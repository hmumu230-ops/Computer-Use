"""Environment detection: session type, compositor, init, audio, toolkit flags.

Detection is cached per bridge lifetime; `detect_env(refresh=True)` re-probes.
Order follows the capability matrix: env sockets > XDG_CURRENT_DESKTOP >
D-Bus names > process scan.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field, asdict

from util import which, run_out


@dataclass
class Environment:
    session_type: str = "tty"          # x11 | wayland | tty
    desktop: str = ""                  # GNOME / KDE / sway / Hyprland / XFCE ...
    compositor: str = "unknown"        # x11 | kde | gnome | sway | hyprland |
                                       # niri | wayfire | labwc | river | dwl |
                                       # cosmic | generic-wlroots | unknown
    gnome_variant: str = ""            # "" | ext (window-calls) | unsafe | locked
    init: str = "unknown"              # systemd | openrc | runit | sysvinit | s6 | other
    systemd_version: int = 0
    audio_server: str = "none"         # pipewire | pulseaudio | alsa | none
    net_backend: str = "unknown"       # networkmanager | networkd | iwd | other
    virtualization: str = ""           # kvm/docker/... or ""
    in_container: bool = False
    has_atspi: bool = False
    tools: dict = field(default_factory=dict)   # name -> path

    def to_dict(self) -> dict:
        return asdict(self)


_ENV_OBJ: "Environment | None" = None

_TOOLS = [
    # window management / input / screenshot
    "wmctrl", "xdotool", "xprop", "xwininfo", "xrandr", "xset", "scrot",
    "import", "mss", "kdotool", "qdbus", "qdbus6", "swaymsg", "hyprctl",
    "niri", "wayfire", "wlrctl", "lswt", "grim", "slurp", "spectacle",
    "wtype", "ydotool", "dotool", "wl-find-cursor",
    # clipboard / notify
    "xclip", "xsel", "wl-copy", "wl-paste", "notify-send", "dragon",
    # portals / dbus
    "gdbus", "busctl", "dbus-send", "flatpak",
    # system
    "systemctl", "loginctl", "journalctl", "hostnamectl", "pkcheck",
    "nmcli", "ip", "resolvectl", "ethtool", "rfkill", "iwctl",
    "pactl", "wpctl", "pw-dump", "amixer",
    "brightnessctl", "ddcutil", "kscreen-doctor", "gdctl", "wlr-randr",
    "gammastep", "wlsunset", "redshift", "hyprsunset",
    "lsblk", "findmnt", "lscpu", "lsusb", "lspci", "udevadm", "lshw",
    "lpstat", "lpadmin", "lpinfo", "cancel",
    "crontab", "at", "atq", "systemd-run",
    "gio", "gtk-launch", "xdg-open", "xdg-mime", "xdg-settings",
    "gnome-extensions", "gsettings", "kwriteconfig6",
    "tesseract", "python3", "sudo", "pkexec", "doas", "pkexec",
    "gnome-screenshot",  # presence probed but deliberately unused
]


def _has_dbus_name(name: str, env: dict) -> bool:
    out = run_out(["busctl", "--user", "list"], timeout=3) or \
        run_out(["dbus-send", "--session", "--dest=org.freedesktop.DBus",
                 "--print-reply", "/org/freedesktop/DBus",
                 "org.freedesktop.DBus.ListNames"], timeout=3)
    return name in out


def _proc_running(name: str) -> bool:
    try:
        return subprocess.run(["pgrep", "-x", name], capture_output=True,
                              timeout=3).returncode == 0
    except Exception:
        return False


def _detect_init() -> tuple[str, int]:
    if os.path.isdir("/run/systemd/system"):
        init = "systemd"
    else:
        comm = run_out(["ps", "-p", "1", "-o", "comm="], timeout=3).strip()
        init = {"init": "sysvinit", "openrc-init": "openrc", "runit": "runit",
                "s6-svscan": "s6", "shepherd": "shepherd"}.get(comm, comm or "unknown")
    ver = 0
    if init == "systemd":
        out = run_out(["systemctl", "--version"], timeout=3)
        # "systemd 252 (252.30-1~deb12u2)"
        parts = out.split()
        if len(parts) >= 2 and parts[1].isdigit():
            ver = int(parts[1])
    return init, ver


def _detect_audio() -> str:
    if which("wpctl"):
        return "pipewire"
    if which("pactl"):
        info = run_out(["pactl", "info"], timeout=3)
        if "PipeWire" in info:
            return "pipewire"
        if "Server Name" in info:
            return "pulseaudio"
    if which("amixer"):
        return "alsa"
    return "none"


def _detect_net() -> str:
    if run_out(["systemctl", "is-active", "NetworkManager"], timeout=3).strip() == "active":
        return "networkmanager"
    if which("nmcli"):
        return "networkmanager"
    if run_out(["systemctl", "is-active", "systemd-networkd"], timeout=3).strip() == "active":
        return "networkd"
    if which("iwctl"):
        return "iwd"
    return "other"


def _detect_virt() -> tuple[str, bool]:
    out = run_out(["systemd-detect-virt"], timeout=3).strip()
    cont = run_out(["systemd-detect-virt", "--container"], timeout=3).strip()
    in_container = bool(cont and cont != "none") or os.path.exists("/.dockerenv") \
        or os.path.exists("/run/.containerenv")
    return ("" if out in ("none", "") else out), in_container


def _detect_compositor(env: dict, desktop: str) -> tuple[str, str]:
    """Return (compositor, gnome_variant)."""
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland", ""
    if env.get("SWAYSOCK"):
        return "sway", ""
    if env.get("NIRI_SOCKET"):
        return "niri", ""
    if env.get("WAYFIRE_SOCKET"):
        return "wayfire", ""
    d = desktop.upper()
    if "KDE" in d or _proc_running("kwin_wayland"):
        return "kde", ""
    if "GNOME" in d or _proc_running("gnome-shell"):
        if _has_dbus_name("org.gnome.Shell", env):
            # unsafe_mode probe + window-calls extension probe
            out = run_out(["gdbus", "call", "--session", "-d", "org.gnome.Shell",
                           "-o", "/org/gnome/Shell", "-m", "org.gnome.Shell.Eval",
                           "true"], timeout=4)
            if out.startswith("(true,"):
                return "gnome", "unsafe"
            ext = run_out(["busctl", "--user", "call", "org.gnome.Shell",
                           "/org/gnome/Shell/Extensions/Windows",
                           "org.gnome.Shell.Extensions.Windows", "List"],
                          timeout=4)
            if "DBus.Error" not in ext and ext.strip():
                return "gnome", "ext"
            return "gnome", "locked"
        return "gnome", "locked"
    if "COSMIC" in d or _proc_running("cosmic-comp"):
        return "cosmic", ""
    if "SWAY" in d:
        return "sway", ""
    for comp in ("wayfire", "labwc", "river", "dwl", "niri"):
        if _proc_running(comp):
            return comp, ""
    if env.get("WAYLAND_DISPLAY"):
        return "generic-wlroots", ""
    return "unknown", ""


def detect_env(refresh: bool = False) -> Environment:
    global _ENV_OBJ
    if _ENV_OBJ is not None and not refresh:
        return _ENV_OBJ
    e = Environment()
    env = os.environ
    e.session_type = env.get("XDG_SESSION_TYPE") or (
        "wayland" if env.get("WAYLAND_DISPLAY")
        else "x11" if env.get("DISPLAY") else "tty")
    desktop = env.get("XDG_CURRENT_DESKTOP") or env.get("XDG_SESSION_DESKTOP") \
        or env.get("DESKTOP_SESSION") or ""
    e.desktop = desktop.split(":")[-1]
    e.init, e.systemd_version = _detect_init()
    e.audio_server = _detect_audio()
    e.net_backend = _detect_net()
    e.virtualization, e.in_container = _detect_virt()
    for t in set(_TOOLS):
        p = which(t)
        if p:
            e.tools[t] = p
    try:
        import gi  # noqa: F401
        e.has_atspi = True
    except Exception:
        e.has_atspi = False
    if e.session_type == "x11":
        e.compositor = "x11"
    elif e.session_type == "wayland":
        e.compositor, e.gnome_variant = _detect_compositor(env, e.desktop)
    _ENV_OBJ = e
    return e


def capabilities() -> dict:
    """Per-domain support matrix for the `capabilities` tool."""
    e = detect_env()
    t = e.tools
    x11 = e.session_type == "x11"
    wl = e.session_type == "wayland"
    comp = e.compositor

    def ok(hint: str = "") -> dict:
        return {"status": "supported", "hint": hint}

    def no(hint: str) -> dict:
        return {"status": "unsupported", "hint": hint}

    def deg(hint: str) -> dict:
        return {"status": "degraded", "hint": hint}

    caps: dict = {"session": e.to_dict()}

    # window management
    if x11:
        caps["window"] = ok("wmctrl/xdotool EWMH") if "wmctrl" in t \
            else no("install wmctrl + xdotool")
    elif comp == "gnome" and e.gnome_variant == "locked":
        caps["window"] = no("GNOME Wayland: install window-calls extension "
                            "or enable unsafe_mode for window ops")
    elif comp in ("kde", "sway", "hyprland", "niri", "wayfire"):
        caps["window"] = ok(f"{comp} IPC")
    elif comp == "cosmic":
        caps["window"] = deg("cosmic toplevel protocol: no geometry")
    else:
        caps["window"] = deg("wlr-foreign-toplevel: list/focus/min/max/close "
                             "only, no geometry") if "lswt" in t or "wlrctl" in t \
            else no("no window-management backend found")

    # input
    if x11:
        caps["input"] = ok("xdotool") if "xdotool" in t else no("install xdotool")
    else:
        if "ydotool" in t or "dotool" in t:
            caps["input"] = ok("uinput (ydotool/dotool)")
        elif comp == "kde":
            caps["input"] = deg("KWin EIS or ydotool required for input")
        elif comp == "gnome":
            caps["input"] = deg("RemoteDesktop portal or ydotool required")
        else:
            caps["input"] = deg("wlr virtual-input or ydotool required")

    # screenshot
    if x11:
        caps["screenshot"] = ok("scrot") if "scrot" in t else no("install scrot")
    elif comp in ("sway", "hyprland", "labwc", "river", "wayfire") and "grim" in t:
        caps["screenshot"] = ok("grim (wlr-screencopy)")
    elif comp == "kde" and "spectacle" in t:
        caps["screenshot"] = ok("spectacle")
    elif "gdbus" in t or "busctl" in t:
        caps["screenshot"] = deg("portal Screenshot (first-run consent dialog)")
    else:
        caps["screenshot"] = no("no screenshot backend")

    # clipboard
    if x11:
        caps["clipboard"] = ok("xclip") if "xclip" in t or "xsel" in t \
            else no("install xclip or xsel")
    else:
        caps["clipboard"] = ok("wl-clipboard") if "wl-copy" in t \
            else no("install wl-clipboard")

    # accessibility
    caps["atspi"] = ok() if e.has_atspi else \
        no("python3-gi + gir1.2-atspi-2.0 not importable from system python")
    caps["ocr"] = ok("tesseract") if "tesseract" in t else \
        deg("install tesseract-ocr for OCR fallback")
    caps["notify"] = ok() if "notify-send" in t else no("install libnotify-bin")
    caps["audio"] = ok(e.audio_server) if e.audio_server != "none" else no("no audio server")
    caps["network"] = ok(e.net_backend) if e.net_backend != "unknown" else deg("limited")
    caps["services"] = ok(e.init) if e.init != "unknown" else no("unknown init")
    caps["cursor_position"] = ok() if (x11 or comp in ("kde", "hyprland")) \
        else no("compositor does not expose pointer position")

    return caps
