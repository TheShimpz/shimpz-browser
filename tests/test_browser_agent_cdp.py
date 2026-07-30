#!/usr/bin/env python3
"""Battle-test for control/cdp_client.py — the only place CDP is spoken from now.

This is the server-side successor to what tests/test-shimpz-cdp.py used to cover directly: the
viewport→desktop pixel math (_screen_xy/_viewport_xy), the injection-safety of the geometry JS
template (_GEOM_JS), and the CDP wire-protocol handling (_cmd/_evaluate/eval_js/rect/text/navigate)
all moved server-side into this module — `shimpz-brain` (the brain) never sees CDP again, only browser-agent's
HTTP surface (see test-shimpz-cdp.py for THAT thin-client side). No live Chrome here: `requests` +
`websockets` are stubbed in sys.modules BEFORE import (same pattern the old test-shimpz-cdp.py used for
shimpzcdp.py), then the REAL _cmd()/_evaluate()/rect()/text()/navigate()/render() run over a
protocol-speaking fake websocket — nothing stubbed above the wire, so the error/fail-fast branches
actually execute through the Browser repository's unittest discovery.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "control"))
import cdp_client as cdp


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def raises(error: type[BaseException], callback) -> bool:
    try:
        callback()
    except error:
        return True
    return False


# The LOAD-BEARING map, with the dpr factor EXERCISED (dpr=2, not the live dpr=1 no-op) — a dropped
# *dpr or double-counted chrome height fails here, not in production against a credentialed page.
_G = {
    "left": 100,
    "top": 200,
    "width": 40,
    "height": 20,
    "screenX": 50,
    "screenY": 10,
    "chromeH": 80,
    "dpr": 2,
}


def test_screen_and_viewport_xy():
    # sx = round((screenX + left + width/2)*dpr) = round((50+100+20)*2) = 340
    # sy = round((screenY + chromeH + top + height/2)*dpr) = round((10+80+200+10)*2) = 600
    check(
        cdp._screen_xy(_G) == (340, 600), "screen map @dpr2 = (340, 600) — a dropped *dpr or double chrome FAILS here"
    )
    check(cdp._viewport_xy(_G) == (120, 210), "viewport centre = (120, 210)")
    check(cdp._screen_xy({**_G, "dpr": 1}) == (170, 300), "@dpr1 = (170, 300) (regression: the live check ran here)")
    check(cdp._screen_xy({**_G, "dpr": None}) == (170, 300), "missing/None dpr defaults to 1 (no crash, no *None)")
    check(
        cdp._screen_xy(_G) != cdp._viewport_xy(_G),
        "screen != viewport → the mapping is actually applied, not a passthrough",
    )


def test_geom_js_selector_injection_safety():
    sel = 'button[aria-label="Edit"]'
    js = cdp._GEOM_JS % json.dumps(sel)
    check("document.querySelector(" in js and "getBoundingClientRect" in js, "geom JS reads querySelector+rect")
    check(json.dumps(sel) in js, "the selector is JSON-escaped, not concatenated raw")
    check("screenX" in js and "devicePixelRatio" in js and "chromeH" in js, "geom JS returns raw screenX/dpr/chrome")
    check("Math.round" not in js and "* dpr" not in js, "geom JS does NO arithmetic — the mapping is in Python")
    hostile = 'a");alert(1)//'
    check(
        json.dumps(hostile) in (cdp._GEOM_JS % json.dumps(hostile)),
        "an injection-y selector stays a JSON string, never breaks out of it",
    )


# ══ drive the REAL _cmd()/_evaluate()/eval_js()/rect()/text()/navigate() over a protocol-speaking fake ws ══
class _WS:
    """A fake CDP websocket keyed by the request id.

    send() records the frame and request id; recv() returns the queued response for that id.
    The real _cmd()/_evaluate() run unchanged, so their error/fail-fast branches are exercised.
    """

    def __init__(self, by_id):
        self._by_id = by_id
        self.sent = []
        self._last = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, payload):
        msg = json.loads(payload)
        self.sent.append(msg)
        self._last = msg["id"]

    async def recv(self):
        r = dict(self._by_id.get(self._last, {"result": {}}))
        r["id"] = self._last
        return json.dumps(r)


def _wire(by_id):
    """Point pick()/websockets.connect() at a fresh fake ws pre-loaded with `by_id` responses; return it."""
    ws = _WS(by_id)
    cdp.pick = lambda hint=None: {"webSocketDebuggerUrl": "ws://fake"}
    cdp.websockets.connect = lambda *a, **k: ws
    return ws


def test_eval_happy_path():
    _wire({1: {"result": {"result": {"value": "Shimpz — LinkedIn"}}}})
    check(
        cdp.eval_js("document.title") == "Shimpz — LinkedIn",
        "eval_js returns the value (real _cmd/_evaluate over the wire)",
    )


def test_rect_happy_and_not_found():
    _wire({1: {"result": {"result": {"value": _G}}}})
    r = cdp.rect("button.edit")
    check(
        r == {"screen_x": 340, "screen_y": 600, "viewport_x": 120, "viewport_y": 210, "width": 40, "height": 20},
        f"rect end-to-end returns the real screen+viewport map (got {r!r})",
    )

    _wire({1: {"result": {"result": {"value": None}}}})
    check(
        cdp.rect("button.missing") is None,
        "rect on a missing selector returns None — fail-loud, never a fabricated coordinate",
    )


def test_text_happy_and_not_found():
    _wire({1: {"result": {"result": {"value": {"t": "Saved ✓"}}}}})
    check(cdp.text("div.banner") == "Saved ✓", "text returns the element's innerText")

    _wire({1: {"result": {"result": {"value": None}}}})
    check(
        cdp.text("div.gone") is None,
        "text on a missing element returns None — race-free (never a silent empty read)",
    )


def test_page_js_exception_raises_cdperror():
    _wire({1: {"result": {"exceptionDetails": {"exception": {"description": "ReferenceError: foo is not defined"}}}}})
    raised = False
    try:
        cdp.eval_js("foo.bar")
    except cdp.CDPError as exc:
        raised = True
        check("ReferenceError" in str(exc), "the CDPError message carries the page's exception description")
    check(raised, "a page-side JS exception raises CDPError (never a swallowed None)")


def test_cdp_protocol_error_raises_cdperror():
    _wire({1: {"error": {"message": "Target closed"}}})
    check(
        raises(cdp.CDPError, lambda: cdp.eval_js("document.title")),
        "a CDP protocol error (the 'error' branch of _cmd) raises CDPError",
    )


def test_navigate_sends_enable_then_navigate_in_order():
    ws = _wire({1: {"result": {}}, 2: {"result": {}}})
    cdp.navigate("https://example.com/x", "example.com")
    methods = [m["method"] for m in ws.sent]
    check(methods == ["Page.enable", "Page.navigate"], "navigate enables the Page domain THEN navigates, in order")
    nav = next(m for m in ws.sent if m["method"] == "Page.navigate")
    check(nav["params"] == {"url": "https://example.com/x"}, "the navigate command carries the exact url")


# ══ render(): opens a FRESH tab (fake requests.put), reads outerHTML over the fake ws, ALWAYS closes ══
# the tab (fake requests.get) — even when the render itself raises. This is the specific bug class the
# real code's try/finally exists to prevent: a failed render must never orphan a live Chrome tab.
class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_render_happy_path_opens_and_closes_the_tab():
    put_calls, get_calls = [], []

    def _put(url, timeout=None):
        put_calls.append(url)
        return _Resp({"id": "tab-1", "webSocketDebuggerUrl": "ws://tab-1"})

    def _get(url, timeout=None):
        get_calls.append(url)
        return _Resp({})

    cdp.requests.put = _put
    cdp.requests.get = _get
    _wire({1: {"result": {"result": {"value": "<html>hi</html>"}}}})
    html = cdp.render("https://example.com/spa", wait_seconds=0)
    check(html == "<html>hi</html>", "render returns the outerHTML read from the fresh tab")
    check(bool(put_calls) and "json/new" in put_calls[0], "render opens a FRESH tab via PUT /json/new")
    check(any("json/close/tab-1" in u for u in get_calls), "render closes the SAME tab it opened, on the happy path")


def test_render_closes_the_tab_even_when_render_raises():
    get_calls = []

    def _put(url, timeout=None):
        return _Resp({"id": "tab-2", "webSocketDebuggerUrl": "ws://tab-2"})

    def _get(url, timeout=None):
        get_calls.append(url)
        return _Resp({})

    cdp.requests.put = _put
    cdp.requests.get = _get
    _wire({1: {"error": {"message": "Target closed mid-render"}}})  # a protocol error inside the async with
    raised = False
    try:
        cdp.render("https://example.com/flaky", wait_seconds=0)
    except cdp.CDPError:
        raised = True
    check(raised, "a CDP error DURING render propagates (not swallowed as empty html)")
    check(
        any("json/close/tab-2" in u for u in get_calls),
        "the tab is STILL closed even though render raised — proves the try/finally, not just the happy path",
    )


def load_tests(_loader, _tests, _pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite


if __name__ == "__main__":
    unittest.main()
