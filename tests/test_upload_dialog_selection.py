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


def _result(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


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

    def test_fails_closed_when_no_dialog_can_be_distinguished(self) -> None:
        responses = [_result("101\n"), _result("Open File - Acme Client\n"), _result("AcmeClient\n")]
        with mock.patch.object(upload_client, "_run", side_effect=responses):
            self.assertIsNone(upload_client._find_dialog("Open File"))


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
