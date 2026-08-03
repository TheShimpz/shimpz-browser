#!/opt/venv/bin/python
"""browser-agent — the isolated Browser Service boundary for XTEST/CDP/X11 access.

The provider-neutral Brain never receives a Browser token or direct access to DISPLAY, CDP,
xdotool, the Chrome profile, or this network. An explicitly authorized caller outside the model
runtime can mediate declared Browser capabilities through this restricted, audited HTTP API.
shimpz-glspoof remains an autonomous background process inside `shimpz-browser`, so it is not part
of this API.

Mandatory controls for the isolated browser boundary:
  - Auth fail-closed on EVERY endpoint: `Authorization: Bearer <token>` required; no token via
    query string; no anonymous "just health" endpoint that would itself prove a capability; an
    internal error NEVER becomes an implicit allow (see `_dispatch`'s exception handling below —
    every branch ends in a 4xx/5xx response, never a fallthrough).
  - No CORS, ever: this API exists for authorized internal Service consumers, never for a page loaded
    in Chrome. No `Access-Control-Allow-Origin` header is ever sent, at any status code.
  - Zero execution endpoints: this service only automates UI (click/type/scroll/navigate/read
    DOM/screenshot/upload+download BYTES). There is no shell/command/open-arbitrary-file endpoint,
    by design — grep this file for "subprocess"/"os.system": every call site is a fixed xdotool/
    ImageMagick argv, never a caller-supplied command.
  - Redacted audit: see audit.py's forbidden-field list — every call site below passes only sizes,
    counts, coordinates, and booleans, never typed text/JS source/upload-download bytes/tokens.

Endpoints (all require `Authorization: Bearer <token>` — see token_store.py):
  POST   /v1/browser/move             {x, y}
  POST   /v1/browser/click            {x, y, button?, count?}
  POST   /v1/browser/dclick           {x, y}
  POST   /v1/browser/key              {combo}
  POST   /v1/browser/type             {text}
  POST   /v1/browser/scroll           {direction, amount?}
  GET    /v1/browser/pos              -> {x, y}
  GET    /v1/browser/screenshot       -> PNG bytes (X-Screen-Geometry header, e.g. "1280x800")
  POST   /v1/browser/navigate         {url, url_hint?}
  POST   /v1/browser/render           {url, wait_seconds?} -> {html} (fresh tab, JS-rendered, closed after)
  POST   /v1/browser/cdp/eval         {js, url_hint?} -> {value}
  GET    /v1/browser/cdp/rect         ?selector=&url_hint= -> {screen_x, screen_y, viewport_x,
                                       viewport_y, width, height}
  GET    /v1/browser/cdp/text         ?selector=&url_hint= -> {text}
  POST   /v1/browser/upload           {mode: dom|native, filename, file_bytes(base64), selector?,
                                       url_hint?, title_regex?}
  GET    /v1/browser/downloads/list   -> {downloads: [{name, size}, ...]}
  GET    /v1/browser/downloads/fetch  ?name=<name> -> file bytes
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import cdp_client
import downloads_client
import screenshot_client
import upload_client
import xtest_client

import audit
import token_store
import validate

LISTEN_PORT = int(os.environ.get("SHIMPZ_BROWSERAGENT_PORT", "7074"))
MAX_HTTP_CONCURRENCY = 32
HTTP_CONNECTION_TIMEOUT_SECONDS = 10
BODY_READ_DEADLINE_SECONDS = 10
BODY_READ_CHUNK_BYTES = 64 * 1024
STANDARD_BODY_MAX_BYTES = 256 * 1024
UPLOAD_BODY_MAX_BYTES = 72 * 1024 * 1024
_POST_BODY_LIMITS = {
    "/v1/browser/cdp/eval": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/click": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/dclick": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/key": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/move": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/navigate": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/render": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/scroll": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/type": STANDARD_BODY_MAX_BYTES,
    "/v1/browser/upload": UPLOAD_BODY_MAX_BYTES,
}

_token = token_store.ensure_token()


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Bound thread creation and expire slow Browser Agent connections."""

    daemon_threads = True
    request_queue_size = 32

    def __init__(
        self,
        *args,
        max_concurrency: int = MAX_HTTP_CONCURRENCY,
        connection_timeout: int = HTTP_CONNECTION_TIMEOUT_SECONDS,
        **kwargs,
    ) -> None:
        self._request_slots = threading.BoundedSemaphore(max_concurrency)
        self._connection_timeout = connection_timeout
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(self._connection_timeout)
        return request, client_address

    def process_request(self, request, client_address) -> None:
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _move(body: dict) -> dict:
    x = validate.validate_coord(body.get("x"), "x")
    y = validate.validate_coord(body.get("y"), "y")
    xtest_client.move(x, y)
    return {"moved": True}


def _click(body: dict) -> dict:
    x = validate.validate_coord(body.get("x"), "x")
    y = validate.validate_coord(body.get("y"), "y")
    button = validate.validate_button(body.get("button", "left"))
    count = validate.validate_count(body.get("count", 1))
    xtest_client.click(x, y, button, count)
    return {"clicked": True}


def _dclick(body: dict) -> dict:
    x = validate.validate_coord(body.get("x"), "x")
    y = validate.validate_coord(body.get("y"), "y")
    xtest_client.dclick(x, y)
    return {"clicked": True}


def _key(body: dict) -> dict:
    combo = validate.validate_key(body.get("combo"))
    xtest_client.key(combo)
    return {"sent": True}


def _type(body: dict) -> dict:
    text = validate.validate_text(body.get("text"))
    xtest_client.type_text(text)
    return {"typed_len": len(text)}


def _scroll(body: dict) -> dict:
    direction, amount = validate.validate_scroll(body.get("direction"), body.get("amount", 3))
    xtest_client.scroll(direction, amount)
    return {"scrolled": True}


def _pos() -> dict:
    x, y = xtest_client.pos()
    return {"x": x, "y": y}


def _navigate(body: dict) -> dict:
    url = validate.validate_navigate_url(body.get("url"))
    url_hint = validate.validate_url_hint(body.get("url_hint"))
    cdp_client.navigate(url, url_hint)
    return {"navigated": True}


def _render(body: dict) -> dict:
    url = validate.validate_navigate_url(body.get("url"))
    wait_seconds = validate.validate_wait_seconds(body.get("wait_seconds", 6.0))
    html = cdp_client.render(url, wait_seconds)
    return {"html": html}


def _cdp_eval(body: dict) -> dict:
    js = validate.validate_js(body.get("js"))
    url_hint = validate.validate_url_hint(body.get("url_hint"))
    value = cdp_client.eval_js(js, url_hint)
    return {"value": value}


def _cdp_rect(selector: str, url_hint: str | None) -> dict:
    result = cdp_client.rect(selector, url_hint)
    if result is None:
        raise ApiError(HTTPStatus.NOT_FOUND, f"selector matched nothing: {selector!r}")
    return result


def _cdp_text(selector: str, url_hint: str | None) -> dict:
    result = cdp_client.text(selector, url_hint)
    if result is None:
        raise ApiError(HTTPStatus.NOT_FOUND, f"selector matched nothing: {selector!r}")
    return {"text": result}


def _upload(body: dict) -> dict:
    mode = validate.validate_upload_mode(body.get("mode", "dom"))
    filename = validate.validate_filename(body.get("filename"))
    raw_b64 = body.get("file_bytes")
    if not isinstance(raw_b64, str) or not raw_b64:
        raise ApiError(HTTPStatus.BAD_REQUEST, "file_bytes must be a non-empty base64 string")
    try:
        file_bytes = base64.b64decode(raw_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ApiError(HTTPStatus.BAD_REQUEST, f"file_bytes is not valid base64: {exc}") from exc
    validate.validate_upload_size(len(file_bytes))

    fd, tmp_path_str = tempfile.mkstemp(prefix="upload-", suffix=f"-{filename}", dir="/tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(file_bytes)
        if mode == "dom":
            selector = validate.validate_selector(body.get("selector"))
            url_hint = validate.validate_url_hint(body.get("url_hint"))
            ok, info = cdp_client.upload_dom(selector, str(tmp_path), url_hint)
            if not ok:
                raise ApiError(HTTPStatus.BAD_GATEWAY, f"DOM upload failed: {info}")
            return {"uploaded": True, "mode": "dom", "detail": info}
        title_regex = body.get("title_regex") or upload_client.DEFAULT_DIALOG_RE
        if not isinstance(title_regex, str) or len(title_regex) > 300:
            raise ApiError(HTTPStatus.BAD_REQUEST, "title_regex must be a string up to 300 chars")
        try:
            detail = upload_client.upload_native(str(tmp_path), title_regex)
        except upload_client.UploadError as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"native upload failed: {exc}") from exc
        return {"uploaded": True, "mode": "native", "detail": detail}
    finally:
        tmp_path.unlink(missing_ok=True)


def _downloads_list() -> dict:
    return {"downloads": downloads_client.list_downloads()}


def _downloads_fetch(name: str) -> bytes:
    name = validate.validate_filename(name)
    try:
        data = downloads_client.fetch(name)
    except downloads_client.DownloadError as exc:
        raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc
    validate.validate_download_size(len(data))
    return data


_AUDITED_ROUTES = frozenset(
    {
        "/v1/browser/cdp/eval",
        "/v1/browser/cdp/rect",
        "/v1/browser/cdp/text",
        "/v1/browser/click",
        "/v1/browser/dclick",
        "/v1/browser/downloads/fetch",
        "/v1/browser/downloads/list",
        "/v1/browser/key",
        "/v1/browser/move",
        "/v1/browser/navigate",
        "/v1/browser/pos",
        "/v1/browser/render",
        "/v1/browser/screenshot",
        "/v1/browser/scroll",
        "/v1/browser/type",
        "/v1/browser/upload",
    }
)


def _audit_route(target: str) -> str:
    """Classify a request target without retaining query values or unknown paths."""
    path = urlsplit(target).path
    return f"route:{path}" if path in _AUDITED_ROUTES else "unknown-route"


class Handler(BaseHTTPRequestHandler):
    server_version = "browser-agent/1.0"

    def _authed(self) -> bool:
        return self.headers.get("Authorization", "") == f"Bearer {_token}"

    def _send_bytes(
        self, status: HTTPStatus, content_type: str, body: bytes, extra_headers: dict | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        # NEVER an Access-Control-Allow-Origin header, at any status — this API is not browser-callable.
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        self._send_bytes(status, "application/json", json.dumps(payload).encode())

    def _body(self, maximum: int) -> dict:
        lengths = self.headers.get_all("Content-Length", [])
        if not lengths:
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
        if len(lengths) != 1 or not lengths[0].isdecimal() or self.headers.get("Transfer-Encoding") is not None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "request framing is invalid")
        length = int(lengths[0])
        if length > maximum:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request body is too large")
        if length == 0:
            return {}
        deadline = time.monotonic() + BODY_READ_DEADLINE_SECONDS
        remaining = length
        raw = bytearray()
        try:
            while remaining:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    raise ApiError(HTTPStatus.REQUEST_TIMEOUT, "request body read timed out")
                self.connection.settimeout(timeout)
                chunk = self.rfile.read(min(remaining, BODY_READ_CHUNK_BYTES))
                if not chunk:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "request body is incomplete")
                raw.extend(chunk)
                remaining -= len(chunk)
        except TimeoutError as exc:
            raise ApiError(HTTPStatus.REQUEST_TIMEOUT, "request body read timed out") from exc
        finally:
            self.connection.settimeout(HTTP_CONNECTION_TIMEOUT_SECONDS)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return payload

    def _dispatch(self, method: str) -> None:
        route = _audit_route(self.path)
        if not self._authed():
            audit.log("auth", route, result="denied", reason_code="api_error", status=HTTPStatus.FORBIDDEN)
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "invalid or missing bearer token"})
            return
        try:
            self._route(method)
        except ApiError as exc:
            audit.log(method.lower(), route, result="denied", reason_code="api_error", status=exc.status)
            self._send_json(exc.status, {"error": exc.message})
        except validate.ValidationError as exc:
            audit.log(
                method.lower(),
                route,
                result="denied",
                reason_code="validation_error",
                status=HTTPStatus.BAD_REQUEST,
            )
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (xtest_client.XTestError, cdp_client.CDPError, screenshot_client.ScreenshotError) as exc:
            audit.log(
                method.lower(),
                route,
                result="error",
                reason_code="upstream_error",
                status=HTTPStatus.BAD_GATEWAY,
            )
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
        except (
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            LookupError,
            cdp_client.websockets.WebSocketException,
        ) as exc:
            audit.log(
                method.lower(),
                route,
                result="error",
                reason_code="internal_error",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _route(self, method: str) -> None:
        split = urlsplit(self.path)
        path = split.path
        if method == "POST":
            self._route_post(path)
            return
        if method == "GET":
            self._route_get(path, parse_qs(split.query))
            return
        raise ApiError(HTTPStatus.NOT_FOUND, f"no route for {method} {path}")

    def _route_input_post(self, path: str, body: dict) -> bool:
        if path not in {
            "/v1/browser/move",
            "/v1/browser/click",
            "/v1/browser/dclick",
            "/v1/browser/key",
            "/v1/browser/type",
            "/v1/browser/scroll",
        }:
            return False
        if path == "/v1/browser/move":
            result = _move(body)
            trace = audit.log("move", f"{body.get('x')},{body.get('y')}", result="ok")
        elif path == "/v1/browser/click":
            result = _click(body)
            trace = audit.log("click", f"{body.get('x')},{body.get('y')}", result="ok")
        elif path == "/v1/browser/dclick":
            result = _dclick(body)
            trace = audit.log("dclick", f"{body.get('x')},{body.get('y')}", result="ok")
        elif path == "/v1/browser/key":
            result = _key(body)
            trace = audit.log("key", body.get("combo", "?"), result="ok")
        elif path == "/v1/browser/type":
            result = _type(body)
            trace = audit.log("type", "input", result="ok", typed_len=result["typed_len"])
        else:
            result = _scroll(body)
            trace = audit.log("scroll", body.get("direction", "?"), result="ok")
        self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
        return True

    def _route_post(self, path: str) -> None:
        maximum = _POST_BODY_LIMITS.get(path)
        if maximum is None:
            raise ApiError(HTTPStatus.NOT_FOUND, f"no route for POST {path}")
        body = self._body(maximum)
        if self._route_input_post(path, body):
            return
        if path == "/v1/browser/navigate":
            result = _navigate(body)
            trace = audit.log("navigate", audit.url_subject(body.get("url", "")), result="ok")
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        if path == "/v1/browser/render":
            result = _render(body)
            trace = audit.log(
                "render",
                audit.url_subject(body.get("url", "")),
                result="ok",
                html_len=len(result["html"]),
            )
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        if path == "/v1/browser/cdp/eval":
            result = _cdp_eval(body)
            trace = audit.log("cdp.eval", "expression", result="ok")
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        if path == "/v1/browser/upload":
            result = _upload(body)
            trace = audit.log(
                "upload",
                audit.opaque_subject("filename", body.get("filename", "")),
                result="ok",
                mode=result["mode"],
            )
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        raise AssertionError(f"POST body limit exists without a route: {path}")

    def _route_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/v1/browser/pos":
            result = _pos()
            self._send_json(HTTPStatus.OK, result)
            return
        if path == "/v1/browser/screenshot":
            png = screenshot_client.capture()
            geo = screenshot_client.geometry()
            headers = {"X-Screen-Geometry": f"{geo[0]}x{geo[1]}"} if geo else {}
            audit.log("screenshot", "root", result="ok", byte_count=len(png))
            self._send_bytes(HTTPStatus.OK, "image/png", png, headers)
            return
        if path == "/v1/browser/cdp/rect":
            selector = validate.validate_selector(query.get("selector", [""])[0])
            url_hint = validate.validate_url_hint((query.get("url_hint") or [None])[0])
            result = _cdp_rect(selector, url_hint)
            trace = audit.log("cdp.rect", audit.opaque_subject("selector", selector), result="ok")
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        if path == "/v1/browser/cdp/text":
            selector = validate.validate_selector(query.get("selector", [""])[0])
            url_hint = validate.validate_url_hint((query.get("url_hint") or [None])[0])
            result = _cdp_text(selector, url_hint)
            trace = audit.log(
                "cdp.text",
                audit.opaque_subject("selector", selector),
                result="ok",
                text_len=len(result["text"]),
            )
            self._send_json(HTTPStatus.OK, {**result, "trace_id": trace})
            return
        if path == "/v1/browser/downloads/list":
            result = _downloads_list()
            audit.log("downloads.list", "catalog", result="ok", count=len(result["downloads"]))
            self._send_json(HTTPStatus.OK, result)
            return
        if path == "/v1/browser/downloads/fetch":
            name = query.get("name", [""])[0]
            data = _downloads_fetch(name)
            audit.log(
                "downloads.fetch",
                audit.opaque_subject("filename", name),
                result="ok",
                byte_count=len(data),
            )
            self._send_bytes(HTTPStatus.OK, "application/octet-stream", data)
            return
        raise ApiError(HTTPStatus.NOT_FOUND, f"no route for GET {path}")

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, fmt: str, *args: object) -> None:
        # Suppress BaseHTTPRequestHandler's default stderr access log — audit.log() is the
        # single source of truth for what happened, in the schema logq expects.
        pass


def main() -> None:
    # An empty host is the HTTPServer spelling for IPv4 INADDR_ANY. The service must be reachable
    # by an explicitly authorized consumer on the private Service network, not just in this container.
    server = BoundedThreadingHTTPServer(("", LISTEN_PORT), Handler)
    print(f"browser-agent listening on :{LISTEN_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
