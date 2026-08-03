#!/usr/bin/env python3
"""Behavioral audit contracts for the Browser Agent HTTP routes."""

from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "control"
sys.path.insert(0, str(AGENT))

import audit
import token_store

with mock.patch.object(token_store, "ensure_token", return_value="test-browser-token"):
    import app


def handler() -> app.Handler:
    instance = object.__new__(app.Handler)
    instance._send_bytes = mock.Mock()
    instance._send_json = mock.Mock()
    return instance


class BrowserAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        audit.AUDIT_PATH = Path(self.temporary.name) / "audit.jsonl"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_excess_connections_without_starting_threads(self) -> None:
        server = app.BoundedThreadingHTTPServer(
            ("127.0.0.1", 0),
            app.Handler,
            max_concurrency=1,
        )
        accepted, peer = socket.socketpair()
        try:
            self.assertTrue(server._request_slots.acquire(blocking=False))
            server.process_request(accepted, ("127.0.0.1", 1))
            self.assertEqual(peer.recv(1), b"")
        finally:
            peer.close()
            server._request_slots.release()
            server.server_close()

    def test_audit_rejects_raw_values_and_accepts_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "bytes"):
            audit.log("probe", "x", result="ok", bytes=b"private")
        for subject in ("https://user@example.com/?secret=value", "selector#private", "x" * 161):
            with self.subTest(subject=subject), self.assertRaisesRegex(ValueError, "unsafe primary field"):
                audit.log("probe", subject, result="ok")

        trace = audit.log("probe", "x", result="ok", byte_count=7)

        self.assertEqual(len(trace), 32)
        self.assertNotIn("private", audit.AUDIT_PATH.read_text(encoding="utf-8"))

    def test_url_and_opaque_subjects_remove_caller_content(self) -> None:
        raw_url = "https://user:password@example.com/private/path?token=secret#fragment"
        selector = "[data-private='typed-secret']"

        self.assertEqual(audit.url_subject(raw_url), "https://example.com")
        summarized = audit.opaque_subject("selector", selector)
        self.assertRegex(summarized, r"^selector:[0-9]+:[0-9a-f]{16}$")
        self.assertNotIn("typed-secret", summarized)

    def test_audit_rotation_keeps_only_the_bounded_backup_set(self) -> None:
        with mock.patch.object(audit, "MAX_BYTES", 1):
            for index in range(audit.BACKUPS + 2):
                audit.log("probe", f"event:{index}", result="ok")

        self.assertTrue(audit.AUDIT_PATH.exists())
        for index in range(1, audit.BACKUPS + 1):
            self.assertTrue(audit.AUDIT_PATH.with_name(f"audit.jsonl.{index}").exists())
        self.assertFalse(audit.AUDIT_PATH.with_name(f"audit.jsonl.{audit.BACKUPS + 1}").exists())

    def test_dispatch_audit_never_retains_query_or_exception_content(self) -> None:
        route = handler()
        route.path = "/v1/browser/type?token=query-secret"
        route._authed = mock.Mock(return_value=False)
        route._dispatch("POST")

        denied = audit.AUDIT_PATH.read_text(encoding="utf-8")
        self.assertIn("route:/v1/browser/type", denied)
        self.assertNotIn("query-secret", denied)

        audit.AUDIT_PATH.unlink()
        route._authed = mock.Mock(return_value=True)
        route._route = mock.Mock(side_effect=app.validate.ValidationError("selector typed-secret is invalid"))
        route._dispatch("POST")

        failed = audit.AUDIT_PATH.read_text(encoding="utf-8")
        self.assertIn('"reason_code": "validation_error"', failed)
        self.assertNotIn("typed-secret", failed)

    def test_screenshot_route_audits_only_the_payload_size(self) -> None:
        route = handler()
        png = b"\x89PNG-private-image"
        with (
            mock.patch.object(app.screenshot_client, "capture", return_value=png),
            mock.patch.object(app.screenshot_client, "geometry", return_value=(1280, 800)),
            mock.patch.object(app.audit, "log", return_value="trace") as log,
        ):
            route._route_get("/v1/browser/screenshot", {})

        log.assert_called_once_with("screenshot", "root", result="ok", byte_count=len(png))
        route._send_bytes.assert_called_once_with(
            HTTPStatus.OK,
            "image/png",
            png,
            {"X-Screen-Geometry": "1280x800"},
        )

    def test_download_route_audits_only_the_payload_size(self) -> None:
        route = handler()
        payload = b"private-download"
        with (
            mock.patch.object(app.downloads_client, "fetch", return_value=payload),
            mock.patch.object(app.audit, "log", return_value="trace") as log,
        ):
            route._route_get("/v1/browser/downloads/fetch", {"name": ["report.pdf"]})

        log.assert_called_once_with(
            "downloads.fetch",
            audit.opaque_subject("filename", "report.pdf"),
            result="ok",
            byte_count=len(payload),
        )
        route._send_bytes.assert_called_once_with(
            HTTPStatus.OK,
            "application/octet-stream",
            payload,
        )

    def test_type_and_cdp_routes_never_put_user_content_in_the_audit_event(self) -> None:
        route = handler()
        route._body = mock.Mock(return_value={"text": "typed-secret"})
        with (
            mock.patch.object(app, "_type", return_value={"typed_len": 12}),
            mock.patch.object(app.audit, "log", return_value="type-trace") as type_log,
        ):
            route._route_post("/v1/browser/type")
        type_log.assert_called_once_with("type", "input", result="ok", typed_len=12)

        route._body = mock.Mock(return_value={"js": "document.cookie"})
        with (
            mock.patch.object(app, "_cdp_eval", return_value={"value": "redacted"}),
            mock.patch.object(app.audit, "log", return_value="cdp-trace") as cdp_log,
        ):
            route._route_post("/v1/browser/cdp/eval")
        cdp_log.assert_called_once_with("cdp.eval", "expression", result="ok")

    def test_url_and_selector_routes_audit_only_summaries(self) -> None:
        route = handler()
        raw_url = "https://user:password@example.com/private?token=secret#fragment"
        route._body = mock.Mock(return_value={"url": raw_url})
        with mock.patch.object(app, "_navigate", return_value={"url": raw_url}):
            route._route_post("/v1/browser/navigate")

        selector = "[data-secret='typed-secret']"
        with mock.patch.object(app, "_cdp_rect", return_value={"x": 1, "y": 2, "width": 3, "height": 4}):
            route._route_get("/v1/browser/cdp/rect", {"selector": [selector]})

        content = audit.AUDIT_PATH.read_text(encoding="utf-8")
        self.assertIn("https://example.com", content)
        self.assertIn("selector:", content)
        for secret in ("user", "password", "/private", "token", "typed-secret"):
            self.assertNotIn(secret, content)


if __name__ == "__main__":
    unittest.main()
