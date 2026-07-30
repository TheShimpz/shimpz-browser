"""The ONLY place CDP (127.0.0.1:9222, loopback-only) is spoken from.

CDP never leaves this container. External callers interact only with browser-agent's validated,
token-gated Service API; the provider-neutral Brain has no direct Browser access.
"""

from __future__ import annotations

import asyncio
import json

import requests
import websockets

CDP = "http://127.0.0.1:9222"


class CDPError(Exception):
    """A CDP call failed, or no page target was reachable."""


def targets() -> list[dict]:
    """All 'page' targets that expose a websocket debugger URL."""
    r = requests.get(f"{CDP}/json", timeout=5).json()
    return [t for t in r if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def pick(url_hint: str | None = None) -> dict:
    """The page target to talk to: the first whose url contains url_hint, else the first page.

    FAIL-FAST: no page target at all is an error, not a silent no-op.
    """
    ts = targets()
    if not ts:
        raise CDPError(f"no page target on CDP {CDP} — is Chrome running?")
    if url_hint:
        ts = [t for t in ts if url_hint in t.get("url", "")] or ts
    return ts[0]


async def _cmd(ws, _id: int, method: str, params: dict | None = None, response_timeout: float = 15) -> dict:
    """Send one CDP command over `ws` and await ITS response (matched by id).

    FAIL-LOUD: a CDP protocol error raises, never returns a silent {}.
    """
    await ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=response_timeout))
        if msg.get("id") == _id:
            if "error" in msg:
                raise CDPError(msg["error"].get("message", str(msg["error"])))
            return msg.get("result", {})


async def _evaluate(ws, expression: str) -> dict:
    res = await _cmd(
        ws,
        1,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True},
    )
    exc = res.get("exceptionDetails")
    if exc:
        msg = (exc.get("exception", {}) or {}).get("description") or exc.get("text") or "evaluation failed"
        raise CDPError(msg)
    return res.get("result", {})


async def _eval_async(js: str, url_hint: str | None) -> object:
    t = pick(url_hint)
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
        r = await _evaluate(ws, js)
        return r.get("value")


def eval_js(js: str, url_hint: str | None = None) -> object:
    return asyncio.run(_eval_async(js, url_hint))


# JS that returns an element's RAW geometry (after scrolling it into view). Deliberately does NO
# arithmetic — the load-bearing viewport→desktop mapping is done in Python (`_screen_xy`), where
# it's unit-tested. Returns null if the selector matches nothing (fail-loud, never a fabricated
# coordinate).
_GEOM_JS = """(() => {
  const el = document.querySelector(%s);
  if (!el) return null;
  el.scrollIntoView({block: "center", inline: "center"});
  const r = el.getBoundingClientRect();
  return {
    left: r.left, top: r.top, width: r.width, height: r.height,
    screenX: window.screenX, screenY: window.screenY,
    chromeH: Math.max(0, window.outerHeight - window.innerHeight),
    dpr: window.devicePixelRatio || 1
  };
})()"""


def _screen_xy(g: dict) -> tuple[int, int]:
    """Map an element's viewport rect (CSS px) to the DESKTOP pixel xtest_client clicks.

    screenX/Y is the browser window's origin on the screen; chromeH is the toolbars (tabs+omnibox)
    above the viewport; devicePixelRatio scales CSS px to the device-pixel framebuffer
    screenshot_client/xtest_client use. Verified live against the real Chrome.
    """
    dpr = g.get("dpr") or 1
    cx = g["screenX"] + g["left"] + g["width"] / 2
    cy = g["screenY"] + g["chromeH"] + g["top"] + g["height"] / 2
    return round(cx * dpr), round(cy * dpr)


def _viewport_xy(g: dict) -> tuple[int, int]:
    return round(g["left"] + g["width"] / 2), round(g["top"] + g["height"] / 2)


def rect(selector: str, url_hint: str | None = None) -> dict | None:
    """Screen + viewport coordinates for `selector`'s center, or None if nothing matches."""
    g = eval_js(_GEOM_JS % json.dumps(selector), url_hint)
    if not g:
        return None
    sx, sy = _screen_xy(g)
    vx, vy = _viewport_xy(g)
    return {
        "screen_x": sx,
        "screen_y": sy,
        "viewport_x": vx,
        "viewport_y": vy,
        "width": round(g["width"]),
        "height": round(g["height"]),
    }


def text(selector: str, url_hint: str | None = None) -> str | None:
    """InnerText of the element matching `selector`, or None if nothing matches.

    ONE round-trip (presence + read together) — no element-vanished race: a missing element is
    reported as missing, never as a successful empty read.
    """
    js = (
        f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
        " return el ? {t: el.innerText} : null; })()"
    )
    v = eval_js(js, url_hint)
    if v is None:
        return None
    return (v.get("t") or "").strip()


def navigate(url: str, url_hint: str | None = None) -> None:
    async def _go() -> None:
        t = pick(url_hint)
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            await _cmd(ws, 1, "Page.enable")
            await _cmd(ws, 2, "Page.navigate", {"url": url})

    asyncio.run(_go())


async def _render_async(url: str, wait_seconds: float) -> str:
    """Open a FRESH tab for `url`, wait for JS to render, read the full outerHTML, close the tab.

    Ported from rootfs/usr/local/bin/webread's `_via_cdp` — its JS-render fallback for SPA pages
    trafilatura's static fetch can't parse. The tab is ALWAYS closed, even on a render failure —
    webread targets flaky/SPA pages, so a failed render must never orphan a live Chrome tab
    (memory growth on the always-on browser). requests calls run in a thread (asyncio.to_thread) —
    a sync HTTP call would otherwise block this coroutine's event loop.
    """
    import contextlib
    import urllib.parse

    target = urllib.parse.quote(url, safe="")
    r = (await asyncio.to_thread(requests.put, f"{CDP}/json/new?{target}", timeout=10)).json()
    tab_id, ws_url = r["id"], r["webSocketDebuggerUrl"]
    try:
        await asyncio.sleep(wait_seconds)
        async with websockets.connect(ws_url, max_size=None) as ws:
            expr = {"expression": "document.documentElement.outerHTML", "returnByValue": True}
            res = await _cmd(ws, 1, "Runtime.evaluate", expr)
            return (res.get("result", {}) or {}).get("value", "") or ""
    finally:
        with contextlib.suppress(OSError, requests.RequestException):
            await asyncio.to_thread(requests.get, f"{CDP}/json/close/{tab_id}", timeout=5)


def render(url: str, wait_seconds: float = 6.0) -> str:
    return asyncio.run(_render_async(url, wait_seconds))


async def _upload_dom_async(selector: str, path: str, url_hint: str | None) -> tuple[bool, str]:
    ts = targets()
    if url_hint:
        ts = [t for t in ts if url_hint in t.get("url", "")] or ts
    last = "no tab"
    for t in ts:
        try:
            async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
                await _cmd(ws, 1, "Runtime.enable")
                await _cmd(ws, 2, "DOM.enable")
                ev = await _cmd(
                    ws, 3, "Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"}
                )
                obj = ev.get("result", {})
                oid = obj.get("objectId")
                if not oid or obj.get("subtype") == "null":
                    last = "selector not found on this page"
                    continue
                await _cmd(ws, 4, "DOM.setFileInputFiles", {"files": [path], "objectId": oid})
                # Actually GATE on the verify count — don't compute it and unconditionally return
                # success. On a React-heavy page the input node can be replaced between get-objectId
                # and setFileInputFiles, so the file lands on a detached node → the live input has 0
                # files. Reporting success with 0 files is the false-success this check catches.
                chk = await _cmd(
                    ws,
                    5,
                    "Runtime.evaluate",
                    {"expression": f"document.querySelector({json.dumps(selector)}).files.length"},
                )
                n = chk.get("result", {}).get("value")
                if not n:
                    last = f"attach did not take — input has {n} file(s) after setFileInputFiles"
                    continue
                return True, f"{n} file(s) in the input on {t.get('url', '?')[:70]}"
        except (OSError, CDPError, KeyError, json.JSONDecodeError, websockets.WebSocketException) as exc:
            last = str(exc)
    return False, last


def upload_dom(selector: str, path: str, url_hint: str | None = None) -> tuple[bool, str]:
    return asyncio.run(_upload_dom_async(selector, path, url_hint))
