#!/usr/bin/env python3
"""Bounded download reads for the Browser download catalog."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "control"))
import downloads_client

import validate


class DownloadFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        patcher = mock.patch.object(downloads_client, "DOWNLOAD_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temporary.cleanup)

    def test_returns_a_file_at_the_bound(self) -> None:
        (self.root / "report.pdf").write_bytes(b"1234")
        with mock.patch.object(validate, "DOWNLOAD_MAX_BYTES", 4):
            self.assertEqual(downloads_client.fetch("report.pdf"), b"1234")

    def test_rejects_an_oversized_file_by_metadata_before_reading(self) -> None:
        (self.root / "large.bin").write_bytes(b"12345")
        opened = mock.MagicMock()
        opened.__enter__.return_value = SimpleNamespace(
            fileno=lambda: 0,
            read=mock.Mock(side_effect=AssertionError("an oversized download must not be read")),
        )
        with (
            mock.patch.object(validate, "DOWNLOAD_MAX_BYTES", 4),
            mock.patch.object(downloads_client.os, "fstat", return_value=SimpleNamespace(st_size=5)),
            mock.patch.object(Path, "open", return_value=opened),
            self.assertRaises(validate.ValidationError),
        ):
            downloads_client.fetch("large.bin")

    def test_caps_the_read_when_the_file_grows_after_admission(self) -> None:
        (self.root / "growing.bin").write_bytes(b"x" * 64)
        real_fstat = os.fstat
        reads = []
        real_open = Path.open

        def tracking_open(path: Path, *args: object, **kwargs: object):
            handle = real_open(path, *args, **kwargs)
            real_read = handle.read

            def bounded_read(size: int = -1) -> bytes:
                reads.append(size)
                return real_read(size)

            handle.read = bounded_read
            return handle

        with (
            mock.patch.object(validate, "DOWNLOAD_MAX_BYTES", 4),
            mock.patch.object(
                downloads_client.os,
                "fstat",
                side_effect=lambda fd: SimpleNamespace(st_size=1, st_mode=real_fstat(fd).st_mode),
            ),
            mock.patch.object(Path, "open", tracking_open),
            self.assertRaises(validate.ValidationError),
        ):
            downloads_client.fetch("growing.bin")
        self.assertEqual(reads, [5])

    def test_refuses_missing_and_escaping_names(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "private.bin").write_bytes(b"x")
        (self.root / "escape.bin").symlink_to(Path(outside.name) / "private.bin")
        for name in ("missing.bin", "escape.bin"):
            with self.subTest(name=name), self.assertRaises(downloads_client.DownloadError):
                downloads_client.fetch(name)


if __name__ == "__main__":
    unittest.main()
