"""Desktop notifications — notify-send, D-Bus org.freedesktop.Notifications
fallback, per-DE DND detection."""
from __future__ import annotations

import detect
from errors import ToolNotFound
from util import run, run_out, which


def send(title: str, body: str = "", urgency: str = "normal",
         icon: str = "", timeout_ms: int = 5000) -> dict:
    if which("notify-send"):
        cmd = ["notify-send", "-u", urgency, "-t", str(int(timeout_ms))]
        if icon:
            cmd += ["-i", icon]
        cmd += [title, body]
        run(cmd, timeout=5)
        return {"sent": True, "via": "notify-send"}
    # raw D-Bus fallback
    out = run_out([
        "gdbus", "call", "--session",
        "-d", "org.freedesktop.Notifications",
        "-o", "/org/freedesktop/Notifications",
        "-m", "org.freedesktop.Notifications.Notify",
        "lcu", "0", icon or "", title, body, "[]", "{}",
        str(int(timeout_ms)),
    ], timeout=5)
    if out.strip():
        return {"sent": True, "via": "dbus", "reply": out.strip()}
    raise ToolNotFound("notify-send",
                       hint="install libnotify-bin or a notification daemon")


def dnd_state() -> dict:
    """Best-effort DND detection per DE."""
    env = detect.detect_env()
    d = env.desktop.upper()
    if "GNOME" in d:
        out = run_out(["gsettings", "get", "org.gnome.desktop.notifications",
                       "show-banners"], timeout=4)
        return {"dnd": "false" in out}
    if "KDE" in d:
        out = run_out(["qdbus", "org.freedesktop.Notifications",
                       "/org/freedesktop/Notifications",
                       "org.freedesktop.Notifications.Inhibited"], timeout=4) or \
            run_out(["qdbus6", "org.freedesktop.Notifications",
                     "/org/freedesktop/Notifications",
                     "org.freedesktop.Notifications.Inhibited"], timeout=4)
        return {"dnd": "true" in out.lower()}
    return {"dnd": None, "hint": "DND detection not implemented for this DE"}
