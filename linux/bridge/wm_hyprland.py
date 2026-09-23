"""Hyprland backend — hyprctl -j.

Handle = window address ("0x..."). Has cursor position (hyprctl cursorpos).
minimize → special workspace; maximize → fullscreen.
"""
from __future__ import annotations

import json

from errors import CuError
from util import run, run_out, which

_BACKEND = "hyprland"


def available() -> bool:
    return which("hyprctl") is not None


def _clients() -> list[dict]:
    try:
        return json.loads(run_out(["hyprctl", "clients", "-j"], timeout=6))
    except Exception:
        return []


def list_windows() -> list[dict]:
    wins = []
    for c in _clients():
        if not c.get("mapped", True):
            continue
        at = c.get("at") or [0, 0]
        sz = c.get("size") or [0, 0]
        wins.append({
            "handle": c.get("address", ""),
            "title": c.get("title", ""),
            "pid": c.get("pid", 0),
            "app_id": c.get("class", ""),
            "geometry": {"x": at[0], "y": at[1], "w": sz[0], "h": sz[1]},
            "focused": False,   # filled below
            "floating": bool(c.get("floating")),
            "workspace": (c.get("workspace") or {}).get("id", -1),
            "backend": _BACKEND,
        })
    try:
        aw = json.loads(run_out(["hyprctl", "activewindow", "-j"], timeout=4))
        for w in wins:
            w["focused"] = (w["handle"] == aw.get("address"))
    except Exception:
        pass
    return wins


def _addr(handle) -> str:
    h = str(handle)
    return h if h.startswith("0x") else f"address:{h}"


def focus(handle) -> None:
    run(["hyprctl", "dispatch", "focuswindow", f"address:{handle}"], timeout=6)


def close(handle) -> None:
    run(["hyprctl", "dispatch", "closewindow", f"address:{handle}"], timeout=6)


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    a = f"address:{handle}"
    if x is not None and y is not None:
        run(["hyprctl", "dispatch", "movewindowpixel",
             f"exact {int(x)} {int(y)},{a}"], timeout=6)
    if w is not None and h is not None:
        run(["hyprctl", "dispatch", "resizewindowpixel",
             f"exact {int(w)} {int(h)},{a}"], timeout=6)


def set_state(handle, state: str, on: bool = True) -> None:
    a = f"address:{handle}"
    if state == "minimize":
        if on:
            run(["hyprctl", "dispatch", "movetoworkspacesilent",
                 f"special:min,{a}"], timeout=6)
        else:
            run(["hyprctl", "dispatch", "movetoworkspacesilent",
                 f"+0,{a}"], timeout=6)
    elif state in ("maximize", "fullscreen"):
        run(["hyprctl", "dispatch", "fullscreen",
             f"1,{a}" if on else f"0,{a}"], timeout=6)
    elif state == "above":
        run(["hyprctl", "dispatch", "pin", a], timeout=6)
    elif state == "floating":
        run(["hyprctl", "dispatch", "setfloating", a], timeout=6)
    else:
        raise CuError(f"hyprland does not support state '{state}'")


def desktops() -> list[dict]:
    try:
        arr = json.loads(run_out(["hyprctl", "workspaces", "-j"], timeout=6))
        aw = json.loads(run_out(["hyprctl", "activeworkspace", "-j"], timeout=4))
        cur = aw.get("id")
        return [{"index": w.get("id", i), "name": w.get("name", ""),
                 "current": w.get("id") == cur}
                for i, w in enumerate(arr)]
    except Exception:
        return []


def switch_desktop(idx: int) -> None:
    run(["hyprctl", "dispatch", "workspace", str(int(idx))], timeout=6)


def move_to_desktop(handle, idx: int) -> None:
    run(["hyprctl", "dispatch", "movetoworkspace",
         f"{int(idx)},address:{handle}"], timeout=6)


def cursor_pos() -> dict | None:
    try:
        p = json.loads(run_out(["hyprctl", "cursorpos", "-j"], timeout=4))
        return {"x": int(p.get("x", 0)), "y": int(p.get("y", 0))}
    except Exception:
        out = run_out(["hyprctl", "cursorpos"], timeout=4)
        try:
            x, y = out.replace(",", " ").split()[:2]
            return {"x": int(x), "y": int(y)}
        except Exception:
            return None
