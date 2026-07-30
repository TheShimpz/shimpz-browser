"""Structured, REDACTED audit log for every browser-agent operation.

Matches the repo-wide structlog JSON schema `logq` expects (ts/level/service/trace_id/msg/…extra).
Mandatory redaction: NEVER log typed text, key combos beyond
the combo name itself, upload/download file bytes, bearer tokens, cookies, or a raw `cdp/eval` JS
payload — only endpoint, status, sizes/counts, and a summarized error. `log()` has no way to accept
a "text"/"js"/"bytes" field, so a call site cannot regress this by accident.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

AUDIT_PATH = Path(os.environ.get("SHIMPZ_BROWSERAGENT_AUDIT_LOG", "/var/log/browser-agent/audit.jsonl"))
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 3

# Fields NEVER allowed in an audit event — a call site that tries to log one of these is a bug in
# app.py, not a legitimate use case; enforced here so it fails loudly in testing, not silently in prod.
_FORBIDDEN_FIELDS = frozenset(
    {"text", "js", "expression", "file_bytes", "bytes", "token", "cookie", "cookies", "password"}
)


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

    `subject` is whatever this op is about (a coordinate pair, a selector, a filename, …) — must
    never itself be raw user/page content long enough to leak typed secrets; callers pass short,
    already-summarized subjects. Returns the trace_id (generated if not given) for the caller to
    echo back in its HTTP response.
    """
    forbidden = _FORBIDDEN_FIELDS & extra.keys()
    if forbidden:
        raise ValueError(
            f"audit.log() refuses forbidden field(s) {sorted(forbidden)} — pass sizes/counts, never raw content"
        )
    trace_id = trace_id or uuid.uuid4().hex
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
    print(line, file=sys.stdout, flush=True)
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _rotate()
    with AUDIT_PATH.open("a") as fh:
        fh.write(line + "\n")
    return trace_id
