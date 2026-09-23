"""GNOME Wayland backend.

Two paths:
- window-calls extension (`org.gnome.Shell.Extensions.Windows`) — full
  list/activate/move/resize/min/max/close. Handle = meta_window id (u32).
- unsafe_mode Eval — same capabilities via JS; used when extension absent.

Bare GNOME Wayland (no ext, safe mode) has NO window API — router reports
UNSUPPORTED_COMPOSITOR with the extension-install hint.
"""
from __future__ import annotations

import json

from errors import CuError, UnsupportedCompositor
from util import run, run_out, which

_BACKEND = "gnome"
_EXT_PATH = "/org/gnome/Shell/Extensions/Windows"
_EXT_IFACE = "org.gnome.Shell.Extensions.Windows"


def _gdbus_call(method: str, *args) -> str:
    cmd = ["gdbus", "call", "--session", "-d", "org.gnome.Shell",
           "-o", _EXT_PATH, "-m", f"{_EXT_IFACE}.{method}", *args]
    return run_out(cmd, timeout=6)


def _unwrap_json(out: str) -> object:
    """gdbus returns ('<json>',) — strip the tuple shell."""
    s = out.strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].rstrip(",").strip()
    if s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    s = s.replace("\\'", "'").replace("\\\\", "\\")
    try:
        return json.loads(s)
    except Exception:
        return None


def _has_ext() -> bool:
    out = _gdbus_call("List")
    return bool(out.strip()) and "DBus.Error" not in out


def _unsafe() -> bool:
    out = run_out(["gdbus", "call", "--session", "-d", "org.gnome.Shell",
                   "-o", "/org/gnome/Shell", "-m", "org.gnome.Shell.Eval",
                   "true"], timeout=4)
    return out.startswith("(true,")


def available() -> bool:
    return _has_ext() or _unsafe()


def _eval(js: str) -> object:
    out = run_out(["gdbus", "call", "--session", "-d", "org.gnome.Shell",
                   "-o", "/org/gnome/Shell", "-m", "org.gnome.Shell.Eval",
                   js], timeout=6)
    # returns (true, '<result-string>')
    s = out.strip()
    if not s.startswith("(true,"):
        raise UnsupportedCompositor(
            "gnome-shell Eval refused (safe mode)", compositor="gnome")
    inner = s[6:].rstrip(")").strip()
    if inner.startswith("'") and inner.endswith("'"):
        inner = inner[1:-1]
    try:
        return json.loads(inner)
    except Exception:
        return inner


def list_windows() -> list[dict]:
    if _has_ext():
        data = _unwrap_json(_gdbus_call("List")) or []
        return [{
            "handle": w.get("id"),
            "title": w.get("title", ""),
            "pid": w.get("pid", 0),
            "app_id": w.get("wm_class", ""),
            "geometry": {"x": w.get("x", 0), "y": w.get("y", 0),
                         "w": w.get("width", 0), "h": w.get("height", 0)},
            "focused": bool(w.get("focus")),
            "workspace": w.get("workspace", -1),
            "backend": _BACKEND,
        } for w in data]
    if _unsafe():
        data = _eval("""
          JSON.stringify(global.get_window_actors().map(a => {
            const w = a.meta_window, r = w.get_frame_rect();
            return {id: w.get_id(), title: w.get_title(),
                    pid: w.get_pid(), cls: w.get_wm_class() || '',
                    x: r.x, y: r.y, w: r.width, h: r.height,
                    focus: w.has_focus(), ws: w.get_workspace().index()};
          }))""") or "[]"
        arr = data if isinstance(data, list) else json.loads(data or "[]")
        return [{
            "handle": w["id"], "title": w.get("title", ""),
            "pid": w.get("pid", 0), "app_id": w.get("cls", ""),
            "geometry": {"x": w["x"], "y": w["y"], "w": w["w"], "h": w["h"]},
            "focused": bool(w.get("focus")), "workspace": w.get("ws", -1),
            "backend": _BACKEND,
        } for w in arr]
    raise UnsupportedCompositor(
        "GNOME Wayland exposes no window API without the window-calls "
        "extension or unsafe_mode", compositor="gnome",
        hint="gnome-extensions install window-calls@domandoman.xyz, or "
             "enable unsafe_mode for Eval access")


def focus(handle) -> None:
    if _has_ext():
        _gdbus_call("Activate", str(int(handle)))
        return
    _eval(f"""
      for (const a of global.get_window_actors())
        if (a.meta_window.get_id() === {int(handle)})
          {{ Main.activateWindow(a.meta_window); return 'ok'; }}
      return 'missing';""")


def close(handle) -> None:
    if _has_ext():
        _gdbus_call("Close", str(int(handle)))
        return
    _eval(f"""
      for (const a of global.get_window_actors())
        if (a.meta_window.get_id() === {int(handle)})
          {{ a.meta_window.delete(global.get_current_time()); return 'ok'; }}
      return 'missing';""")


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    wid = int(handle)
    if _has_ext():
        cur = _unwrap_json(_gdbus_call("GetFrameBounds", str(wid))) or {}
        _gdbus_call("MoveResize", str(wid),
                    str(int(x) if x is not None else cur.get("x", 0)),
                    str(int(y) if y is not None else cur.get("y", 0)),
                    str(int(w) if w is not None else cur.get("width", 0)),
                    str(int(h) if h is not None else cur.get("height", 0)))
        return
    _eval(f"""
      for (const a of global.get_window_actors())
        if (a.meta_window.get_id() === {wid}) {{
          const r = a.meta_window.get_frame_rect();
          a.meta_window.move_resize_frame(true,
            {int(x) if x is not None else 'r.x'},
            {int(y) if y is not None else 'r.y'},
            {int(w) if w is not None else 'r.width'},
            {int(h) if h is not None else 'r.height'});
          return 'ok'; }}
      return 'missing';""")


def set_state(handle, state: str, on: bool = True) -> None:
    wid = int(handle)
    if _has_ext():
        m = {"minimize": "Minimize" if on else "Unminimize",
             "maximize": "Maximize" if on else "Unmaximize"}.get(state)
        if m is None:
            raise CuError(f"window-calls does not support state '{state}'")
        _gdbus_call(m, str(wid))
        return
    js = {
        ("minimize", True): "a.meta_window.minimize()",
        ("minimize", False): "a.meta_window.unminimize()",
        ("maximize", True): "a.meta_window.maximize(Meta.MaximizeFlags.BOTH)",
        ("maximize", False): "a.meta_window.unmaximize(Meta.MaximizeFlags.BOTH)",
    }.get((state, on))
    if js is None:
        raise CuError(f"gnome does not support state '{state}' on={on}")
    _eval(f"""
      for (const a of global.get_window_actors())
        if (a.meta_window.get_id() === {wid}) {{ {js}; return 'ok'; }}
      return 'missing';""")


def desktops() -> list[dict]:
    if not _unsafe():
        return []
    data = _eval("""
      JSON.stringify({n: global.workspace_manager.n_workspaces,
                      cur: global.workspace_manager.get_active_workspace_index()})
    """) or "{}"
    try:
        d = data if isinstance(data, dict) else json.loads(data)
        return [{"index": i, "current": i == d.get("cur")}
                for i in range(d.get("n", 0))]
    except Exception:
        return []


def cursor_pos() -> dict | None:
    if not _unsafe():
        return None
    data = _eval("JSON.stringify(global.get_pointer())")
    try:
        x, y, *_ = data if isinstance(data, list) else json.loads(data)
        return {"x": int(x), "y": int(y)}
    except Exception:
        return None
