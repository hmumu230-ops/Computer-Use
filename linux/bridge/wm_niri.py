"""niri backend — `niri msg --json` (single-line JSON over $NIRI_SOCKET).

Handle = window id (u64). Scrollable-tiling: free move only for floating
windows; maximize ≈ maximize-column / fullscreen-window.
"""
from __future__ import annotations

import json

from errors import CuError
from util import run, run_out, which

_BACKEND = "niri"


def available() -> bool:
    return which("niri") is not None


def _j(*args) -> object:
    try:
        return json.loads(run_out(["niri", "msg", "--json",
                                   *[str(a) for a in args]], timeout=6))
    except Exception:
        return None


def list_windows() -> list[dict]:
    arr = _j("windows") or []
    wins = []
    for w in arr:
        lay = w.get("layout") or {}
        size = lay.get("window_size") or [0, 0]
        pos = lay.get("tile_pos_in_workspace_view") or [0, 0]
        off = lay.get("window_offset_in_tile") or [0, 0]
        wins.append({
            "handle": w.get("id"),
            "title": w.get("title", ""),
            "pid": w.get("pid", 0),
            "app_id": w.get("app_id", ""),
            "geometry": {"x": pos[0] + off[0], "y": pos[1] + off[1],
                         "w": size[0], "h": size[1]},
            "focused": bool(w.get("is_focused")),
            "floating": bool(w.get("is_floating")),
            "workspace": w.get("workspace_id", -1),
            "backend": _BACKEND,
        })
    return wins


def _id(handle) -> str:
    return str(int(handle))


def focus(handle) -> None:
    run(["niri", "msg", "action", "focus-window", "--id", _id(handle)],
        timeout=6)


def close(handle) -> None:
    run(["niri", "msg", "action", "close-window", "--id", _id(handle)],
        timeout=6)


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    i = _id(handle)
    if x is not None and y is not None:
        run(["niri", "msg", "action", "move-floating-window", "--id", i,
             "-x", str(int(x)), "-y", str(int(y))], timeout=6)
    if w is not None:
        run(["niri", "msg", "action", "set-window-width", "--id", i,
             str(int(w))], timeout=6)
    if h is not None:
        run(["niri", "msg", "action", "set-window-height", "--id", i,
             str(int(h))], timeout=6)


def set_state(handle, state: str, on: bool = True) -> None:
    i = _id(handle)
    if state == "maximize":
        run(["niri", "msg", "action", "maximize-column"], timeout=6)
    elif state == "fullscreen":
        run(["niri", "msg", "action", "fullscreen-window", "--id", i],
            timeout=6)
    elif state == "floating":
        run(["niri", "msg", "action",
             "move-window-to-floating" if on else "move-window-to-tiling",
             "--id", i], timeout=6)
    else:
        raise CuError(f"niri does not support state '{state}'",
                      hint="niri has no minimize; move to another workspace")


def desktops() -> list[dict]:
    arr = _j("workspaces") or []
    return [{"index": w.get("idx", i), "id": w.get("id"),
             "name": w.get("name", ""), "current": bool(w.get("is_focused"))}
            for i, w in enumerate(arr)]


def switch_desktop(idx: int) -> None:
    run(["niri", "msg", "action", "focus-workspace", str(int(idx))], timeout=6)


def move_to_desktop(handle, idx: int) -> None:
    run(["niri", "msg", "action", "move-window-to-workspace",
         "--id", _id(handle), str(int(idx))], timeout=6)


def cursor_pos() -> dict | None:
    return None
