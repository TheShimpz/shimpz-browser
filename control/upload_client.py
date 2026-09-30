"""File upload into the browser — two modes, ported from two separate CLIs that used to run here.

`mode="dom"` — rootfs/usr/local/bin/chrome-upload's approach: CDP DOM.setFileInputFiles on a page's
<input type=file>, no OS dialog at all (see cdp_client.upload_dom).

`mode="native"` — rootfs/usr/local/bin/uiupload's approach: complete a native GTK/Qt "Open File"
dialog via REAL XTEST events (xdotool). Needed because synthetic events (XSendEvent) are silently
discarded by GTK. Faithful port of uiupload's exact fallback sequence: Ctrl+L + path + Enter, then
mnemonic (Alt+O / Alt+A), then a real click on the geometrically-derived "Open" button.

Both modes receive the file's bytes over HTTP and write them to an EPHEMERAL temp path inside this
container first — neither mode ever assumes a path shared with another container.
"""

from __future__ import annotations

import os
import subprocess
import time

import native_process

os.environ.setdefault("DISPLAY", ":1")

DEFAULT_DIALOG_RE = "Open File|Save File|Save As|Open Files|Select|Abrir|Salvar|Selecionar arquivo"


class UploadError(Exception):
    """Neither CDP DOM injection nor native-dialog completion could attach the file."""


def _run(*a: str) -> subprocess.CompletedProcess:
    return native_process.run_xdotool(*a)


def _title_identifies_application(title: str, window_class: str) -> bool:
    compact_title = "".join(char for char in title.casefold() if char.isalnum())
    compact_class = "".join(char for char in window_class.casefold() if char.isalnum())
    return bool(compact_title and compact_class and (compact_class in compact_title or compact_title in compact_class))


def _input(*arguments: str) -> None:
    """Send one xdotool input command; a failed command aborts the upload, never counts as done."""
    if _run(*arguments).returncode != 0:
        raise UploadError(f"native input {arguments[0]} failed")


def _find_dialog(title_regex: str) -> str | None:
    """The newest open file dialog, None only when X confirms no match, or UploadError.

    xdotool search exits 1 with no output exactly when nothing matches; any other failure (X
    unreachable, invalid pattern, a window whose name or class cannot be read) is a lookup failure
    and must never be mistaken for the dialog having closed.
    """
    search = _run("search", "--name", title_regex)
    if search.returncode == 1 and not search.stdout.strip() and not search.stderr.strip():
        return None
    if search.returncode != 0 or not search.stdout.strip():
        raise UploadError("file dialog lookup failed")
    candidates = []
    for window_id in search.stdout.split():
        name = _run("getwindowname", window_id)
        window_class = _run("getwindowclassname", window_id)
        if name.returncode != 0 or window_class.returncode != 0:
            raise UploadError("file dialog lookup failed")
        if _title_identifies_application(name.stdout.strip(), window_class.stdout.strip()):
            continue
        candidates.append(window_id)
    return candidates[-1] if candidates else None


def _wait_for_dialog(title_regex: str) -> str:
    for _ in range(40):  # ~8s wait for the dialog to appear
        wid = _find_dialog(title_regex)
        if wid:
            return wid
        time.sleep(0.2)
    raise UploadError("no file dialog found")


def _open_button_points(wid: str) -> list[tuple[int, int]]:
    """Candidate points on the dialog's Open button (bottom-right corner of the window)."""
    geom = _run("getwindowgeometry", "--shell", wid)
    if geom.returncode != 0:
        raise UploadError("file dialog geometry lookup failed")
    values = dict(line.split("=", 1) for line in geom.stdout.splitlines() if "=" in line)
    try:
        x, y, width, height = (int(values[key]) for key in ("X", "Y", "WIDTH", "HEIGHT"))
    except KeyError, ValueError:
        raise UploadError("file dialog geometry lookup failed") from None
    return [(x + width - 52, y + height - dy) for dy in (30, 38, 22, 46)]


def upload_native(path: str, title_regex: str = DEFAULT_DIALOG_RE) -> str:
    """Complete an already-open native file dialog with `path`. Raises UploadError on failure."""
    wid = _wait_for_dialog(title_regex)
    _input("windowactivate", "--sync", wid)
    time.sleep(0.2)
    _input("key", "--clearmodifiers", "ctrl+l")  # GTK location bar
    time.sleep(0.2)
    _input("type", "--clearmodifiers", "--delay", "12", path)
    time.sleep(0.2)
    _input("key", "--clearmodifiers", "Return")
    time.sleep(0.5)
    if not _find_dialog(title_regex):
        return f"'{path}' opened (path + Enter)"

    # A) GTK Open-button mnemonic (no coordinates): "_Open" -> Alt+O; "_Abrir" -> Alt+A.
    for mnemonic in ("alt+o", "alt+a"):
        _input("key", "--clearmodifiers", mnemonic)
        time.sleep(0.5)
        if not _find_dialog(title_regex):
            return f"'{path}' opened (mnemonic {mnemonic})"

    # B) Real XTEST click on the Open button.
    for ox, oy in _open_button_points(wid):
        _input("mousemove", str(ox), str(oy))
        time.sleep(0.12)
        _input("click", "1")
        time.sleep(0.4)
        if not _find_dialog(title_regex):
            return f"'{path}' opened (real click on Open)"

    raise UploadError("dialog still open after path+Enter, mnemonic, and coordinate-click fallbacks")
