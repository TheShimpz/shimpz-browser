"""Read-only access to Chrome's download directory — list what's there, fetch one file's bytes.

The directory is PINNED by policy (DownloadDirectory in shimpz-automation.json, see
image/rootfs/etc/opt/chrome/policies/managed/shimpz-automation.json) to a known, fixed path — never
guessed from Chrome's own default resolution (which depends on $HOME and isn't worth depending on).
No model-runtime shared volume exists. An authorized Service consumer fetches one file's bytes per
API call, with the same one-shot-per-call shape as screenshot_client.
"""

from __future__ import annotations

import os
from pathlib import Path

import validate

DOWNLOAD_DIR = Path(os.environ.get("SHIMPZ_BROWSER_DOWNLOAD_DIR", "/config/downloads"))


class DownloadError(Exception):
    """The requested download doesn't exist, isn't a regular file, or resolves outside the download directory."""


def list_downloads() -> list[dict]:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(DOWNLOAD_DIR.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        entries.append({"name": path.name, "size": path.stat().st_size})
    return entries


def _resolve(name: str) -> Path:
    """Resolve `name` to a real path INSIDE DOWNLOAD_DIR, refusing traversal/symlinks.

    `name` is already validate.validate_filename()-checked (no `/`, no leading dot) by the caller,
    but resolve() + a root-containment check is the actual guarantee, not the regex alone.
    """
    candidate = (DOWNLOAD_DIR / name).resolve()
    root = DOWNLOAD_DIR.resolve()
    if candidate != root and root not in candidate.parents:
        raise DownloadError(f"resolved path escapes the download directory: {name!r}")
    if not candidate.is_file():
        raise DownloadError(f"no such download: {name!r}")
    if candidate.is_symlink():
        raise DownloadError(f"refusing a symlink: {name!r}")
    return candidate


def fetch(name: str) -> bytes:
    """One download's bytes, admitted by size before reading and never read past the bound.

    The open file's size is admitted first, then the read is capped one byte past the bound so a
    file Chrome is still growing cannot push the buffered response over DOWNLOAD_MAX_BYTES.
    """
    path = _resolve(name)
    with path.open("rb") as fh:
        validate.validate_download_size(os.fstat(fh.fileno()).st_size)
        data = fh.read(validate.DOWNLOAD_MAX_BYTES + 1)
    validate.validate_download_size(len(data))
    return data
