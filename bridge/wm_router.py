"""Window-management router: pick the backend for the detected compositor.

Uniform ops surface — every backend implements the same function names;
missing capability raises UnsupportedCompositor with a remediation hint.
"""
from __future__ import annotations

import detect
from errors import UnsupportedCompositor, StaleRef
from refs import RefStore, WindowRef

import wm_x11
import wm_kde
import wm_sway
import wm_hyprland
import wm_niri
import wm_wayfire
import wm_gnome
import wm_foreign

_BACKENDS = {
    "x11": wm_x11, "kde": wm_kde, "sway": wm_sway, "hyprland": wm_hyprland,
    "niri": wm_niri, "wayfire": wm_wayfire, "gnome": wm_gnome,
    "generic-wlroots": wm_foreign, "labwc": wm_foreign, "river": wm_foreign,
    "dwl": wm_foreign, "cosmic": wm_foreign,
}

_MOD = None
_MOD_NAME = ""


def backend(refresh: bool = False):
    """Active WM backend module."""
    global _MOD, _MOD_NAME
    if _MOD is not None and not refresh:
        return _MOD
    env = detect.detect_env(refresh=refresh)
    mod = _BACKENDS.get(env.compositor)
    if mod is None:
        # order: compositor module > foreign-toplevel > none
        if wm_foreign.available():
            mod = wm_foreign
        else:
            raise UnsupportedCompositor(
                f"no window-management backend for compositor "
                f"'{env.compositor}' (session={env.session_type})",
                compositor=env.compositor,
                hint="X11 needs wmctrl+xdotool; Wayland needs a compositor "
                     "IPC tool (kdotool/swaymsg/hyprctl/niri/wlrctl) or the "
                     "GNOME window-calls extension")
    if not mod.available():
        raise UnsupportedCompositor(
            f"{env.compositor} backend unavailable (required tools missing)",
            compositor=env.compositor)
    _MOD, _MOD_NAME = mod, env.compositor
    return mod


def list_windows(store: RefStore | None = None) -> list[dict]:
    mod = backend()
    raw = mod.list_windows()
    out = []
    for w in raw:
        item = dict(w)
        handle = item.pop("handle", None)
        if store is not None:
            wr = store.add_window(
                handle=handle, backend=_MOD_NAME,
                title=item.get("title", ""), pid=item.get("pid", 0),
                geometry=item.get("geometry"), focused=item.get("focused", False))
            item["ref"] = wr.ref
        item["backend"] = _MOD_NAME
        out.append(item)
    return out


def _resolve(store: RefStore, ref: str) -> WindowRef:
    obj = store.get(ref)
    if not isinstance(obj, WindowRef):
        raise StaleRef(f"{ref} is not a window ref")
    return obj


def _op(store: RefStore, ref: str, method: str, *a, **kw):
    w = _resolve(store, ref)
    mod = backend()
    fn = getattr(mod, method, None)
    if fn is None:
        raise UnsupportedCompositor(
            f"backend '{_MOD_NAME}' has no {method}", compositor=_MOD_NAME)
    return fn(w.handle, *a, **kw)


def focus(store: RefStore, ref: str):
    _op(store, ref, "focus")
    return {"focused": ref}


def close(store: RefStore, ref: str):
    _op(store, ref, "close")
    return {"closed": ref}


def move_resize(store: RefStore, ref: str, x=None, y=None, w=None, h=None):
    _op(store, ref, "move_resize", x=x, y=y, w=w, h=h)
    return {"moved": ref}


def set_state(store: RefStore, ref: str, state: str, on: bool = True):
    _op(store, ref, "set_state", state, on)
    return {"ref": ref, "state": state, "on": on}


def desktops() -> list[dict]:
    mod = backend()
    fn = getattr(mod, "desktops", None)
    return fn() if fn else []


def switch_desktop(idx: int):
    mod = backend()
    if not hasattr(mod, "switch_desktop"):
        raise UnsupportedCompositor(
            f"backend '{_MOD_NAME}' cannot switch desktops",
            compositor=_MOD_NAME)
    mod.switch_desktop(int(idx))
    return {"desktop": int(idx)}


def move_to_desktop(store: RefStore, ref: str, idx: int):
    _op(store, ref, "move_to_desktop", int(idx))
    return {"ref": ref, "desktop": int(idx)}


def cursor_pos() -> dict | None:
    mod = backend()
    fn = getattr(mod, "cursor_pos", None)
    return fn() if fn else None
