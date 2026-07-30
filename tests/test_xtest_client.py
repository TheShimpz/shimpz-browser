from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
