"""Wayfire backend — JSON over $WAYFIRE_SOCKET (ipc + ipc-rules plugins).

Handle = view id (int). Closest-to-X11 feature set among wlroots compositors:
real x/y/w/h, true minimize, sticky, always-on-top.
"""
from __future__ import annotations

import json
import os
import socket

from errors import CuError, UnsupportedCompositor
from util import which

_BACKEND = "wayfire"


def available() -> bool:
    return bool(os.environ.get("WAYFIRE_SOCKET"))


def _sock() -> socket.socket:
    path = os.environ["WAYFIRE_SOCKET"]
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.settimeout(6)
    return s


def _call(method: str, data: dict | None = None) -> dict:
    payload = json.dumps({"method": method, "data": data or {}}).encode()
    s = _sock()
    try:
        # wayfire IPC: 4-byte little-endian length prefix + JSON
        s.sendall(len(payload).to_bytes(4, "little") + payload)
        hdr = b""
        while len(hdr) < 4:
            chunk = s.recv(4 - len(hdr))
            if not chunk:
                raise CuError("wayfire socket closed mid-header")
            hdr += chunk
        n = int.from_bytes(hdr, "little")
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode() or "{}")
    finally:
        s.close()


def list_windows() -> list[dict]:
    resp = _call("window-rules/list-views") or {}
    views = resp.get("views") or resp.get("result") or []
    if isinstance(views, dict):
        views = list(views.values())
    wins = []
    for v in views:
        g = v.get("geometry") or {}
        st = v.get("state") or {}
        wins.append({
            "handle": v.get("id"),
            "title": v.get("title", ""),
            "pid": v.get("pid", 0),
            "app_id": v.get("app-id", ""),
            "geometry": {"x": g.get("x", 0), "y": g.get("y", 0),
                         "w": g.get("width", 0), "h": g.get("height", 0)},
            "focused": bool(v.get("focused")),
            "minimized": bool(st.get("minimized")),
            "workspace": v.get("workspace", -1),
            "backend": _BACKEND,
        })
    return wins


def focus(handle) -> None:
    _call("window-rules/focus-view", {"id": int(handle)})


def close(handle) -> None:
    _call("window-rules/close-view", {"id": int(handle)})


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    wins = {w["handle"]: w for w in list_windows()}
    cur = (wins.get(int(handle)) or {}).get("geometry") or {}
    _call("window-rules/configure-view", {
        "id": int(handle),
        "x": int(x) if x is not None else cur.get("x", 0),
        "y": int(y) if y is not None else cur.get("y", 0),
        "w": int(w) if w is not None else cur.get("w", 0),
        "h": int(h) if h is not None else cur.get("h", 0)})


def set_state(handle, state: str, on: bool = True) -> None:
    vid = int(handle)
    if state == "minimize":
        _call("window-rules/set-view-minimized", {"id": vid, "state": on})
    elif state == "fullscreen":
        _call("window-rules/set-view-fullscreen", {"id": vid, "state": on})
    elif state == "above":
        _call("window-rules/set-view-always-on-top", {"id": vid, "state": on})
    elif state == "sticky":
        _call("window-rules/set-view-sticky", {"id": vid, "state": on})
    else:
        raise CuError(f"wayfire does not support state '{state}'")


def desktops() -> list[dict]:
    return []  # wayfire wsets — workspace info via wset_info; list shallow


def cursor_pos() -> dict | None:
    return None
