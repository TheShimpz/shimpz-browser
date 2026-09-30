#!/usr/bin/env python3
"""Focused checks for provider-neutral native-dialog selection."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "control"))
import upload_client


def _result(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


_GEOMETRY = "WINDOW=202\nX=100\nY=50\nWIDTH=600\nHEIGHT=400\nSCREEN=0\n"


class _FakeX:
    """One open file dialog (window 202) on a scripted X display driven through xdotool argv."""

    def __init__(self, closes_on: tuple[str, ...] | None = None, failing: frozenset[str] = frozenset()) -> None:
        self.closes_on = closes_on
        self.failing = failing
        self.dialog_open = True
        self.calls: list[tuple[str, ...]] = []
        self.geometry = _GEOMETRY

    def __call__(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(arguments)
        operation = arguments[0]
        if operation in self.failing:
            return _result(returncode=1, stderr="Error: Can't open display")
        if operation == "search":
            return _result("202\n") if self.dialog_open else _result(returncode=1)
        if operation == "getwindowname":
            return _result("Open File\n")
        if operation == "getwindowclassname":
            return _result("AcmeClient\n")
        if operation == "getwindowgeometry":
            return _result(self.geometry)
        if arguments == self.closes_on:
            self.dialog_open = False
        return _result()

    def inputs(self) -> list[str]:
        lookups = {"search", "getwindowname", "getwindowclassname", "getwindowgeometry"}
        return [call[0] for call in self.calls if call[0] not in lookups]


class DialogSelectionTests(unittest.TestCase):
    def test_ignores_an_application_window_and_returns_the_dialog(self) -> None:
        responses = [
            _result("101\n202\n"),
            _result("Open File - Acme Client\n"),
            _result("AcmeClient\n"),
            _result("Open File\n"),
            _result("AcmeClient\n"),
        ]
        with mock.patch.object(upload_client, "_run", side_effect=responses) as run:
            self.assertEqual(upload_client._find_dialog("Open File"), "202")
        self.assertEqual(
            run.call_args_list,
            [
                mock.call("search", "--name", "Open File"),
                mock.call("getwindowname", "101"),
                mock.call("getwindowclassname", "101"),
                mock.call("getwindowname", "202"),
                mock.call("getwindowclassname", "202"),
            ],
        )

    def test_distinguishes_confirmed_absence_from_lookup_failure(self) -> None:
        with mock.patch.object(upload_client, "_run", return_value=_result(returncode=1)):
            self.assertIsNone(upload_client._find_dialog("Open File"))

        failures = (
            [_result(returncode=1, stderr="Failed to compile regex")],
            [_result(returncode=0)],
            [_result("101\n"), _result(returncode=1, stderr="BadWindow"), _result("AcmeClient\n")],
        )
        for responses in failures:
            with (
                self.subTest(responses=responses),
                mock.patch.object(upload_client, "_run", side_effect=responses),
                self.assertRaises(upload_client.UploadError) as caught,
            ):
                upload_client._find_dialog("Open File")
            self.assertEqual(str(caught.exception), "file dialog lookup failed")

    def test_fails_closed_when_no_dialog_can_be_distinguished(self) -> None:
        responses = [_result("101\n"), _result("Open File - Acme Client\n"), _result("AcmeClient\n")]
        with mock.patch.object(upload_client, "_run", side_effect=responses):
            self.assertIsNone(upload_client._find_dialog("Open File"))


class NativeUploadCompletionTests(unittest.TestCase):
    def upload(self, display: _FakeX) -> str:
        with (
            mock.patch.object(upload_client, "_run", display),
            mock.patch.object(upload_client.time, "sleep"),
        ):
            return upload_client.upload_native("upload-report.pdf", "Open File")

    def test_path_and_enter_completes_when_x_confirms_the_dialog_closed(self) -> None:
        display = _FakeX(closes_on=("key", "--clearmodifiers", "Return"))
        self.assertEqual(self.upload(display), "'upload-report.pdf' opened (path + Enter)")
        self.assertEqual(display.inputs(), ["windowactivate", "key", "type", "key"])

    def test_failed_input_commands_are_never_reported_as_completion(self) -> None:
        for operation, sent in (("windowactivate", 1), ("type", 3), ("click", 8)):
            display = _FakeX(failing=frozenset({operation}))
            with self.subTest(operation=operation), self.assertRaises(upload_client.UploadError) as caught:
                self.upload(display)
            self.assertEqual(str(caught.exception), f"native input {operation} failed")
            self.assertEqual(len(display.inputs()), sent)

    def test_a_failed_dialog_lookup_is_not_mistaken_for_a_closed_dialog(self) -> None:
        display = _FakeX()
        original = display.__call__

        def search_fails_after_enter(*arguments: str) -> subprocess.CompletedProcess[str]:
            if arguments[0] == "search" and "Return" in {call[-1] for call in display.calls}:
                display.calls.append(arguments)
                return _result(returncode=1, stderr="Error: Can't open display")
            return original(*arguments)

        with (
            mock.patch.object(upload_client, "_run", search_fails_after_enter),
            mock.patch.object(upload_client.time, "sleep"),
            self.assertRaises(upload_client.UploadError) as caught,
        ):
            upload_client.upload_native("upload-report.pdf", "Open File")
        self.assertEqual(str(caught.exception), "file dialog lookup failed")

    def test_mnemonic_and_click_fallbacks_complete_only_after_confirmed_close(self) -> None:
        display = _FakeX(closes_on=("key", "--clearmodifiers", "alt+a"))
        self.assertEqual(self.upload(display), "'upload-report.pdf' opened (mnemonic alt+a)")

        display = _FakeX(closes_on=("click", "1"))
        self.assertEqual(self.upload(display), "'upload-report.pdf' opened (real click on Open)")
        self.assertIn(("mousemove", "648", "420"), display.calls)

    def test_a_dialog_that_never_closes_fails_after_every_fallback(self) -> None:
        display = _FakeX()
        with self.assertRaises(upload_client.UploadError) as caught:
            self.upload(display)
        self.assertIn("dialog still open", str(caught.exception))
        self.assertEqual(display.inputs().count("click"), 4)

    def test_unreadable_dialog_geometry_fails_closed(self) -> None:
        for geometry, failing in (("", frozenset({"getwindowgeometry"})), ("X=1\nY=2\n", frozenset())):
            display = _FakeX(failing=failing)
            display.geometry = geometry
            with self.subTest(geometry=geometry), self.assertRaises(upload_client.UploadError) as caught:
                self.upload(display)
            self.assertEqual(str(caught.exception), "file dialog geometry lookup failed")
            self.assertNotIn("click", display.inputs())


class NativeUploadErrorTests(unittest.TestCase):
    def test_missing_dialog_error_never_echoes_the_caller_pattern(self) -> None:
        with (
            mock.patch.object(upload_client, "_find_dialog", return_value=None),
            mock.patch.object(upload_client.time, "sleep"),
            self.assertRaises(upload_client.UploadError) as caught,
        ):
            upload_client.upload_native("upload-report.pdf", "caller-secret-pattern")

        self.assertEqual(str(caught.exception), "no file dialog found")


if __name__ == "__main__":
    unittest.main()
