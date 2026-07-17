"""The ONLY place XTEST (xdotool against DISPLAY=:1) is driven from.

The X11 display is a Unix domain socket (svc-kasmvnc's Xvnc has no `-listen tcp`) unreachable from
other containers. browser-agent owns the WindMouse-based human motion implementation and exposes
only its validated HTTP operations; the provider-neutral Brain has no direct Browser access.
"""

from __future__ import annotations

import math
import os
import random
import time

import native_process

os.environ.setdefault("DISPLAY", ":1")


class XTestError(Exception):
    """An xdotool invocation failed — X down, bad DISPLAY, or an invalid keysym."""


def _xdo(*a: str) -> None:
    # FAIL-FAST: a non-zero xdotool exit previously meant "reported success but did nothing" — the
    # exact failure mode this real-input tool exists to eliminate. Surface xdotool's own stderr.
    result = native_process.run_xdotool(*a)
    if result.returncode != 0:
        raise XTestError(f"xdotool {' '.join(a)} failed (rc={result.returncode}): {(result.stderr or '').strip()}")


def pos() -> tuple[int, int]:
    result = native_process.run_xdotool("getmouselocation", "--shell")
    if result.returncode != 0:
        raise XTestError(f"xdotool getmouselocation failed (rc={result.returncode}): {(result.stderr or '').strip()}")
    parsed = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            parsed[k] = v.strip()
    if "X" not in parsed or "Y" not in parsed:
        raise XTestError(f"xdotool getmouselocation gave no X/Y: {result.stdout!r}")
    return int(parsed["X"]), int(parsed["Y"])


def _windmouse(
    sx: float,
    sy: float,
    dx: float,
    dy: float,
    gravity: float = 9.0,
    wind_mag: float = 3.0,
    max_step: float = 12.0,
    damp_dist: float = 12.0,
) -> list[tuple[int, int]]:
    """Yield (x,y) points from (sx,sy) to (dx,dy) — Ben Land's WindMouse.

    Parameter names map to the paper's G_0/W_0/M_0/D_0: gravitational pull toward the target, wind
    force magnitude, max step size, and the distance where wind damps out.
    """
    cx, cy = float(sx), float(sy)
    vx = vy = wx = wy = 0.0
    s3, s5 = math.sqrt(3), math.sqrt(5)
    pts = []
    while math.hypot(dx - cx, dy - cy) >= 1:
        dist = math.hypot(dx - cx, dy - cy)
        wind = min(wind_mag, dist)
        if dist >= damp_dist:
            wx = wx / s3 + (2 * random.random() - 1) * wind / s5
            wy = wy / s3 + (2 * random.random() - 1) * wind / s5
        else:
            wx /= s3
            wy /= s3
            if max_step < 3:
                max_step = random.random() * 3 + 3
            else:
                max_step /= s5
        vx += wx + gravity * (dx - cx) / dist
        vy += wy + gravity * (dy - cy) / dist
        vmag = math.hypot(vx, vy)
        if vmag > max_step:
            vclip = max_step / 2 + random.random() * max_step / 2
            vx = vx / vmag * vclip
            vy = vy / vmag * vclip
        cx += vx
        cy += vy
        pts.append((round(cx), round(cy)))
    pts.append((int(dx), int(dy)))
    return pts


def move(dx: int, dy: int, jitter: int = 2) -> tuple[int, int]:
    # land on a random point near the target, not its exact center
    dx += random.randint(-jitter, jitter)
    dy += random.randint(-jitter, jitter)
    sx, sy = pos()
    path = _windmouse(sx, sy, dx, dy)
    for x, y in path:
        _xdo("mousemove", str(x), str(y))
        time.sleep(random.uniform(0.004, 0.016))
    return dx, dy


def click(dx: int, dy: int, button: str = "left", count: int = 1) -> None:
    b = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
    move(dx, dy)
    time.sleep(random.uniform(0.05, 0.18))  # human pre-click dwell
    _xdo("click", "--repeat", str(count), b)


def dclick(dx: int, dy: int) -> None:
    move(dx, dy)
    time.sleep(random.uniform(0.05, 0.15))
    _xdo("click", "--repeat", "2", "--delay", str(random.randint(80, 140)), "1")


def type_text(text: str) -> None:
    for ch in text:
        _xdo("type", "--clearmodifiers", "--", ch)
        time.sleep(random.uniform(0.045, 0.16))
        if random.random() < 0.04:  # occasional human pause
            time.sleep(random.uniform(0.25, 0.6))


def key(combo: str) -> None:
    _xdo("key", "--clearmodifiers", combo)


def scroll(direction: str, amount: int = 3) -> None:
    btn = "4" if direction == "up" else "5"
    for _ in range(int(amount)):
        _xdo("click", btn)
        time.sleep(random.uniform(0.08, 0.22))
