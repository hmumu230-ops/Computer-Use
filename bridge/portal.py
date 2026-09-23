"""xdg-desktop-portal D-Bus helpers (Screenshot / ScreenCast / RemoteDesktop).

Pure GLib/Gio — the bridge already requires python3-gi for AT-SPI, so this
adds zero dependencies. Portal calls are async (Request::Response signal);
`call_portal` wraps the pattern.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import uuid

from errors import CuError, PermissionRequired, UnsupportedPlatform

PORTAL = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"

_GIO = _GLIB = None


def _gio():
    global _GIO, _GLIB
    if _GIO is None:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        _GIO, _GLIB = Gio, GLib
    return _GIO, _GLIB


def portal_available() -> bool:
    try:
        Gio, _ = _gio()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        name = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "NameHasOwner",
            _GLIB_variant("(s)", (PORTAL,)), None,
            Gio.DBusCallFlags.NONE, -1, None)
        return bool(name and name.unpack()[0])
    except Exception:
        return False


def _GLIB_variant(sig, val):
    _, GLib = _gio()
    return GLib.Variant(sig, val)


def call_portal(iface: str, method: str, params: tuple,
                options: dict | None = None, timeout: int = 30) -> dict:
    """Call a portal Request-style method; block for Response; return results."""
    Gio, GLib = _gio()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    token = f"lcu{uuid.uuid4().hex[:10]}"
    sender = bus.get_unique_name()[1:].replace(".", "_")
    req_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    loop = GLib.MainLoop()
    out: dict = {}

    def on_resp(conn, s, path, ifc, sig, params_v, _):
        if path == req_path:
            r, res = params_v.unpack()[:2]
            out["resp"], out["res"] = r, res
            loop.quit()

    sub = bus.signal_subscribe(
        PORTAL, "org.freedesktop.portal.Request", "Response",
        None, None, Gio.DBusSignalFlags.NONE, on_resp, None)
    try:
        opts = dict(options or {})
        opts["handle_token"] = token
        variant_opts = {k: GLib.Variant(_guess_sig(v), v) for k, v in opts.items()}
        sig = _sig_for(method)
        bus.call_sync(
            PORTAL, DESKTOP_PATH, iface, method,
            GLib.Variant(sig, (*params, variant_opts)),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None)
        src = GLib.timeout_add_seconds(timeout, loop.quit)
        loop.run()
        GLib.source_remove(src)
    finally:
        bus.signal_unsubscribe(sub)
    if "resp" not in out:
        raise CuError(f"portal {method} timed out", hint="portal hung")
    if out["resp"] != 0:
        if out["resp"] == 1:
            raise PermissionRequired(
                f"portal {method} denied/cancelled", permission="portal")
        raise CuError(f"portal {method} failed: resp={out['resp']}")
    return dict(out.get("res") or {})


def _guess_sig(v):
    if isinstance(v, bool):
        return "b"
    if isinstance(v, int):
        return "u" if v >= 0 else "i"
    if isinstance(v, str):
        return "s"
    if isinstance(v, (list, tuple)):
        return "as"
    return "s"


def _sig_for(method: str) -> str:
    # (IN parent_window s, IN options a{sv}) etc.
    return {
        "Screenshot": "(sa{sv})",
        "PickColor": "(sa{sv})",
        "CreateSession": "(a{sv})",
        "SelectDevices": "(oa{sv})",
        "SelectSources": "(oa{sv})",
        "Start": "(osa{sv})",
        "OpenPipeWireRemote": "(oa{sv})",
    }.get(method, "(sa{sv})")


def screenshot_path(timeout: int = 30) -> str:
    """Portal Screenshot interactive:false → file URI → local path.
    First call may show a consent dialog (persisted thereafter); `setup`
    can pre-seed the PermissionStore for zero prompts."""
    res = call_portal("org.freedesktop.portal.Screenshot", "Screenshot",
                      ("",), {"interactive": False}, timeout=timeout)
    uri = res.get("uri")
    if not uri:
        raise CuError("portal screenshot returned no uri")
    return urllib.parse.unquote(urllib.parse.urlparse(uri).path)


def preseed_screenshot_permission() -> bool:
    """Grant the unsandboxed app_id "" persistent screenshot permission —
    zero-prompt provisioning for `setup`."""
    try:
        Gio, GLib = _gio()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            "org.freedesktop.impl.portal.PermissionStore",
            "/org/freedesktop/impl/portal/PermissionStore",
            "org.freedesktop.impl.portal.PermissionStore", "SetPermission",
            GLib.Variant("(sbsas)", ("screenshot", True, "screenshot", "",
                                     ["yes"])),
            None, Gio.DBusCallFlags.NONE, -1, None)
        return True
    except Exception:
        return False


# ---------- RemoteDesktop (GNOME/KDE Wayland input injection) ----------

RD_IFACE = "org.freedesktop.portal.RemoteDesktop"
RD_KEYBOARD = 1
RD_POINTER = 2
RD_TOUCHSCREEN = 4
RD_AXIS_VERTICAL = 0
RD_AXIS_HORIZONTAL = 1

_RD: dict | None = None       # {"session", "stream", "bus"}
_RD_BROKEN = False            # set once session creation/notify fails hard


def _rd_token_file() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "linux-computer-use", "rd_token.json")


def _rd_load_token() -> str | None:
    try:
        with open(_rd_token_file(), encoding="utf-8") as fh:
            return json.load(fh).get("restore_token")
    except Exception:
        return None


def _rd_save_token(token: str) -> None:
    try:
        path = _rd_token_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"restore_token": token}, fh)
    except Exception:
        pass


def rd_available() -> bool:
    """True when a RemoteDesktop portal backend plausibly exists.

    Only GNOME/KDE-class portals implement RemoteDesktop today;
    xdg-desktop-portal-wlr does not."""
    if _RD_BROKEN:
        return False
    return portal_available()


def rd_session(timeout: int = 60) -> dict:
    """Lazily establish one RemoteDesktop session for the bridge lifetime.

    First call may show a consent dialog; persist_mode=2 + a stored
    restore_token make subsequent calls (and later bridge runs) silent.
    """
    global _RD, _RD_BROKEN
    if _RD is not None:
        return _RD
    try:
        Gio, _ = _gio()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        sess_tok = f"lcus{uuid.uuid4().hex[:10]}"
        res = call_portal(RD_IFACE, "CreateSession", (),
                          {"session_handle_token": sess_tok}, timeout=timeout)
        session = res.get("session_handle")
        if not session:
            sender = bus.get_unique_name()[1:].replace(".", "_")
            session = (f"/org/freedesktop/portal/desktop/session/"
                       f"{sender}/{sess_tok}")
        call_portal(RD_IFACE, "SelectDevices", (session,),
                    {"types": RD_KEYBOARD | RD_POINTER}, timeout=timeout)
        src_opts: dict = {"types": 1, "multiple": False, "persist_mode": 2}
        token = _rd_load_token()
        if token:
            src_opts["restore_token"] = token
        call_portal(RD_IFACE, "SelectSources", (session,), src_opts,
                    timeout=timeout)
        res = call_portal(RD_IFACE, "Start", (session, ""), {}, timeout=timeout)
        streams = res.get("streams") or []
        if not streams:
            raise CuError("RemoteDesktop returned no streams",
                          hint="cannot place absolute pointer without a stream")
        if res.get("restore_token"):
            _rd_save_token(str(res["restore_token"]))
        _RD = {"session": session, "stream": int(streams[0][0]), "bus": bus}
        return _RD
    except Exception:
        _RD_BROKEN = True
        raise


def rd_close() -> None:
    global _RD
    if _RD is None:
        return
    try:
        Gio, _ = _gio()
        _RD["bus"].call_sync(PORTAL, _RD["session"],
                             "org.freedesktop.portal.Session", "Close",
                             None, None, Gio.DBusCallFlags.NONE, -1, None)
    except Exception:
        pass
    _RD = None


def _rd_call(method: str, sig: str, tail: tuple) -> None:
    global _RD_BROKEN
    try:
        rd = rd_session()
        Gio, GLib = _gio()
        rd["bus"].call_sync(
            PORTAL, DESKTOP_PATH, RD_IFACE, method,
            GLib.Variant(sig, (rd["session"], {}, *tail)),
            None, Gio.DBusCallFlags.NONE, -1, None)
    except CuError:
        raise
    except Exception as exc:
        _RD_BROKEN = True
        raise CuError(f"RemoteDesktop {method} failed: {exc}") from exc


def rd_pointer_move_abs(x: float, y: float) -> None:
    _rd_call("NotifyPointerMotionAbsolute", "(oa{sv}udd)",
             (rd_session()["stream"], float(x), float(y)))


def rd_pointer_button(button: int, down: bool) -> None:
    _rd_call("NotifyPointerButton", "(oa{sv}iu)",
             (int(button), 1 if down else 0))


def rd_axis_discrete(axis: int, steps: int) -> None:
    _rd_call("NotifyPointerAxisDiscrete", "(oa{sv}ui)",
             (int(axis), int(steps)))


def rd_keycode(keycode: int, down: bool) -> None:
    _rd_call("NotifyKeyboardKeycode", "(oa{sv}iu)",
             (int(keycode), 1 if down else 0))


def rd_keysym(keysym: int, down: bool) -> None:
    _rd_call("NotifyKeyboardKeysym", "(oa{sv}iu)",
             (int(keysym), 1 if down else 0))
