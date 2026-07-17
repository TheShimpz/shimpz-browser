"""The local, single-scope bearer token for authorized Browser Service consumers.

Generated once on first boot and shared only through a private runtime volume; never stored in
`.env` and never exposed to the provider-neutral Brain.
"""

from __future__ import annotations

import grp
import os
import secrets
from pathlib import Path

TOKEN_PATH = Path(os.environ.get("SHIMPZ_BROWSERAGENT_TOKEN_FILE", "/run/shimpz-browseragent/token"))
TOKEN_GROUP = os.environ.get("SHIMPZ_BROWSERAGENT_TOKEN_GROUP", "shimpzbrowseragent-token")


def _group_readable(path: Path) -> None:
    """Enforce 0440 + TOKEN_GROUP on `path`, every time — idempotent and self-healing."""
    gid = grp.getgrnam(TOKEN_GROUP).gr_gid
    os.chown(path, -1, gid)
    path.chmod(0o440)


def ensure_token() -> str:
    if TOKEN_PATH.exists():
        token = TOKEN_PATH.read_text().strip()
        if token:
            _group_readable(TOKEN_PATH)
            return token
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    TOKEN_PATH.write_text(token)
    _group_readable(TOKEN_PATH)
    return token
