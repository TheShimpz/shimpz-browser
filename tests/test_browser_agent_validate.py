#!/usr/bin/env python3
"""Unit tests for control/validate.py, the allowlist gate before any XTEST/CDP/FS action.

Every check here is a case where a compromised or buggy `shimpz-brain`
must be refused before it ever reaches xtest_client.py/cdp_client.py/upload_client.py/
downloads_client.py — the actual X11/Chrome/filesystem access.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "control"))
import validate


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_validate_coord():
    for bad in (-1, 4097, 1.5, True, "10", None):
        try:
            validate.validate_coord(bad, "x")
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in (0, 500, 4096):
        check(validate.validate_coord(good, "x") == good, f"{good} passes")


def test_validate_button():
    for bad in ("LEFT", "middle-click", "", None, 1):
        try:
            validate.validate_button(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in ("left", "right", "middle"):
        check(validate.validate_button(good) == good, f"{good} passes")


def test_validate_count():
    for bad in (0, -1, 11, 1.5, True, None):
        try:
            validate.validate_count(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in (1, 5, 10):
        check(validate.validate_count(good) == good, f"{good} passes")


def test_validate_key_rejects_shell_metacharacters_and_bad_charset():
    for bad in ("ctrl+l; rm -rf /", "a b", "$(whoami)", "", "a" * 65, None, 123):
        try:
            validate.validate_key(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in ("Return", "ctrl+l", "alt+F4", "ctrl+shift+l"):
        check(validate.validate_key(good) == good, f"{good!r} passes")


def test_validate_text_bounds():
    for bad in ("", "a" * 20_001, None, 123):
        try:
            validate.validate_text(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_text("hello") == "hello", "a real string passes")
    check(validate.validate_text("a" * 20_000) == "a" * 20_000, "exactly the max length passes")


def test_validate_scroll():
    for bad_dir in ("sideways", "UP", "", None):
        try:
            validate.validate_scroll(bad_dir, 3)
            check(False, f"must reject direction {bad_dir!r}")
        except validate.ValidationError:
            check(True, f"rejected direction {bad_dir!r}")
    for bad_amount in (0, -1, 51, 1.5, True, "3"):
        try:
            validate.validate_scroll("up", bad_amount)
            check(False, f"must reject amount {bad_amount!r}")
        except validate.ValidationError:
            check(True, f"rejected amount {bad_amount!r}")
    check(validate.validate_scroll("down", 5) == ("down", 5), "a real direction+amount passes")


def test_validate_js_bounds():
    for bad in ("", None, 123, "x" * 20_001):
        try:
            validate.validate_js(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_js("document.title") == "document.title", "real JS passes")


def test_validate_selector_bounds():
    for bad in ("", None, 123, "x" * 501):
        try:
            validate.validate_selector(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_selector("#avatar") == "#avatar", "a real selector passes")


def test_validate_url_hint_optional():
    check(validate.validate_url_hint(None) is None, "None passes through as None")
    for bad in (123, "x" * 501):
        try:
            validate.validate_url_hint(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_url_hint("linkedin.com") == "linkedin.com", "a real hint passes")


def test_validate_navigate_url_requires_http_scheme():
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x", "", None, "example.com"):
        try:
            validate.validate_navigate_url(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in ("http://example.com", "https://example.com/path?q=1"):
        check(validate.validate_navigate_url(good) == good, f"{good!r} passes")


def test_validate_wait_seconds_bounds():
    for bad in (0, 0.5, 31, -1, True, "6", None):
        try:
            validate.validate_wait_seconds(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_wait_seconds(6) == 6.0, "a real int passes as float")
    check(validate.validate_wait_seconds(1.0) == 1.0, "the min bound passes")
    check(validate.validate_wait_seconds(30.0) == 30.0, "the max bound passes")


def test_validate_filename_rejects_traversal_and_separators():
    for bad in ("../../etc/passwd", "a/b", "a\\b", ".", "..", "", None, 123, "a" * 201):
        try:
            validate.validate_filename(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    for good in ("logo.png", "report_2026-07-04.pdf", "a-b.c"):
        check(validate.validate_filename(good) == good, f"{good!r} passes")


def test_validate_upload_mode():
    for bad in ("dom ", "NATIVE", "", None, "exec"):
        try:
            validate.validate_upload_mode(bad)
            check(False, f"must reject {bad!r}")
        except validate.ValidationError:
            check(True, f"rejected {bad!r}")
    check(validate.validate_upload_mode("dom") == "dom", "dom passes")
    check(validate.validate_upload_mode("native") == "native", "native passes")


def test_validate_upload_size_bounds():
    for bad in (0, -1, validate.UPLOAD_MAX_BYTES + 1):
        try:
            validate.validate_upload_size(bad)
            check(False, f"must reject {bad}")
        except validate.ValidationError:
            check(True, f"rejected {bad}")
    check(validate.validate_upload_size(1) == 1, "1 byte passes")
    check(
        validate.validate_upload_size(validate.UPLOAD_MAX_BYTES) == validate.UPLOAD_MAX_BYTES, "exactly the max passes"
    )


def test_validate_download_size_bounds():
    try:
        validate.validate_download_size(validate.DOWNLOAD_MAX_BYTES + 1)
        check(False, "must reject over-limit size")
    except validate.ValidationError:
        check(True, "rejected over-limit size")
    check(validate.validate_download_size(0) == 0, "an empty file passes (0 is a valid size)")
    check(
        validate.validate_download_size(validate.DOWNLOAD_MAX_BYTES) == validate.DOWNLOAD_MAX_BYTES,
        "exactly the max passes",
    )


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite


if __name__ == "__main__":
    unittest.main()
