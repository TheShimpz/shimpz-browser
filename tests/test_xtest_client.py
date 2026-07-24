from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

AGENT = Path(__file__).resolve().parents[1] / "browser-agent"
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

    def test_type_text_sends_one_sequence_with_per_character_pauses(self) -> None:
        with (
            mock.patch.object(xtest_client.random, "uniform", side_effect=[0.1, 0.2, 0.3]),
            mock.patch.object(xtest_client.random, "random", side_effect=[0.01, 0.5]),
            mock.patch.object(xtest_client, "_xdo") as run,
        ):
            xtest_client.type_text("a-")

        run.assert_called_once_with(
            "type",
            "--clearmodifiers",
            "--delay",
            "100",
            "--",
            "a-",
            "sleep",
            "0.5",
        )


if __name__ == "__main__":
    unittest.main()
