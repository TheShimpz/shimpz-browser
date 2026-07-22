#!/usr/bin/env python3
"""Behavioral audit contracts for the Browser Agent HTTP routes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "browser-agent"
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

    def test_audit_rejects_raw_values_and_accepts_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "bytes"):
            audit.log("probe", "x", result="ok", bytes=b"private")

        trace = audit.log("probe", "x", result="ok", byte_count=7)

        self.assertEqual(len(trace), 32)
        self.assertNotIn("private", audit.AUDIT_PATH.read_text(encoding="utf-8"))

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
            "report.pdf",
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
        type_log.assert_called_once_with("type", "?", result="ok", typed_len=12)

        route._body = mock.Mock(return_value={"js": "document.cookie"})
        with (
            mock.patch.object(app, "_cdp_eval", return_value={"value": "redacted"}),
            mock.patch.object(app.audit, "log", return_value="cdp-trace") as cdp_log,
        ):
            route._route_post("/v1/browser/cdp/eval")
        cdp_log.assert_called_once_with("cdp.eval", "?", result="ok")


if __name__ == "__main__":
    unittest.main()
