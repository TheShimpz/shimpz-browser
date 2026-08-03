#!/usr/bin/env python3
"""Bounded request-body contracts for the Browser Agent HTTP boundary."""

from __future__ import annotations

import io
import json
import sys
import unittest
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "control"
sys.path.insert(0, str(AGENT))

import token_store

with mock.patch.object(token_store, "ensure_token", return_value="test-browser-token"):
    import app


def body_handler(payload: bytes, *lengths: str) -> app.Handler:
    instance = object.__new__(app.Handler)
    headers = Message()
    for length in lengths:
        headers.add_header("Content-Length", length)
    instance.headers = headers
    instance.rfile = io.BytesIO(payload)
    instance.connection = SimpleNamespace(settimeout=mock.Mock())
    return instance


class BrowserBodyTests(unittest.TestCase):
    def test_body_requires_one_unambiguous_content_length(self) -> None:
        cases = (
            ((), HTTPStatus.LENGTH_REQUIRED),
            (("2", "2"), HTTPStatus.BAD_REQUEST),
            (("-1",), HTTPStatus.BAD_REQUEST),
            (("not-a-number",), HTTPStatus.BAD_REQUEST),
            (("²",), HTTPStatus.BAD_REQUEST),
        )
        for lengths, status in cases:
            with self.subTest(lengths=lengths):
                route = body_handler(b"{}", *lengths)
                with self.assertRaises(app.ApiError) as caught:
                    route._body(app.STANDARD_BODY_MAX_BYTES)
                self.assertEqual(caught.exception.status, status)

        route = body_handler(b"{}", "2")
        route.headers.add_header("Transfer-Encoding", "chunked")
        with self.assertRaises(app.ApiError) as caught:
            route._body(app.STANDARD_BODY_MAX_BYTES)
        self.assertEqual(caught.exception.status, HTTPStatus.BAD_REQUEST)

    def test_body_rejects_oversize_before_reading(self) -> None:
        route = body_handler(b"", str(app.STANDARD_BODY_MAX_BYTES + 1))
        route.rfile = SimpleNamespace(read=mock.Mock(side_effect=AssertionError("body must not be read")))

        with self.assertRaises(app.ApiError) as caught:
            route._body(app.STANDARD_BODY_MAX_BYTES)

        self.assertEqual(caught.exception.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        route.rfile.read.assert_not_called()

    def test_body_rejects_incomplete_and_expired_reads(self) -> None:
        incomplete = body_handler(b"{}", "3")
        with self.assertRaises(app.ApiError) as caught:
            incomplete._body(app.STANDARD_BODY_MAX_BYTES)
        self.assertEqual(caught.exception.status, HTTPStatus.BAD_REQUEST)

        expired = body_handler(b"{}", "2")
        with (
            mock.patch.object(app.time, "monotonic", side_effect=(0.0, 11.0)),
            self.assertRaises(app.ApiError) as caught,
        ):
            expired._body(app.STANDARD_BODY_MAX_BYTES)
        self.assertEqual(caught.exception.status, HTTPStatus.REQUEST_TIMEOUT)
        expired.connection.settimeout.assert_called_once_with(app.HTTP_CONNECTION_TIMEOUT_SECONDS)

    def test_body_parses_with_an_absolute_socket_deadline(self) -> None:
        route = body_handler(b'{"x":1}', "7")
        with mock.patch.object(app.time, "monotonic", side_effect=(5.0, 6.0)):
            self.assertEqual(route._body(app.STANDARD_BODY_MAX_BYTES), {"x": 1})

        self.assertEqual(
            route.connection.settimeout.call_args_list,
            [mock.call(9.0), mock.call(app.HTTP_CONNECTION_TIMEOUT_SECONDS)],
        )

    def test_standard_limit_preserves_the_documented_unicode_text_maximum(self) -> None:
        text = "😀" * app.validate.TEXT_MAX_LEN
        payload = json.dumps({"text": text}).encode("ascii")
        self.assertGreater(len(payload), 64 * 1024)
        self.assertLessEqual(len(payload), app.STANDARD_BODY_MAX_BYTES)

        route = body_handler(payload, str(len(payload)))
        self.assertEqual(route._body(app.STANDARD_BODY_MAX_BYTES), {"text": text})

    def test_routes_select_the_smallest_applicable_body_limit(self) -> None:
        route = object.__new__(app.Handler)
        route._body = mock.Mock(return_value={"url": "https://example.com"})
        route._send_json = mock.Mock()
        with (
            mock.patch.object(app, "_navigate", return_value={"navigated": True}),
            mock.patch.object(app.audit, "log", return_value="trace"),
        ):
            route._route_post("/v1/browser/navigate")
        route._body.assert_called_once_with(app.STANDARD_BODY_MAX_BYTES)

        route._body.reset_mock(return_value=True)
        route._body.return_value = {"filename": "report.pdf"}
        with (
            mock.patch.object(app, "_upload", return_value={"uploaded": True, "mode": "dom"}),
            mock.patch.object(app.audit, "log", return_value="trace"),
        ):
            route._route_post("/v1/browser/upload")
        route._body.assert_called_once_with(app.UPLOAD_BODY_MAX_BYTES)

    def test_unknown_post_route_is_rejected_without_reading(self) -> None:
        route = object.__new__(app.Handler)
        route._body = mock.Mock(side_effect=AssertionError("unknown routes must not read a body"))

        with self.assertRaises(app.ApiError) as caught:
            route._route_post("/v1/browser/unknown")

        self.assertEqual(caught.exception.status, HTTPStatus.NOT_FOUND)
        route._body.assert_not_called()


if __name__ == "__main__":
    unittest.main()
