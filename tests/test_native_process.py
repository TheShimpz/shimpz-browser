from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "control"
sys.path.insert(0, str(AGENT))

import native_process


class NativeProcessTests(unittest.TestCase):
    def test_runs_only_the_fixed_tool_as_captured_argv(self) -> None:
        completed = subprocess.CompletedProcess([], 7, "output", "failure")
        with mock.patch.object(native_process.subprocess, "run", return_value=completed) as run:
            result = native_process.run_xdotool("type", "--", "hello; still argv")

        self.assertIs(result, completed)
        run.assert_called_once_with(
            ["/usr/bin/xdotool", "type", "--", "hello; still argv"],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_rejects_any_executable_outside_the_image_allowlist(self) -> None:
        with (
            mock.patch.object(native_process.subprocess, "run") as run,
            self.assertRaisesRegex(ValueError, "unsupported browser-agent executable"),
        ):
            native_process._run("/bin/sh", ("-c", "true"))

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
