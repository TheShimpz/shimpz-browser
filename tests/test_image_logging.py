#!/usr/bin/env python3
"""Supervised Browser processes never write unrotated log files onto the persistent volume."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOTFS = Path(__file__).resolve().parents[1] / "image" / "rootfs"
# Every output redirection in a shell script: `>`, `>>`, or an fd-numbered form, and its target.
_REDIRECT = re.compile(r"(?<![<>&0-9])[0-9]?>>?\s*(?!&)(\S+)")


class ImageLoggingTests(unittest.TestCase):
    def test_autostart_sends_process_output_only_to_the_container_log_or_null(self) -> None:
        script = (ROOTFS / "defaults" / "autostart").read_text(encoding="utf-8")
        body = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))

        targets = _REDIRECT.findall(body)

        self.assertTrue(targets, "the Chrome launch still discards its own output")
        self.assertEqual(set(targets), {"/dev/null"})


if __name__ == "__main__":
    unittest.main()
