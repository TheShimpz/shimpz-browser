"""Allowlist validation for browser-agent — runs BEFORE any XTEST/CDP/filesystem action.

Nothing here touches X11/Chrome/the filesystem; it only decides yes/no and returns validated
values the caller (app.py) turns into xtest_client.py/cdp_client.py/upload_client.py/
downloads_client.py calls. Same shape as every other component's own validate.py — the actual
security boundary, not the client that acts on its output.
"""

from __future__ import annotations

import re

# The locked desktop resolution (svc-kasmvnc/run's SHIMPZ_SCREEN, default 1280x800) bounds every real
# coordinate — a click far outside it is either a caller bug or a coordinate meant for a different
# screen size; refuse it rather than clicking wherever X clamps it to.
COORD_MIN, COORD_MAX = 0, 4096
TEXT_MAX_LEN = 20_000
JS_MAX_LEN = 20_000
SELECTOR_MAX_LEN = 500
URL_HINT_MAX_LEN = 500
FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
UPLOAD_MAX_BYTES = 50 * 1024 * 1024
DOWNLOAD_MAX_BYTES = 200 * 1024 * 1024
# xdotool key/keysym syntax: letters, digits, +/_ (combos like ctrl+shift+l), and X keysym names
# (Return, Escape, F5, ...) — all ASCII, no shell metacharacters (xdotool receives this as a single
# argv element via subprocess, never a shell string, but a narrow charset is still the honest
# allowlist for "this is a keysym/combo", not a shell-injection concern per se).
KEY_RE = re.compile(r"^[A-Za-z0-9+_]{1,64}$")
SCROLL_DIRECTIONS = frozenset({"up", "down"})
SCROLL_AMOUNT_MAX = 50
CLICK_BUTTONS = frozenset({"left", "right", "middle"})
CLICK_COUNT_MAX = 10
UPLOAD_MODES = frozenset({"dom", "native"})


class ValidationError(Exception):
    """A browser-agent request failed the allowlist — nothing was touched."""


def validate_coord(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field} must be an integer: {value!r}")
    if not (COORD_MIN <= value <= COORD_MAX):
        raise ValidationError(f"{field} {value} outside {COORD_MIN}-{COORD_MAX}")
    return value


def validate_button(value: object) -> str:
    if value not in CLICK_BUTTONS:
        raise ValidationError(f"button must be one of {sorted(CLICK_BUTTONS)}: {value!r}")
    return value


def validate_count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"count must be an integer: {value!r}")
    if not (1 <= value <= CLICK_COUNT_MAX):
        raise ValidationError(f"count {value} outside 1-{CLICK_COUNT_MAX}")
    return value


def validate_key(value: object) -> str:
    if not isinstance(value, str) or not KEY_RE.match(value):
        raise ValidationError(f"key/combo must match {KEY_RE.pattern!r}: {value!r}")
    return value


def validate_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"text must be a string: {value!r}")
    if not (1 <= len(value) <= TEXT_MAX_LEN):
        raise ValidationError(f"text length {len(value)} outside 1-{TEXT_MAX_LEN}")
    return value


def validate_scroll(direction: object, amount: object) -> tuple[str, int]:
    if direction not in SCROLL_DIRECTIONS:
        raise ValidationError(f"direction must be one of {sorted(SCROLL_DIRECTIONS)}: {direction!r}")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ValidationError(f"amount must be an integer: {amount!r}")
    if not (1 <= amount <= SCROLL_AMOUNT_MAX):
        raise ValidationError(f"amount {amount} outside 1-{SCROLL_AMOUNT_MAX}")
    return direction, amount


def validate_js(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"js must be a non-empty string: {value!r}")
    if len(value) > JS_MAX_LEN:
        raise ValidationError(f"js length {len(value)} exceeds {JS_MAX_LEN}")
    return value


def validate_selector(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"selector must be a non-empty string: {value!r}")
    if len(value) > SELECTOR_MAX_LEN:
        raise ValidationError(f"selector length {len(value)} exceeds {SELECTOR_MAX_LEN}")
    return value


def validate_url_hint(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > URL_HINT_MAX_LEN:
        raise ValidationError(f"url_hint must be a string up to {URL_HINT_MAX_LEN} chars: {value!r}")
    return value


def validate_navigate_url(value: object) -> str:
    if not isinstance(value, str) or not re.match(r"^https?://", value):
        raise ValidationError(f"url must start with http:// or https://: {value!r}")
    return value


RENDER_WAIT_MIN, RENDER_WAIT_MAX = 1.0, 30.0


def validate_wait_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"wait_seconds must be a number: {value!r}")
    if not (RENDER_WAIT_MIN <= value <= RENDER_WAIT_MAX):
        raise ValidationError(f"wait_seconds {value} outside {RENDER_WAIT_MIN}-{RENDER_WAIT_MAX}")
    return float(value)


def validate_filename(value: object) -> str:
    """Sanitized-name-only — no path separators, no leading dot, no traversal shape at all."""
    if not isinstance(value, str) or not FILENAME_RE.match(value):
        raise ValidationError(f"filename must match {FILENAME_RE.pattern!r}: {value!r}")
    if value in (".", ".."):
        raise ValidationError(f"filename must not be a directory reference: {value!r}")
    return value


def validate_upload_mode(value: object) -> str:
    if value not in UPLOAD_MODES:
        raise ValidationError(f"mode must be one of {sorted(UPLOAD_MODES)}: {value!r}")
    return value


def validate_upload_size(byte_count: int) -> int:
    if byte_count <= 0 or byte_count > UPLOAD_MAX_BYTES:
        raise ValidationError(f"upload size {byte_count} outside 1-{UPLOAD_MAX_BYTES}")
    return byte_count


def validate_download_size(byte_count: int) -> int:
    if byte_count > DOWNLOAD_MAX_BYTES:
        raise ValidationError(f"download size {byte_count} exceeds {DOWNLOAD_MAX_BYTES}")
    return byte_count
