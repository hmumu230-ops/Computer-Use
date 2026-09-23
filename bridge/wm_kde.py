"""KDE Plasma window backend — kdotool preferred, KWin-script injection fallback.

Handle = KWin internalId (string). Works on Wayland and X11 sessions.
KWin scripting: loadScript → run → stop → unloadScript; results return via
print() → journalctl _COMM=kwin_* (same channel kdotool uses internally).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid

from errors import CuError, UnsupportedCompositor
from util import run, run_out, which

_BACKEND = "kde"


def available() -> bool:
    return which("kdotool") is not None or which("dbus-send") is not None \
        or which("qdbus") is not None or which("qdbus6") is not None


def _kdotool(*args) -> str:
    return run_out(["kdotool", *[str(a) for a in args]], timeout=6)


def list_windows() -> list[dict]:
    if which("kdotool"):
        return _list_kdotool()
    return _list_kwinscript()


def _list_kdotool() -> list[dict]:
    out = _kdotool("search", "--classname", ".*", "-l", "200")
    wins = []
    active = _kdotool("getactivewindow").strip()
    for line in out.splitlines():
        wid = line.strip()
        if not wid:
            continue
        geo = _kdotool("getwindowgeometry", "--shell", wid)
        g = {}
        for ln in geo.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                if v.lstrip("-").isdigit():
                    g[k.lower()] = int(v)
        wins.append({
            "handle": wid,
            "title": _kdotool("getwindowname", wid).strip(),
            "pid": int((_kdotool("getwindowpid", wid).strip() or "0")),
            "geometry": {"x": g.get("x", 0), "y": g.get("y", 0),
                         "w": g.get("width", 0), "h": g.get("height", 0)},
            "focused": wid == active,
            "backend": _BACKEND,
        })
    return wins


def _kwin_script(js_body: str) -> str:
    """Inject JS into KWin; result comes back through journalctl print()."""
    tag = f"lcu_{uuid.uuid4().hex[:8]}"
    script = (
        f"try{{var r=(function(){{{js_body}}})();"
        f"print('{tag}:'+JSON.stringify(r));}}"
        f"catch(e){{print('{tag}:ERR:'+e);}}")
    fd, path = tempfile.mkstemp(suffix=".js", prefix="lcu-kwin-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        sid = run_out(["dbus-send", "--session", "--print-reply=literal",
                       "--dest=org.kde.KWin", "/Scripting",
                       "org.kde.kwin.Scripting.loadScript",
                       f"string:{path}", f"string:{tag}"])
        sid = sid.strip().split()[-1] if sid.strip() else ""
        if not sid.isdigit():
            raise UnsupportedCompositor("KWin script injection failed",
                                        compositor="kde")
        spath = f"/Scripting/Script{sid}"
        run_out(["dbus-send", "--session", "--dest=org.kde.KWin", spath,
                 "org.kde.kwin.Script.run"])
        time.sleep(0.4)
        run_out(["dbus-send", "--session", "--dest=org.kde.KWin", spath,
                 "org.kde.kwin.Script.stop"])
        run_out(["dbus-send", "--session", "--dest=org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.unloadScript", f"string:{tag}"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    for comm in ("kwin_wayland", "kwin_x11"):
        out = run_out(["journalctl", f"_COMM={comm}", "-o", "cat",
                       "--since", "-10s", "--no-pager"])
        for line in reversed(out.splitlines()):
            if line.startswith(f"{tag}:"):
                payload = line[len(tag) + 1:]
                if payload.startswith("ERR:"):
                    raise CuError(f"KWin script error: {payload[4:]}")
                return payload
    raise CuError("KWin script produced no output",
                  hint="journalctl _COMM=kwin_* empty — check session bus")


def _list_kwinscript() -> list[dict]:
    payload = _kwin_script("""
      const out=[];
      for (const w of workspace.windowList()) {
        if (!w.normalWindow) continue;
        const g=w.frameGeometry;
        out.push({id:w.internalId,title:w.caption,pid:w.pid,
          cls:w.resourceClass.toString(),x:g.x,y:g.y,w:g.width,h:g.height,
          minimized:w.minimized,active:w===workspace.activeWindow});
      }
      return out;
    """)
    wins = []
    for w in json.loads(payload):
        wins.append({
            "handle": w["id"], "title": w.get("title", ""),
            "pid": w.get("pid", 0),
            "geometry": {"x": w["x"], "y": w["y"], "w": w["w"], "h": w["h"]},
            "focused": w.get("active", False),
            "minimized": w.get("minimized", False),
            "backend": _BACKEND,
        })
    return wins


def _ensure_id(handle) -> str:
    return str(handle)


def focus(handle) -> None:
    if which("kdotool"):
        run(["kdotool", "windowactivate", str(handle)], timeout=6)
        time.sleep(0.05)
        return
    _kwin_script(f"""
      for (const w of workspace.windowList())
        if (w.internalId === '{_ensure_id(handle)}')
          {{ workspace.setActiveWindow(w); return true; }}
      return false;
    """)


def close(handle) -> None:
    if which("kdotool"):
        run(["kdotool", "windowclose", str(handle)], timeout=6)
        return
    _kwin_script(f"""
      for (const w of workspace.windowList())
        if (w.internalId === '{_ensure_id(handle)}')
          {{ w.closeWindow(); return true; }}
      return false;
    """)


def move_resize(handle, x=None, y=None, w=None, h=None) -> None:
    if which("kdotool"):
        if x is not None or y is not None:
            g = _geom_kdotool(handle)
            run(["kdotool", "windowmove", str(handle),
                 str(x if x is not None else g["x"]),
                 str(y if y is not None else g["y"])], timeout=6)
        if w is not None or h is not None:
            g = _geom_kdotool(handle)
            run(["kdotool", "windowsize", str(handle),
                 str(w if w is not None else g["w"]),
                 str(h if h is not None else g["h"])], timeout=6)
        return
    _kwin_script(f"""
      for (const w of workspace.windowList())
        if (w.internalId === '{_ensure_id(handle)}') {{
          const g = w.frameGeometry;
          w.frameGeometry = {{x:{int(x) if x is not None else 'g.x'},
            y:{int(y) if y is not None else 'g.y'},
            width:{int(w) if w is not None else 'g.width'},
            height:{int(h) if h is not None else 'g.height'}}};
          return true;
        }}
      return false;
    """)


def _geom_kdotool(handle) -> dict:
    out = _kdotool("getwindowgeometry", "--shell", str(handle))
    g = {}
    for ln in out.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            if v.lstrip("-").isdigit():
                g[k.lower()] = int(v)
    return {"x": g.get("x", 0), "y": g.get("y", 0),
            "w": g.get("width", 0), "h": g.get("height", 0)}


def set_state(handle, state: str, on: bool = True) -> None:
    mapping = {
        "minimize": "minimized", "above": "above", "fullscreen": "fullscreen",
        "shaded": "shaded", "sticky": "keep_above",
    }
    if which("kdotool") and state in ("minimize", "above", "fullscreen",
                                    "shaded"):
        prop = {"minimize": "minimized", "above": "above",
                "fullscreen": "fullscreen", "shaded": "shaded"}[state]
        op = "add" if on else "remove"
        run(["kdotool", "windowstate", f"--{op}", prop.upper(),
             str(handle)], timeout=6)
        return
    # generic script path
    js_prop = mapping.get(state)
    if js_prop is None:
        raise CuError(f"unknown window state {state}")
    val = "true" if on else "false"
    _kwin_script(f"""
      for (const w of workspace.windowList())
        if (w.internalId === '{_ensure_id(handle)}')
          {{ w['{js_prop}'] = {val}; return true; }}
      return false;
    """)


def desktops() -> list[dict]:
    out = run_out(["qdbus", "org.kde.KWin", "/VirtualDesktopManager",
                   "org.kde.KWin.VirtualDesktopManager.desktops"]) or \
        run_out(["qdbus6", "org.kde.KWin", "/VirtualDesktopManager",
                 "org.kde.KWin.VirtualDesktopManager.desktops"])
    try:
        arr = json.loads(out) if out.strip().startswith("[") else []
        cur = run_out(["qdbus", "org.kde.KWin", "/VirtualDesktopManager",
                       "org.kde.KWin.VirtualDesktopManager.current"]) or \
            run_out(["qdbus6", "org.kde.KWin", "/VirtualDesktopManager",
                     "org.kde.KWin.VirtualDesktopManager.current"])
        cur = cur.strip()
        return [{"index": d.get("position", i), "id": d.get("id", ""),
                 "name": d.get("name", ""), "current": d.get("id") == cur}
                for i, d in enumerate(arr)]
    except Exception:
        return []


def cursor_pos() -> dict | None:
    if which("kdotool"):
        out = _kdotool("getmouselocation", "--shell")
        pos = {}
        for ln in out.splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                if v.lstrip("-").isdigit():
                    pos[k.lower()] = int(v)
        if "x" in pos:
            return {"x": pos["x"], "y": pos.get("y", 0)}
    return None
