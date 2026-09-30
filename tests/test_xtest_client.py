from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "control"
sys.path.insert(0, str(AGENT))

import xtest_client


class XTestClientTests(unittest.TestCase):
    def test_move_sends_one_paced_xdotool_sequence(self) -> None:
        with (
            mock.patch.object(xtest_client, "pos", return_value=(1, 2)),
            mock.patch.object(xtest_client, "_windmouse", return_value=[(3, 4), (5, 6)]),
            mock.patch.object(xtest_client.random, "randint", side_effect=[0, 0]),
            mock.patch.object(xtest_client.random, "uniform", side_effect=[0.01, 0.02]),
            mock.patch.object(xtest_client, "_xdo") as run,
        ):
            self.assertEqual(xtest_client.move(5, 6), (5, 6))

        run.assert_called_once_with(
            "mousemove",
            "3",
            "4",
            "sleep",
            "0.01",
            "mousemove",
            "5",
            "6",
            "sleep",
            "0.02",
        )

    def test_type_text_sends_each_chunk_in_argv_safe_invocations(self) -> None:
        with (
            mock.patch.object(xtest_client, "_TYPE_CHUNK_SIZE", 2),
            mock.patch.object(xtest_client.random, "uniform", side_effect=[0.1, 0.2, 0.3, 0.4]),
            mock.patch.object(xtest_client.random, "random", return_value=0.5),
            mock.patch.object(xtest_client, "_xdo") as run,
            mock.patch.object(xtest_client.time, "sleep") as sleep,
        ):
            xtest_client.type_text("ab-c")

        self.assertEqual(
            run.call_args_list,
            [
                mock.call("type", "--clearmodifiers", "--delay", "100", "--", "ab"),
                mock.call("type", "--clearmodifiers", "--delay", "300", "--", "-c"),
            ],
        )
        sleep.assert_called_once_with(0.2)

    def test_type_text_empty_text_is_a_no_op(self) -> None:
        with (
            mock.patch.object(xtest_client, "_xdo") as run,
            mock.patch.object(xtest_client.time, "sleep") as sleep,
        ):
            xtest_client.type_text("")

        run.assert_not_called()
        sleep.assert_not_called()


class XTestErrorRedactionTests(unittest.TestCase):
    def test_failed_typing_never_returns_typed_text_argv_or_stderr(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "stdout typed-secret", "stderr typed-secret")
        with (
            mock.patch.object(xtest_client.native_process, "run_xdotool", return_value=failed),
            self.assertRaises(xtest_client.XTestError) as caught,
        ):
            xtest_client.type_text("typed-secret")

        self.assertEqual(str(caught.exception), "xdotool type failed (rc=1)")

    def test_failed_pointer_lookups_return_only_closed_messages(self) -> None:
        cases = (
            (subprocess.CompletedProcess([], 1, "", "stderr-detail"), "xdotool getmouselocation failed (rc=1)"),
            (
                subprocess.CompletedProcess([], 0, "SCREEN=stdout-detail\n", ""),
                "xdotool getmouselocation returned no pointer position",
            ),
        )
        for result, message in cases:
            with (
                self.subTest(message=message),
                mock.patch.object(xtest_client.native_process, "run_xdotool", return_value=result),
                self.assertRaises(xtest_client.XTestError) as caught,
            ):
                xtest_client.pos()
            self.assertEqual(str(caught.exception), message)


if __name__ == "__main__":
    unittest.main()
