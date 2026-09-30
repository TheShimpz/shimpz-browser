from __future__ import annotations

import subprocess
import sys
import time
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
            timeout=native_process.TIMEOUT_SECONDS,
        )

    def test_kills_a_blocked_child_and_raises_a_closed_error(self) -> None:
        children = []
        real_popen = subprocess.Popen

        def tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen:
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        with (
            mock.patch.object(native_process, "_EXECUTABLES", frozenset({"/bin/sleep"})),
            mock.patch.object(native_process, "TIMEOUT_SECONDS", 0.2),
            mock.patch.object(native_process.subprocess, "Popen", tracking_popen),
        ):
            started = time.monotonic()
            with self.assertRaises(native_process.NativeProcessError) as caught:
                native_process._run("/bin/sleep", ("30",))
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 5)
        self.assertEqual(str(caught.exception), "sleep timed out after 0.2s")
        self.assertIsNone(caught.exception.__cause__)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].returncode, -9, "the timed-out child was killed and reaped")

    def test_timeout_error_never_carries_argv_or_output(self) -> None:
        expired = subprocess.TimeoutExpired(["/usr/bin/xdotool", "type", "--", "typed-secret"], 30, "out", "err")
        with (
            mock.patch.object(native_process.subprocess, "run", side_effect=expired),
            self.assertRaises(native_process.NativeProcessError) as caught,
        ):
            native_process.run_xdotool("type", "--", "typed-secret")

        self.assertNotIn("typed-secret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_rejects_any_executable_outside_the_image_allowlist(self) -> None:
        with (
            mock.patch.object(native_process.subprocess, "run") as run,
            self.assertRaisesRegex(ValueError, "unsupported browser-agent executable"),
        ):
            native_process._run("/bin/sh", ("-c", "true"))

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
