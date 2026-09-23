"""Generic wlroots backend — wlr-foreign-toplevel via lswt + wlrctl.

Lowest common denominator for labwc/river/dwl/phoc and COSMIC fallback.
Capabilities: list (title/app_id/state), focus, minimize, maximize,
fullscreen, close. NO geometry, NO pid — fields report null honestly.
Handle = lswt id or app_id/title matchspec.
"""
from __future__ import annotations

import re

from errors import CuError, UnsupportedCompositor
from util import run, run_out, which

_BACKEND = "foreign"


def available() -> bool:
    return which("wlrctl") is not None or which("lswt") is not None


def list_windows() -> list[dict]:
    wins = []
    if which("lswt"):
        out = run_out(["lswt"], timeout=6)
        cur = {}
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("toplevel"):
                if cur:
                    wins.append(cur)
                cur = {}
            m = re.match(r"(title|app-id|state|id):\s*(.*)", line)
            if m:
                cur[m.group(1)] = m.group(2)
        if cur:
            wins.append(cur)
        return [{
            "handle": w.get("id") or w.get("app-id") or w.get("title", ""),
            "title": w.get("title", ""),
            "app_id": w.get("app-id", ""),
            "pid": 0,
            "geometry": None,          # protocol exposes none — honest null
            "focused": "A" in (w.get("state") or ""),
            "state_raw": w.get("state", ""),
            "backend": _BACKEND,
        } for w in wins if w]
    # wlrctl fallback
    out = run_out(["wlrctl", "window", "list"], timeout=6)
    for line in out.splitlines():
        m = re.match(r"([^:]+):\s*(.*)", line)
        if m:
            wins.append({
                "handle": m.group(1).strip(), "app_id": m.group(1).strip(),
                "title": m.group(2).strip(), "pid": 0, "geometry": None,
                "focused": False, "backend": _BACKEND})
    return wins


def _spec(handle) -> str:
    h = str(handle)
    if ":" in h:   # already a matchspec like app_id:firefox
        return h
    return f"app_id:{h}"


def focus(handle) -> None:
    if which("wlrctl"):
        run(["wlrctl", "window", "focus", _spec(handle)], timeout=6)
        return
    raise UnsupportedCompositor("wlrctl missing", compositor="wlroots")


def close(handle) -> None:
    if which("wlrctl"):
        run(["wlrctl", "window", "close", _spec(handle)], timeout=6)
        return
    raise UnsupportedCompositor("wlrctl missing", compositor="wlroots")


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    raise UnsupportedCompositor(
        "wlr-foreign-toplevel exposes no window geometry", compositor="wlroots",
        hint="compositor does not implement ext-foreign-toplevel geometry; "
             "use a compositor-specific backend")


def set_state(handle, state: str, on: bool = True) -> None:
    if not which("wlrctl"):
        raise UnsupportedCompositor("wlrctl missing", compositor="wlroots")
    spec = _spec(handle)
    m = {"minimize": "minimize", "maximize": "maximize",
         "fullscreen": "fullscreen"}.get(state)
    if m is None:
        raise CuError(f"foreign-toplevel does not support state '{state}'")
    args = ["wlrctl", "window", m, spec]
    if not on:
        args.append("state:-fullscreen" if state == "fullscreen" else f"state:-{m}")
    run(args, timeout=6)


def desktops() -> list[dict]:
    return []


def cursor_pos() -> dict | None:
    return None
