"""Read-only access to Chrome's download directory — list what's there, fetch one file's bytes.

The directory is PINNED by policy (DownloadDirectory in shimpz-automation.json, see
image/rootfs/etc/opt/chrome/policies/managed/shimpz-automation.json) to a known, fixed path — never
guessed from Chrome's own default resolution (which depends on $HOME and isn't worth depending on).
No model-runtime shared volume exists. An authorized Service consumer fetches one file's bytes per
API call, with the same one-shot-per-call shape as screenshot_client.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import validate

DOWNLOAD_DIR = Path(os.environ.get("SHIMPZ_BROWSER_DOWNLOAD_DIR", "/config/downloads"))
READ_CHUNK_BYTES = 1024 * 1024


class DownloadError(Exception):
    """The requested download doesn't exist, isn't one regular file, or isn't directly inside the download directory."""


def list_downloads() -> list[dict]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(DOWNLOAD_DIR.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        entries.append({"name": path.name, "size": path.stat().st_size})
    return entries


def _open_download(name: str) -> int:
    """Open the basename `name` relative to a pinned DOWNLOAD_DIR descriptor, never following a symlink.

    `name` is already validate.validate_filename()-checked by the caller, but the guarantee is the
    descriptor walk: a name swapped for a symlink after any earlier check fails this open instead of
    reaching a file outside the directory, and every later check and read uses the returned descriptor.
    """
    try:
        directory = os.open(DOWNLOAD_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise DownloadError("download directory is unavailable") from exc
    try:
        return os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    except OSError as exc:
        raise DownloadError(f"no such download: {name!r}") from exc
    finally:
        os.close(directory)


def fetch(name: str) -> bytes:
    """One regular download's bytes, admitted by metadata before reading and never read past the bound.

    The open file's type and size are admitted first, then the read through that same descriptor is
    capped one byte past the bound so a file Chrome is still growing cannot push the buffered response
    over DOWNLOAD_MAX_BYTES.
    """
    descriptor = _open_download(name)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise DownloadError(f"refusing a download that is not one regular file: {name!r}")
        validate.validate_download_size(metadata.st_size)
        limit = validate.DOWNLOAD_MAX_BYTES + 1
        data = bytearray()
        while len(data) < limit and (chunk := os.read(descriptor, min(READ_CHUNK_BYTES, limit - len(data)))):
            data += chunk
    finally:
        os.close(descriptor)
    validate.validate_download_size(len(data))
    return bytes(data)
