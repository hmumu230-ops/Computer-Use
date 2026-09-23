#!/usr/bin/env python3
"""Linux computer-use bridge — enhanced fork.

Newline-delimited JSON protocol over stdio:
  request : {"id": ..., "cmd": "...", ...args}
  response: {"id": ..., "ok": true, "result": ...}
            {"id": ..., "ok": false, "error": {code,message,hint,retryable}}

Handshake: send {"cmd":"hello"} → {version, capabilities, session}.

Sibling modules in this directory are importable because the script dir is
sys.path[0] when spawned as `python3 bridge.py`. Runs on the system python
(`/usr/bin/python3`) so `gi.repository.Atspi` is available.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import CuError, InvalidArgs, UnknownCommand, to_error_dict  # noqa: E402
import util  # noqa: E402
import detect  # noqa: E402
import refs  # noqa: E402
import safety  # noqa: E402

VERSION = "0.3.0"
STORE = refs.RefStore()


# ---------- args ----------

def _args(req: dict, *specs) -> dict:
    """Extract declared args. specs: name | (name, default)."""
    out = {}
    for s in specs:
        if isinstance(s, tuple):
            out[s[0]] = req.get(s[0], s[1])
        else:
            if s not in req:
                raise InvalidArgs(f"missing required arg '{s}'")
            out[s[0]] = req[s]
    return out


# ---------- session / introspection ----------

def cmd_hello(req):
    return {"version": VERSION,
            "capabilities": detect.capabilities(),
            "session": detect.detect_env().to_dict()}


def cmd_ping(req):
    return {"pong": True}


def cmd_capabilities(req):
    return detect.capabilities()


def cmd_probe(req):
    import sysprobe
    return sysprobe.probe()


def cmd_preflight(req):
    import sysprobe
    a = _args(req, "action", ("required", ""))
    return sysprobe.preflight(a["action"], a["required"])


# ---------- windows ----------

def cmd_list_windows(req):
    STORE.new_generation()  # window listing also mints fresh @wN refs
    return {"windows": __import__("wm_router").list_windows(STORE)}


def _wm():
    return __import__("wm_router")


def cmd_window_focus(req):
    a = _args(req, "ref")
    return _wm().focus(STORE, a["ref"])


def cmd_window_close(req):
    a = _args(req, "ref")
    safety.gate("window:close", {"ref": a["ref"]}, True,
                req.get("confirmToken", ""))
    return _wm().close(STORE, a["ref"])


def cmd_window_move(req):
    a = _args(req, "ref")
    return _wm().move_resize(STORE, a["ref"], x=req.get("x"), y=req.get("y"),
                             w=req.get("w"), h=req.get("h"))


def cmd_window_state(req):
    a = _args(req, "ref", "state")
    return _wm().set_state(STORE, a["ref"], a["state"],
                           bool(req.get("on", True)))


def cmd_desktops(req):
    return {"desktops": _wm().desktops()}


def cmd_switch_desktop(req):
    a = _args(req, "index")
    return _wm().switch_desktop(int(a["index"]))


def cmd_window_to_desktop(req):
    a = _args(req, "ref", "index")
    return _wm().move_to_desktop(STORE, a["ref"], int(a["index"]))


def cmd_cursor_pos(req):
    from errors import UnsupportedCompositor
    pos = _wm().cursor_pos()
    if pos is None:
        raise UnsupportedCompositor(
            "cursor position not exposed by this compositor",
            compositor=detect.detect_env().compositor,
            hint="readable on X11, KDE (kdotool), Hyprland only")
    return pos


# ---------- snapshot / elements ----------

def _resolve_window_rect(win_ref: str | None) -> dict | None:
    if not win_ref:
        return None
    w = STORE.try_get(win_ref)
    if w is None:
        raise InvalidArgs(f"unknown window ref {win_ref}")
    return w.geometry


def cmd_snapshot(req):
    """Screenshot + AT-SPI element enumeration. Returns fresh generation."""
    import shot
    import a11y

    win_ref = req.get("window")
    region = req.get("region")          # {x,y,w,h} logical
    include_tree = bool(req.get("tree", True))
    app_pid = req.get("pid")

    rect = _resolve_window_rect(win_ref) or region
    cap = shot.capture(window_rect=rect)
    with open(cap["path"], "rb") as f:
        png = f.read()
    try:
        os.remove(cap["path"])
    except OSError:
        pass

    STORE.new_generation()
    windows = []
    try:
        windows = _wm().list_windows(STORE)
    except CuError:
        pass

    elements = []
    if include_tree:
        try:
            a11y.init()
            root = None
            if app_pid:
                root = a11y.app_root_for_pid(int(app_pid))
            elif win_ref:
                w = STORE.try_get(win_ref)
                if w and w.pid:
                    root = a11y.app_root_for_pid(w.pid)
            if root is None:
                # focused window's app, else all apps
                fw = next((w for w in STORE.windows.values() if w.focused), None)
                if fw and fw.pid:
                    root = a11y.app_root_for_pid(fw.pid)
            if root is None:
                roots = a11y.app_roots()
                for r in roots:
                    for ax in a11y.walk(r):
                        elements.append(_register(ax))
            else:
                for ax in a11y.walk(root):
                    elements.append(_register(ax))
        except CuError as e:
            elements = []
            util.log(f"atspi walk skipped: {e.message}")

    return {
        "stateId": uuid.uuid4().hex[:12],
        "generation": STORE.generation,
        "pngBase64": base64.b64encode(png).decode("ascii"),
        "width": cap["width"], "height": cap["height"],
        "scale": cap.get("scale", 1.0),
        "backend": cap.get("backend", ""),
        "windows": windows,
        "elements": elements,
    }


def _register(ax) -> dict:
    el = STORE.add_element(
        bus_name=ax.bus_name, pid=ax.pid, index_path=ax.index_path,
        role=ax.role, name=ax.name, nth=ax.nth, bbox=ax.bbox,
        states=ax.states, actions=ax.actions,
        interfaces=ax.interfaces, node=ax.node)
    return {
        "ref": el.ref, "role": el.role, "name": el.name,
        "bbox": el.bbox,
        "canPress": ax.can_press, "canSetText": ax.can_set_text,
        "canFocus": ax.can_focus,
        "states": sorted(s for s in el.states if s in
                         ("enabled", "disabled", "checked", "expanded",
                          "collapsed", "focused", "pressed", "selected",
                          "editable", "read_only", "required",
                          "indeterminate", "busy", "modal", "sensitive")),
        "actions": sorted(el.actions),
    }


def _resolve_el(ref: str):
    import a11y
    el = STORE.elements.get(ref)
    if el is None:
        raise InvalidArgs(f"unknown element ref {ref}")
    if el.synthetic:
        return el, None
    node = STORE.resolve_element(
        ref, lambda loc: a11y.resolve_locator(
            loc.bus_name, loc.pid, loc.index_path, loc.role, loc.name))
    return el, node.node if hasattr(node, "node") else node


def cmd_find_elements(req):
    import a11y
    a = _args(req)
    role = req.get("role", "")
    name = req.get("name", "")
    states = tuple(req.get("states", []))
    limit = int(req.get("limit", 50))
    pid = req.get("pid")
    a11y.init()
    root = a11y.app_root_for_pid(int(pid)) if pid else None
    hits = []
    if root is not None:
        hits = a11y.find_elements(root, role, name, states, limit)
    else:
        for r in a11y.app_roots():
            hits += a11y.find_elements(r, role, name, states, limit)
            if len(hits) >= limit:
                break
    return {"elements": [_register(h) for h in hits[:limit]]}


def cmd_find_text(req):
    import a11y
    import ocr
    import shot
    import tempfile
    needle = req.get("text") or req.get("needle")
    if not needle:
        raise InvalidArgs("missing 'text'")
    region = req.get("region")
    img_path = None
    root = None
    try:
        a11y.init()
        fw = next((w for w in STORE.windows.values() if w.focused), None)
        root = a11y.app_root_for_pid(fw.pid) if fw and fw.pid else None
        if root is None:
            roots = a11y.app_roots()
            root = roots[0] if roots else None
    except CuError:
        root = None
    if region or root is None:
        cap = shot.capture(region=region)
        img_path = cap["path"]
        tmp = None
    else:
        img_path = None
        tmp = None
    try:
        hits = ocr.find_text(needle, image_path=img_path,
                             atspi_root=root, region=region,
                             limit=int(req.get("limit", 10)))
    finally:
        if img_path:
            try:
                os.remove(img_path)
            except OSError:
                pass
    out = []
    for h in hits:
        el = STORE.add_synthetic(h["bbox"], h.get("name") or h.get("text", ""),
                                 source=h.get("via", "find_text"))
        out.append({"ref": el.ref, "bbox": h["bbox"], "via": h.get("via"),
                    "text": h.get("text", h.get("name", ""))})
    return {"matches": out}


def cmd_wait_for(req):
    import a11y
    role = req.get("role", "")
    name = req.get("name", "")
    event_type = req.get("event", "")
    timeout = float(req.get("timeout", 10))

    def pred(ev):
        if event_type and event_type not in ev.get("type", ""):
            return False
        if role and ev.get("source_role") != role:
            return False
        if name and name.lower() not in (ev.get("source_name") or "").lower():
            return False
        return bool(event_type or role or name)

    return a11y.wait_for(pred, timeout=timeout)


def cmd_wait_for_text(req):
    import a11y
    text = req.get("text", "")
    timeout = float(req.get("timeout", 10))
    if not text:
        raise InvalidArgs("missing 'text'")

    def pred(ev):
        if ev.get("type", "").startswith("object:text-changed") or \
                "accessible-name" in ev.get("type", ""):
            return text.lower() in (ev.get("source_name") or "").lower() or \
                text.lower() in (ev.get("data") or "").lower()
        return False

    return a11y.wait_for(pred, timeout=timeout,
                         topics=("object:text-changed",
                                 "object:property-change:accessible-name",
                                 "object:children-changed"))


# ---------- actions ----------

def _click_coords(req) -> tuple[int | None, int | None]:
    ref = req.get("ref")
    if ref:
        obj = STORE.get(ref)
        bbox = getattr(obj, "bbox", None) or getattr(obj, "geometry", None)
        if not bbox:
            raise CuError(f"ref {ref} has no geometry")
        return int(bbox["x"] + bbox["w"] // 2), int(bbox["y"] + bbox["h"] // 2)
    if req.get("x") is not None and req.get("y") is not None:
        return int(req["x"]), int(req["y"])
    return None, None


def cmd_click(req):
    """Click: ref → semantic action first when possible; coords fallback."""
    import inject
    ref = req.get("ref")
    method = req.get("method", "auto")   # auto | action | synthetic
    if ref and method in ("auto", "action"):
        try:
            _el, node = _resolve_el(ref)
        except CuError:
            if method == "action":
                raise
            node = None
        if node is not None:
            import a11y
            try:
                r = a11y.act(node, "press")
                return {"ref": ref, "method": r["method"],
                        "action": r["action"]}
            except CuError:
                if method == "action":
                    raise
                # auto → fall through to coordinates
    x, y = _click_coords(req)
    if x is None:
        raise InvalidArgs("click requires ref or x,y")
    inject.mouse_click(x, y, req.get("button", "left"),
                       int(req.get("clickCount", 1)))
    return {"x": x, "y": y, "method": "synthetic",
            "button": req.get("button", "left")}


def cmd_act(req):
    """Ref-only semantic action — no coordinates (poka-yoke)."""
    import a11y
    a = _args(req, "ref")
    verb = req.get("verb", "press")
    el, node = _resolve_el(a["ref"])
    if node is None:
        raise CuError(f"ref {a['ref']} is synthetic — no semantic action",
                      hint="use click with coordinates")
    return a11y.act(node, verb)


def cmd_type_text(req):
    import inject
    a = _args(req, "text")
    inject.type_text(a["text"], int(req.get("delayMs", 8)))
    return {"typed": len(a["text"]), "backend": inject.backend_name()}


def cmd_set_text(req):
    import a11y
    a = _args(req, "ref", "text")
    el, node = _resolve_el(a["ref"])
    if node is not None:
        try:
            return a11y.set_text(node, a["text"])
        except CuError:
            pass
    # fallback: focus + select-all + type
    import inject
    if el.bbox:
        x = el.bbox["x"] + el.bbox["w"] // 2
        y = el.bbox["y"] + el.bbox["h"] // 2
        inject.mouse_click(x, y)
    inject.keypress(["ctrl+a"])
    inject.keypress(["Delete"])
    inject.type_text(a["text"])
    return {"used": "fallback"}


def cmd_set_value(req):
    import a11y
    a = _args(req, "ref", "value")
    _el, node = _resolve_el(a["ref"])
    if node is None:
        raise CuError("synthetic ref has no Value interface")
    return a11y.set_value(node, float(a["value"]))


def cmd_select(req):
    import a11y
    a = _args(req, "ref", "index")
    _el, node = _resolve_el(a["ref"])
    if node is None:
        raise CuError("synthetic ref has no Selection interface")
    return a11y.select_child(node, int(a["index"]))


def cmd_keypress(req):
    import inject
    a = _args(req, "keys")
    inject.keypress(a["keys"])
    return {"keys": a["keys"], "backend": inject.backend_name()}


def cmd_scroll(req):
    import inject
    x, y = _click_coords(req)
    inject.scroll(x, y, int(req.get("scrollX", 0)), int(req.get("scrollY", 0)))
    return {"scrolled": True, "backend": inject.backend_name()}


def cmd_move_mouse(req):
    import inject
    a = _args(req)
    x, y = _click_coords(req)
    if x is None:
        raise InvalidArgs("move_mouse requires ref or x,y")
    inject.mouse_move(x, y)
    return {"x": x, "y": y}


def cmd_drag(req):
    import inject
    a = _args(req)
    if req.get("from") and req.get("to"):
        f = STORE.get(req["from"])
        t = STORE.get(req["to"])
        fb = getattr(f, "bbox", None) or getattr(f, "geometry", None)
        tb = getattr(t, "bbox", None) or getattr(t, "geometry", None)
        if not fb or not tb:
            raise CuError("drag refs lack geometry")
        x1, y1 = int(fb["x"] + fb["w"] / 2), int(fb["y"] + fb["h"] / 2)
        x2, y2 = int(tb["x"] + tb["w"] / 2), int(tb["y"] + tb["h"] / 2)
    else:
        x1 = int(req.get("x1")); y1 = int(req.get("y1"))
        x2 = int(req.get("x2")); y2 = int(req.get("y2"))
    inject.drag(x1, y1, x2, y2)
    return {"from": [x1, y1], "to": [x2, y2]}


def cmd_screenshot(req):
    import shot
    rect = _resolve_window_rect(req.get("window")) or req.get("region")
    cap = shot.capture(window_rect=rect)
    with open(cap["path"], "rb") as f:
        png = f.read()
    try:
        os.remove(cap["path"])
    except OSError:
        pass
    return {"stateId": uuid.uuid4().hex[:12],
            "pngBase64": base64.b64encode(png).decode("ascii"),
            "width": cap["width"], "height": cap["height"],
            "scale": cap.get("scale", 1.0), "backend": cap.get("backend", "")}


def cmd_computer_actions(req):
    import a11y
    import inject
    trace = []
    fail_fast = bool(req.get("failFast", False))
    for a in req.get("actions", []):
        t = a.get("type")
        try:
            if t == "click":
                r = cmd_click(a)
            elif t == "act":
                r = cmd_act(a)
            elif t == "type_text":
                r = cmd_type_text(a)
            elif t == "set_text":
                r = cmd_set_text(a)
            elif t == "set_value":
                r = cmd_set_value(a)
            elif t == "keypress":
                r = cmd_keypress(a)
            elif t == "scroll":
                r = cmd_scroll(a)
            elif t == "drag":
                r = cmd_drag(a)
            elif t == "move_mouse":
                r = cmd_move_mouse(a)
            elif t == "wait_for":
                r = cmd_wait_for(a)
            else:
                raise InvalidArgs(f"unknown action type {t}")
            trace.append({"type": t, "ok": True, "result": r})
        except Exception as e:
            trace.append({"type": t, "ok": False,
                          "error": to_error_dict(e)})
            if fail_fast:
                break
    return {"trace": trace, "stopped": fail_fast and not trace[-1]["ok"]}


# ---------- clipboard / notify / apps ----------

def cmd_clipboard_get(req):
    import clip
    what = req.get("what", "auto")
    out = {"targets": clip.targets()}
    if what in ("auto", "text"):
        try:
            out["text"] = clip.get_text()
        except Exception:
            pass
    if what in ("auto", "image"):
        try:
            out["image"] = clip.get_image()
        except Exception:
            pass
    if what in ("auto", "files"):
        try:
            out["files"] = clip.get_files()
        except Exception:
            pass
    return out


def cmd_clipboard_set(req):
    import clip
    if req.get("text") is not None:
        return clip.set_text(req["text"])
    if req.get("pngBase64") is not None:
        return clip.set_image(req["pngBase64"])
    if req.get("files") is not None:
        return clip.set_files(req["files"])
    raise InvalidArgs("clipboard_set needs text|pngBase64|files")


def cmd_notify(req):
    import notify
    a = _args(req, "title")
    return notify.send(a["title"], req.get("body", ""),
                       req.get("urgency", "normal"), req.get("icon", ""),
                       int(req.get("timeoutMs", 5000)))


def cmd_launch_app(req):
    import subprocess
    a = _args(req, "target")
    target = a["target"]
    # .desktop file id → gtk-launch; path → gio launch; else xdg-open/exec
    if target.endswith(".desktop") or "/" not in target:
        if util.which("gtk-launch") and not target.endswith(".desktop"):
            r = util.run(["gtk-launch", target], timeout=8)
            if r.returncode == 0:
                return {"launched": target, "via": "gtk-launch"}
        if util.which("gio") and (target.endswith(".desktop") or "/" in target):
            r = util.run(["gio", "launch", target], timeout=8)
            if r.returncode == 0:
                return {"launched": target, "via": "gio"}
    subprocess.Popen(["xdg-open", target] if "://" in target or
                     os.path.exists(target) else ["/bin/sh", "-c", target],
                     env=util.env_for_gui())
    return {"launched": target, "via": "exec"}


# ---------- system tools ----------

def cmd_identity(req):
    import syscore
    return syscore.identity()


def cmd_service(req):
    import syscore
    a = _args(req, "action")
    scope = req.get("scope", "system")
    tok = req.get("confirmToken", "")
    act, name = a["action"], req.get("name", "")
    if act == "list":
        return {"services": syscore.service_list(scope)}
    if not name:
        raise InvalidArgs("missing 'name'")
    if act == "get":
        return syscore.service_get(name, scope)
    fn = {"start": syscore.service_start, "stop": syscore.service_stop,
          "restart": syscore.service_restart, "enable": syscore.service_enable,
          "disable": syscore.service_disable}.get(act)
    if fn is None:
        raise InvalidArgs(f"unknown service action {act}")
    return fn(name, scope, tok)


def cmd_task(req):
    import syscore
    a = _args(req, "action")
    act = a["action"]
    tok = req.get("confirmToken", "")
    if act == "list":
        return syscore.task_list()
    if act == "add_timer":
        return syscore.task_add_timer(
            req["command"], req.get("onCalendar", ""),
            req.get("onActive", ""), req.get("name", "lcu-job"),
            bool(req.get("user", True)))
    if act == "add_cron":
        return syscore.task_add_cron(req["schedule"], req["command"])
    if act == "remove_cron":
        return syscore.task_remove_cron(req["match"], tok)
    raise InvalidArgs(f"unknown task action {act}")


def cmd_power(req):
    import syscore
    a = _args(req, "action")
    if a["action"] == "uptime":
        return syscore.uptime()
    if a["action"] == "inhibitors":
        return {"inhibitors": syscore.inhibit_list()}
    return syscore.power(a["action"], req.get("confirmToken", ""))


def cmd_journal(req):
    import syscore
    return {"entries": syscore.journal(
        unit=req.get("unit", ""), priority=req.get("priority", ""),
        since=req.get("since", ""), lines=int(req.get("lines", 50)),
        grep=req.get("grep", ""), boot=req.get("boot"),
        user=bool(req.get("user", False)))}


def cmd_dmesg(req):
    import syscore
    return {"lines": syscore.dmesg(int(req.get("lines", 50)),
                                   req.get("level", ""))}


def cmd_proc(req):
    import syscore
    a = _args(req, "action")
    if a["action"] == "list":
        return {"processes": syscore.proc_list(req.get("name", ""))}
    if a["action"] == "kill":
        return syscore.proc_kill(int(req["pid"]),
                                 int(req.get("signal", 15)),
                                 req.get("confirmToken", ""))
    raise InvalidArgs(f"unknown proc action {a['action']}")


def cmd_env(req):
    import syscore
    a = _args(req, "action")
    tok = req.get("confirmToken", "")
    if a["action"] == "list":
        return {"env": syscore.env_list()}
    if a["action"] == "get":
        return syscore.env_get(req["name"])
    if a["action"] == "set":
        return syscore.env_set(req["name"], req["value"],
                               req.get("persist", "session"), tok)
    if a["action"] == "delete":
        return syscore.env_delete(req["name"], req.get("persist", "session"),
                                  tok)
    raise InvalidArgs(f"unknown env action {a['action']}")


def cmd_audio(req):
    import syshw
    a = _args(req, "action")
    if a["action"] == "get":
        return syshw.audio_get()
    if a["action"] == "set":
        return syshw.audio_set(req.get("volume"), req.get("mute"))
    if a["action"] == "devices":
        return {"devices": syshw.audio_devices()}
    raise InvalidArgs(f"unknown audio action {a['action']}")


def cmd_net(req):
    import syshw
    a = _args(req, "action")
    tok = req.get("confirmToken", "")
    act = a["action"]
    if act == "adapters":
        return {"adapters": syshw.net_adapters()}
    if act == "status":
        return syshw.net_nm_status()
    if act == "wifi_list":
        return {"aps": syshw.net_wifi_list()}
    if act == "wifi_connect":
        return syshw.net_wifi_connect(req["ssid"], req.get("password", ""), tok)
    if act == "radio":
        return syshw.net_set_radio(req["radio"], bool(req.get("on", True)), tok)
    if act == "proxy":
        return syshw.net_proxy(req.get("mode", "none"), req.get("http", ""),
                               req.get("https", ""), req.get("socks", ""), tok)
    raise InvalidArgs(f"unknown net action {act}")


def cmd_display(req):
    import syshw
    a = _args(req, "action")
    tok = req.get("confirmToken", "")
    act = a["action"]
    if act == "brightness":
        return syshw.display_brightness()
    if act == "set_brightness":
        return syshw.display_set_brightness(int(req["percent"]), tok)
    if act == "list":
        return {"outputs": syshw.display_list()}
    if act == "night_light":
        return syshw.display_night_light(bool(req.get("on", True)),
                                         int(req.get("temp", 4000)), tok)
    raise InvalidArgs(f"unknown display action {act}")


def cmd_device(req):
    import syshw
    a = _args(req, "action")
    if a["action"] == "block":
        return {"devices": syshw.device_block()}
    if a["action"] == "usb":
        return {"devices": syshw.device_usb()}
    if a["action"] == "pci":
        return {"devices": syshw.device_pci()}
    if a["action"] == "printers":
        return {"printers": syshw.device_printers()}
    raise InvalidArgs(f"unknown device action {a['action']}")


def cmd_dnd(req):
    import notify
    return notify.dnd_state()


# ---------- dispatch ----------

COMMANDS = {
    "hello": cmd_hello, "ping": cmd_ping,
    "capabilities": cmd_capabilities, "probe": cmd_probe,
    "preflight": cmd_preflight,
    "list_windows": cmd_list_windows,
    "window_focus": cmd_window_focus, "window_close": cmd_window_close,
    "window_move": cmd_window_move, "window_state": cmd_window_state,
    "desktops": cmd_desktops, "switch_desktop": cmd_switch_desktop,
    "window_to_desktop": cmd_window_to_desktop,
    "cursor_pos": cmd_cursor_pos,
    "snapshot": cmd_snapshot, "screenshot": cmd_screenshot,
    "find_elements": cmd_find_elements, "find_text": cmd_find_text,
    "wait_for": cmd_wait_for, "wait_for_text": cmd_wait_for_text,
    "act": cmd_act, "click": cmd_click, "type_text": cmd_type_text,
    "set_text": cmd_set_text, "set_value": cmd_set_value,
    "select": cmd_select, "keypress": cmd_keypress, "scroll": cmd_scroll,
    "move_mouse": cmd_move_mouse, "drag": cmd_drag,
    "computer_actions": cmd_computer_actions,
    "clipboard_get": cmd_clipboard_get, "clipboard_set": cmd_clipboard_set,
    "notify": cmd_notify, "dnd": cmd_dnd, "launch_app": cmd_launch_app,
    "identity": cmd_identity, "service": cmd_service, "task": cmd_task,
    "power": cmd_power, "journal": cmd_journal, "dmesg": cmd_dmesg,
    "proc": cmd_proc, "env": cmd_env, "audio": cmd_audio,
    "net": cmd_net, "display": cmd_display, "device": cmd_device,
}


def handle(req: dict) -> dict:
    cmd = req.get("cmd")
    fn = COMMANDS.get(cmd)
    if fn is None:
        raise UnknownCommand(f"unknown cmd {cmd!r}",
                             hint="call `hello` for the command surface")
    return fn(req)


def main() -> int:
    # best-effort GUI env recovery for headless/SSH spawns
    env = util.env_for_gui()
    os.environ.update({k: v for k, v in env.items() if k not in os.environ})
    env_info = detect.detect_env()
    util.log(f"lcu bridge {VERSION} session={env_info.session_type} "
             f"compositor={env_info.compositor} atspi={env_info.has_atspi}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(
                {"id": None, "ok": False,
                 "error": InvalidArgs(f"bad json: {e}").to_dict()}) + "\n")
            sys.stdout.flush()
            continue
        rid = req.get("id")
        try:
            result = handle(req)
            sys.stdout.write(json.dumps({"id": rid, "ok": True,
                                         "result": result}) + "\n")
        except Exception as e:
            sys.stdout.write(json.dumps({"id": rid, "ok": False,
                                         "error": to_error_dict(e)}) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
