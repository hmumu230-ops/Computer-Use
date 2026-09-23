"""sway / i3 IPC backend — swaymsg JSON.

Handle = con_id (int). Tiling WM: move/resize only meaningful for floating
windows; minimize→scratchpad, maximize→fullscreen approximations.
"""
from __future__ import annotations

import json

from errors import CuError
from util import run, run_out, which

_BACKEND = "sway"


def available() -> bool:
    return which("swaymsg") is not None


def _msg(*args) -> str:
    return run_out(["swaymsg", *[str(a) for a in args]], timeout=6)


def _leaves() -> list[dict]:
    try:
        tree = json.loads(_msg("-t", "get_tree"))
    except Exception:
        return []
    out = []

    def visit(n):
        if n.get("type") in ("con", "floating_con") and (
                n.get("app_id") or n.get("window_properties") or n.get("name")):
            out.append(n)
        for c in n.get("nodes", []) + n.get("floating_nodes", []):
            visit(c)

    visit(tree)
    return out


def list_windows() -> list[dict]:
    wins = []
    for n in _leaves():
        wp = n.get("window_properties") or {}
        r = n.get("rect") or {}
        wins.append({
            "handle": n["id"],
            "title": n.get("name") or wp.get("title", ""),
            "pid": n.get("pid", 0),
            "app_id": n.get("app_id") or wp.get("class", ""),
            "geometry": {"x": r.get("x", 0), "y": r.get("y", 0),
                         "w": r.get("width", 0), "h": r.get("height", 0)},
            "focused": bool(n.get("focused")),
            "floating": n.get("type") == "floating_con",
            "workspace": _ws_of(n),
            "backend": _BACKEND,
        })
    return wins


def _ws_of(node) -> int:
    # walk is not parent-linked; callers needing workspace can re-query
    return node.get("workspace", -1) if isinstance(node.get("workspace"), int) else -1


def _crit(handle) -> str:
    return f"[con_id={int(handle)}]"


def focus(handle) -> None:
    run(["swaymsg", _crit(handle), "focus"], timeout=6)


def close(handle) -> None:
    run(["swaymsg", _crit(handle), "kill"], timeout=6)


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    c = _crit(handle)
    if x is not None and y is not None:
        run(["swaymsg", c, "move", "absolute", "position",
             str(int(x)), str(int(y))], timeout=6)
    if w is not None and h is not None:
        run(["swaymsg", c, "resize", "set",
             str(int(w)), str(int(h))], timeout=6)


def set_state(handle, state: str, on: bool = True) -> None:
    c = _crit(handle)
    if state == "minimize":
        if on:
            run(["swaymsg", c, "move", "scratchpad"], timeout=6)
        else:
            run(["swaymsg", c, "scratchpad", "show"], timeout=6)
    elif state == "maximize":
        run(["swaymsg", c, "fullscreen", "enable" if on else "disable"],
            timeout=6)
    elif state == "above":
        # sway has no always-on-top; sticky is the closest
        run(["swaymsg", c, "sticky", "toggle"], timeout=6)
    elif state == "floating":
        run(["swaymsg", c, "floating", "enable" if on else "disable"],
            timeout=6)
    else:
        raise CuError(f"sway does not support state '{state}'")


def desktops() -> list[dict]:
    try:
        arr = json.loads(_msg("-t", "get_workspaces"))
        return [{"index": w.get("num", i), "name": w.get("name", ""),
                 "current": bool(w.get("focused"))}
                for i, w in enumerate(arr)]
    except Exception:
        return []


def switch_desktop(idx: int) -> None:
    run(["swaymsg", "workspace", str(int(idx))], timeout=6)


def move_to_desktop(handle, idx: int) -> None:
    run(["swaymsg", _crit(handle), "move", "container", "to", "workspace",
         str(int(idx))], timeout=6)


def cursor_pos() -> dict | None:
    # sway IPC has no cursor query (PR#8780 stalled); wl-find-cursor is a
    # layer-shell hack we don't take.
    return None
