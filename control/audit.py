"""Structured, REDACTED audit log for every browser-agent operation.

Matches the repo-wide structlog JSON schema `logq` expects (ts/level/service/trace_id/msg/…extra).
Mandatory redaction: NEVER log typed text, key combos beyond the combo name itself, raw URLs,
selectors, filenames, upload/download file bytes, bearer tokens, cookies, exception messages, or a
raw `cdp/eval` JS payload — only closed subjects, status, sizes/counts, and classified errors.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

AUDIT_PATH = Path(os.environ.get("SHIMPZ_BROWSERAGENT_AUDIT_LOG", "/var/log/browser-agent/audit.jsonl"))
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 3

# Fields NEVER allowed in an audit event — a call site that tries to log one of these is a bug in
# app.py, not a legitimate use case; enforced here so it fails loudly in testing, not silently in prod.
_ALLOWED_EXTRA_FIELDS = frozenset(
    {"byte_count", "count", "html_len", "mode", "reason_code", "status", "text_len", "typed_len"}
)
_COUNT_FIELDS = frozenset({"byte_count", "count", "html_len", "status", "text_len", "typed_len"})
_REASON_CODES = frozenset({"api_error", "internal_error", "upstream_error", "validation_error"})
_SAFE_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,:/+_-]{0,159}\Z")
_SAFE_OP = re.compile(r"[a-z][a-z0-9.]{0,31}\Z")
_TRACE_ID = re.compile(r"[0-9a-f]{32}\Z")
_RESULTS = frozenset({"denied", "error", "ok"})
_WRITE_LOCK = threading.Lock()


def opaque_subject(kind: str, value: object) -> str:
    """Summarize one caller-controlled value without retaining its content."""
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{len(text)}:{digest}"


def url_subject(value: object) -> str:
    """Return a URL origin with credentials, path, query, and fragment removed."""
    text = str(value)
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
    except UnicodeError, ValueError:
        return opaque_subject("url", text)
    subject = f"{parsed.scheme.lower()}://{host}"
    if parsed.scheme.lower() not in {"http", "https"} or _SAFE_SUBJECT.fullmatch(subject) is None:
        return opaque_subject("url", text)
    return subject


def _validate_event(op: str, subject: str, result: str, extra: dict[str, object]) -> None:
    if _SAFE_OP.fullmatch(op) is None or _SAFE_SUBJECT.fullmatch(subject) is None or result not in _RESULTS:
        raise ValueError("audit event contains an unbounded or unsafe primary field")
    unknown = extra.keys() - _ALLOWED_EXTRA_FIELDS
    if unknown:
        raise ValueError(f"audit.log() refuses unknown field(s) {sorted(unknown)}")
    for field in _COUNT_FIELDS & extra.keys():
        value = extra[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"audit field {field} must be a non-negative integer")
    if "reason_code" in extra and extra["reason_code"] not in _REASON_CODES:
        raise ValueError("audit reason_code is not classified")
    if "mode" in extra and extra["mode"] not in {"dom", "native"}:
        raise ValueError("audit mode is invalid")


def _rotate() -> None:
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size <= MAX_BYTES:
        return
    for i in range(BACKUPS - 1, 0, -1):
        src = AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.{i}")
        dst = AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.{i + 1}")
        if src.exists():
            src.replace(dst)
    AUDIT_PATH.replace(AUDIT_PATH.with_name(f"{AUDIT_PATH.name}.1"))


def log(op: str, subject: str, *, result: str, trace_id: str | None = None, **extra: object) -> str:
    """Emit one audit line.

    `subject` must already be a short closed value or the result of `opaque_subject()` /
    `url_subject()`. Returns the trace_id (generated if not given) for the caller to echo back.
    """
    _validate_event(op, subject, result, extra)
    trace_id = trace_id or uuid.uuid4().hex
    if _TRACE_ID.fullmatch(trace_id) is None:
        raise ValueError("audit trace_id is invalid")
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "info" if result == "ok" else "warn",
        "service": "browser-agent",
        "trace_id": trace_id,
        "msg": f"{op} {subject}: {result}",
        "op": op,
        "subject": subject,
        "result": result,
        **extra,
    }
    line = json.dumps(event, sort_keys=True)
    with _WRITE_LOCK:
        print(line, file=sys.stdout, flush=True)
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate()
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    return trace_id
