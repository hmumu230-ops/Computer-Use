"""X11/EWMH window backend — wmctrl + xdotool + xprop.

Covers every EWMH-compliant WM (GNOME-X11, KDE-X11, XFCE, Cinnamon, MATE,
openbox, i3, ...). Window handle = X11 window id (int).
"""
from __future__ import annotations

import time

from errors import ToolNotFound, CuError
from util import run, run_out, which


def available() -> bool:
    return which("wmctrl") is not None and which("xdotool") is not None


def list_windows() -> list[dict]:
    if not available():
        raise ToolNotFound("wmctrl/xdotool")
    out = run_out(["wmctrl", "-lpG"])
    active = _active_wid()
    wins = []
    for line in out.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        wid_hex, desk, pid, x, y, w, h, _host, title = parts
        try:
            wid = int(wid_hex, 16)
            geo = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
            pid_i = int(pid)
        except ValueError:
            continue
        wins.append({
            "handle": wid, "title": title, "pid": pid_i,
            "geometry": geo, "focused": wid == active,
            "desktop": int(desk) if desk.lstrip("-").isdigit() else -1,
        })
    return wins


def _active_wid() -> int | None:
    out = run_out(["xdotool", "getactivewindow"]).strip()
    try:
        return int(out)
    except ValueError:
        return None


def focus(handle) -> None:
    run(["xdotool", "windowactivate", "--sync", str(int(handle))], timeout=5)
    time.sleep(0.05)


def close(handle) -> None:
    run(["wmctrl", "-i", "-c", str(int(handle))])


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    cur = _geom(int(handle))
    x = cur["x"] if x is None else int(x)
    y = cur["y"] if y is None else int(y)
    w = cur["w"] if w is None else int(w)
    h = cur["h"] if h is None else int(h)
    run(["wmctrl", "-i", "-r", str(int(handle)), "-e", f"0,{x},{y},{w},{h}"])


def _geom(wid: int) -> dict:
    out = run_out(["xdotool", "getwindowgeometry", "--shell", str(wid)])
    g = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if v.lstrip("-").isdigit():
                g[k.lower()] = int(v)
    return {"x": g.get("x", 0), "y": g.get("y", 0),
            "w": g.get("width", 0), "h": g.get("height", 0)}


_WM_STATE = {
    "minimize": ("add", "hidden"),
    "unminimize": ("remove", "hidden"),
    "maximize": ("add", "maximized_vert,maximized_horz"),
    "unmaximize": ("remove", "maximized_vert,maximized_horz"),
    "above": ("add", "above"),
    "unabove": ("remove", "above"),
    "fullscreen": ("add", "fullscreen"),
    "unfullscreen": ("remove", "fullscreen"),
    "shaded": ("add", "shaded"),
    "sticky": ("add", "sticky"),
}


def set_state(handle, state: str, on: bool = True) -> None:
    wid = str(int(handle))
    if state == "minimize" and on:
        run(["xdotool", "windowminimize", wid])
        return
    if state not in _WM_STATE:
        raise CuError(f"unknown window state {state}")
    op, prop = _WM_STATE[state]
    if not on:
        op = "remove" if op == "add" else "add"
    run(["wmctrl", "-i", "-r", wid, "-b", f"{op},{prop}"])


def desktops() -> list[dict]:
    out = run_out(["wmctrl", "-d"])
    desks = []
    for line in out.splitlines():
        parts = line.split(None, 9)
        if len(parts) >= 2:
            desks.append({"index": int(parts[0]), "current": parts[1] == "*",
                          "name": parts[-1]})
    return desks


def switch_desktop(idx: int) -> None:
    run(["wmctrl", "-s", str(int(idx))])


def move_to_desktop(handle, idx: int) -> None:
    run(["wmctrl", "-i", "-r", str(int(handle)), "-t", str(int(idx))])


def cursor_pos() -> dict | None:
    out = run_out(["xdotool", "getmouselocation", "--shell"])
    pos = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if v.lstrip("-").isdigit():
                pos[k.lower()] = int(v)
    if "x" in pos and "y" in pos:
        return {"x": pos["x"], "y": pos["y"], "screen": pos.get("screen", 0)}
    return None


def stacking_order() -> list[int]:
    """_NET_CLIENT_LIST_STACKING (bottom→top)."""
    out = run_out(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"])
    ids = []
    for tok in out.replace(",", " ").split():
        if tok.startswith("0x"):
            try:
                ids.append(int(tok, 16))
            except ValueError:
                pass
    return ids
