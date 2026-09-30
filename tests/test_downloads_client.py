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

    def _regular_metadata(self, size: int):
        real_fstat = os.fstat

        def fstat(fd: int) -> SimpleNamespace:
            metadata = real_fstat(fd)
            return SimpleNamespace(st_size=size, st_mode=metadata.st_mode, st_nlink=metadata.st_nlink)

        return fstat

    def _open_descriptors(self) -> int:
        return len(list(Path("/proc/self/fd").iterdir()))

    def test_rejects_an_oversized_file_by_metadata_before_reading(self) -> None:
        (self.root / "large.bin").write_bytes(b"12345")
        with (
            mock.patch.object(validate, "DOWNLOAD_MAX_BYTES", 4),
            mock.patch.object(downloads_client.os, "read", side_effect=AssertionError("oversized download read")),
            self.assertRaises(validate.ValidationError),
        ):
            downloads_client.fetch("large.bin")

    def test_caps_the_read_when_the_file_grows_after_admission(self) -> None:
        (self.root / "growing.bin").write_bytes(b"x" * 64)
        real_read = os.read
        reads = []

        def tracking_read(fd: int, size: int) -> bytes:
            reads.append(size)
            return real_read(fd, 1)

        with (
            mock.patch.object(validate, "DOWNLOAD_MAX_BYTES", 4),
            mock.patch.object(downloads_client.os, "fstat", side_effect=self._regular_metadata(1)),
            mock.patch.object(downloads_client.os, "read", tracking_read),
            self.assertRaises(validate.ValidationError),
        ):
            downloads_client.fetch("growing.bin")
        self.assertEqual(reads, [5, 4, 3, 2, 1])

    def test_refuses_missing_escaping_and_non_regular_names(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (Path(outside.name) / "private.bin").write_bytes(b"x")
        (self.root / "escape.bin").symlink_to(Path(outside.name) / "private.bin")
        (self.root / "linked.bin").write_bytes(b"x")
        os.link(self.root / "linked.bin", self.root / "second-link.bin")
        os.mkfifo(self.root / "pipe.bin")
        (self.root / "nested").mkdir()
        before = self._open_descriptors()
        for name in ("missing.bin", "escape.bin", "linked.bin", "pipe.bin", "nested", ".", ".."):
            with self.subTest(name=name), self.assertRaises(downloads_client.DownloadError):
                downloads_client.fetch(name)
        self.assertEqual(self._open_descriptors(), before)

    def test_refuses_an_unavailable_or_symlinked_download_directory(self) -> None:
        (self.root / "real").mkdir()
        (self.root / "real" / "report.pdf").write_bytes(b"x")
        (self.root / "alias").symlink_to(self.root / "real", target_is_directory=True)
        for directory in (self.root / "missing", self.root / "alias"):
            with (
                self.subTest(directory=directory.name),
                mock.patch.object(downloads_client, "DOWNLOAD_DIR", directory),
                self.assertRaises(downloads_client.DownloadError),
            ):
                downloads_client.fetch("report.pdf")

    def test_refuses_a_symlink_swapped_in_after_validation(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        private = Path(outside.name) / "private.bin"
        private.write_bytes(b"outside secret")
        download = self.root / "report.pdf"
        download.write_bytes(b"download")
        real_open = os.open

        def swap_before_open(path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
            if dir_fd is not None:
                download.unlink()
                download.symlink_to(private)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        self.assertEqual(downloads_client.list_downloads(), [{"name": "report.pdf", "size": 8}])
        with (
            mock.patch.object(downloads_client.os, "open", swap_before_open),
            self.assertRaises(downloads_client.DownloadError),
        ):
            downloads_client.fetch("report.pdf")

    def test_reads_the_pinned_file_when_the_name_is_swapped_after_open(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        private = Path(outside.name) / "private.bin"
        private.write_bytes(b"outside secret")
        download = self.root / "report.pdf"
        download.write_bytes(b"download")
        real_open = os.open

        def swap_after_open(path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
            descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
            if dir_fd is not None:
                download.rename(self.root / "moved.pdf")
                download.symlink_to(private)
            return descriptor

        with mock.patch.object(downloads_client.os, "open", swap_after_open):
            self.assertEqual(downloads_client.fetch("report.pdf"), b"download")


if __name__ == "__main__":
    unittest.main()
