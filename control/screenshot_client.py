"""The ONLY place the X11 root window is captured from.

Ported from rootfs/usr/local/bin/shimpz-shot: ImageMagick `import -window root`, deliberately NOT
CDP/Page.captureScreenshot — invisible to the page, shows what the DOM hides (overlays, invisible
reCAPTCHA, real rendered state). Moved server-side because the X11 socket never leaves this
container. Depends on svc-kasmvnc/run's `-drinode`-omission fix to avoid a black GBM framebuffer
(unchanged, still lives in this image's s6 override).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import native_process

os.environ.setdefault("DISPLAY", ":1")


class ScreenshotError(Exception):
    """The root window could not be captured."""


def capture() -> bytes:
    """PNG bytes of the whole desktop, straight from the X11 framebuffer."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        result = native_process.capture_root_window(str(out_path))
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise ScreenshotError(
                f"could not capture the screen (DISPLAY={os.environ.get('DISPLAY')}): {(result.stderr or '').strip()}"
            )
        return out_path.read_bytes()
    finally:
        out_path.unlink(missing_ok=True)


def geometry() -> tuple[int, int] | None:
    result = native_process.run_xdotool("getdisplaygeometry")
    if result.returncode != 0 or not result.stdout.strip():
        return None
    parts = result.stdout.split()
    if len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])
