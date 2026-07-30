"""shimpzcdp — the SHARED CDP plumbing for the always-on Chrome (CDP at 127.0.0.1:9222).

The target listing/picking and the send/await-by-id command loop were hand-rolled near-identically
in chrome-upload, shimpz-cdp, webread and shimpz-glspoof; they live HERE now. Reuse this — never hand-roll
another CDP websocket client.

Import from the callers with `sys.path.insert(0, os.environ.get("SHIMPZ_LIB", "/opt/shimpz-lib"))` so the
in-container default is `/opt/shimpz-lib` and the host-side unit tests point SHIMPZ_LIB at rootfs/opt/shimpz-lib.
"""

import asyncio
import json

import requests

CDP = "http://127.0.0.1:9222"


def targets():
    """All 'page' targets that expose a websocket debugger URL."""
    r = requests.get(f"{CDP}/json", timeout=5).json()
    return [t for t in r if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def pick(url_hint=None):
    """The page target to talk to: the first whose url contains url_hint, else the first page.

    FAIL-FAST: no page target at all is an error, not a silent no-op.
    """
    ts = targets()
    if not ts:
        raise RuntimeError(f"no page target on CDP {CDP} — is Chrome running?")
    if url_hint:
        ts = [t for t in ts if url_hint in t.get("url", "")] or ts
    return ts[0]


def browser_ws():
    """The BROWSER-level websocket URL (Target.* auto-attach lives here, not on a page target)."""
    return requests.get(f"{CDP}/json/version", timeout=5).json()["webSocketDebuggerUrl"]


async def cmd(ws, _id, method, params=None, response_timeout=15):
    """Send one CDP command over `ws` and await ITS response (matched by id).

    FAIL-LOUD: a CDP protocol error raises, never returns a silent {}.
    """
    await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=response_timeout))
        if msg.get("id") == _id:
            if "error" in msg:
                raise RuntimeError(msg["error"].get("message", str(msg["error"])))
            return msg.get("result", {})
