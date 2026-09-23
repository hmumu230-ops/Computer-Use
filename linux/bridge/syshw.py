"""Hardware domains: audio, network, display, devices.

JSON-first parsing where the tool supports it; terse/text parsers otherwise.
Write ops declare permission requirements.
"""
from __future__ import annotations

import json
import os
import re

import detect
import safety
from errors import CuError, UnsupportedPlatform, ToolNotFound
from util import run, run_out, which


# ---------- audio ----------

def _audio_backend() -> str:
    env = detect.detect_env()
    if env.audio_server == "pipewire" and which("wpctl"):
        return "wpctl"
    if which("pactl"):
        return "pactl"
    if which("amixer"):
        return "amixer"
    raise UnsupportedPlatform("no audio server", hint="pipewire/pulseaudio/alsa")


def audio_get() -> dict:
    be = _audio_backend()
    if be == "wpctl":
        vol = run_out(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=4)
        m = re.search(r"Volume:\s*([\d.]+)", vol)
        muted = "MUTED" in vol
        return {"backend": "wpctl",
                "volume": float(m.group(1)) * 100 if m else None,
                "muted": muted}
    if be == "pactl":
        vol = run_out(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=4)
        m = re.search(r"(\d+)%", vol)
        mut = run_out(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=4)
        return {"backend": "pactl",
                "volume": int(m.group(1)) if m else None,
                "muted": "yes" in mut.lower()}
    out = run_out(["amixer", "-D", "default", "sget", "Master"], timeout=4)
    m = re.search(r"\[(\d+)%\]", out)
    return {"backend": "amixer",
            "volume": int(m.group(1)) if m else None,
            "muted": "[off]" in out}


def audio_set(volume: int | None = None, mute: bool | None = None) -> dict:
    be = _audio_backend()
    if be == "wpctl":
        if volume is not None:
            run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                 f"{int(volume)}%"], timeout=4)
        if mute is not None:
            run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@",
                 "1" if mute else "0"], timeout=4)
    elif be == "pactl":
        if volume is not None:
            run(["pactl", "set-sink-volume", "@DEFAULT_SINK@",
                 f"{int(volume)}%"], timeout=4)
        if mute is not None:
            run(["pactl", "set-sink-mute", "@DEFAULT_SINK@",
                 "1" if mute else "0"], timeout=4)
    else:
        if volume is not None:
            run(["amixer", "-D", "default", "sset", "Master",
                 f"{int(volume)}%"], timeout=4)
        if mute is not None:
            run(["amixer", "-D", "default", "sset", "Master",
                 "mute" if mute else "unmute"], timeout=4)
    safety.audit("audio:set", {"volume": volume, "mute": mute}, "done")
    return {"ok": True, "backend": be}


def audio_devices() -> list[dict]:
    be = _audio_backend()
    if be == "wpctl":
        try:
            out = run_out(["pw-dump"], timeout=6)
            arr = json.loads(out)
            return [{"id": o.get("id"),
                     "name": (o.get("info", {}).get("props", {}) or {}).get(
                         "node.name"),
                     "desc": (o.get("info", {}).get("props", {}) or {}).get(
                         "node.description")}
                    for o in arr if isinstance(o, dict)
                    and o.get("type") == "PipeWire:Interface:Node"]
        except Exception:
            pass
    if be == "pactl":
        out = run_out(["pactl", "list", "short", "sinks"], timeout=4)
        return [{"index": p[0], "name": p[1]}
                for p in (l.split("\t") for l in out.splitlines()) if len(p) >= 2]
    out = run_out(["amixer", "-D", "default", "scontrols"], timeout=4)
    return [{"name": l} for l in out.splitlines() if l.strip()]


# ---------- network ----------

def net_adapters() -> list[dict]:
    if which("ip"):
        out = run_out(["ip", "-j", "addr", "show"], timeout=5)
        try:
            arr = json.loads(out)
            return [{"name": a.get("ifname"), "state": a.get("operstate"),
                     "mac": a.get("address"),
                     "addrs": [f"{i.get('local')}/{i.get('prefixlen')}"
                               for i in a.get("addr_info", [])]}
                    for a in arr]
        except Exception:
            pass
    return []


def net_nm_status() -> dict:
    if not which("nmcli"):
        return {"backend": detect.detect_env().net_backend}
    out = run_out(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION",
                   "device", "status"], timeout=6)
    devs = []
    for line in out.splitlines():
        p = _nm_split(line)
        if len(p) >= 4:
            devs.append({"device": p[0], "type": p[1], "state": p[2],
                         "connection": p[3]})
    return {"devices": devs}


def _nm_split(line: str) -> list[str]:
    """nmcli -t escapes colons in values as \\: — split on unescaped colons."""
    return re.split(r"(?<!\\):", line)


def net_wifi_list() -> list[dict]:
    if not which("nmcli"):
        raise ToolNotFound("nmcli", hint="install network-manager")
    out = run_out(["nmcli", "-t", "-f",
                   "SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,SECURITY",
                   "device", "wifi", "list"], timeout=15)
    aps = []
    for line in out.splitlines():
        p = _nm_split(line)
        if len(p) >= 7 and p[0]:
            aps.append({"ssid": p[0], "bssid": p[1], "chan": p[2],
                        "freq": p[3], "rate": p[4],
                        "signal": int(p[5]) if p[5].isdigit() else 0,
                        "security": p[6]})
    return aps


def net_wifi_connect(ssid: str, password: str = "",
                     confirm_token: str = "") -> dict:
    safety.gate("net:wifi_connect", {"ssid": ssid}, True, confirm_token)
    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd += ["password", password]
    r = run(cmd, timeout=30)
    if r.returncode != 0:
        raise CuError(f"wifi connect failed: {r.stderr.strip()}")
    safety.audit("net:wifi_connect", {"ssid": ssid}, "done")
    return {"connected": ssid}


def net_set_radio(radio: str, on: bool, confirm_token: str = "") -> dict:
    safety.gate("net:radio", {"radio": radio, "on": on}, True, confirm_token)
    if radio in ("wifi", "wwan"):
        r = run(["nmcli", "radio", radio, "on" if on else "off"], timeout=8)
    else:
        r = run(["rfkill", "unblock" if on else "block", radio], timeout=8)
    if r.returncode != 0:
        raise CuError(f"radio {radio} failed: {r.stderr.strip()}")
    safety.audit("net:radio", {"radio": radio, "on": on}, "done")
    return {"radio": radio, "on": on}


def net_proxy(mode: str = "none", http: str = "", https: str = "",
              socks: str = "", confirm_token: str = "") -> dict:
    """mode: none|manual|auto(PAC url in http). GNOME gsettings + env fallback."""
    safety.gate("net:proxy", {"mode": mode}, True, confirm_token)
    env = detect.detect_env()
    if "GNOME" in env.desktop.upper() and which("gsettings"):
        run(["gsettings", "set", "org.gnome.system.proxy", "mode",
             f"'{mode}'"], timeout=5)
        if mode == "manual":
            for key, val in (("http", http), ("https", https),
                             ("socks", socks)):
                if val:
                    host, _, port = val.partition(":")
                    run(["gsettings", "set", f"org.gnome.system.proxy.{key}",
                         "host", f"'{host}'"], timeout=5)
                    if port:
                        run(["gsettings", "set",
                             f"org.gnome.system.proxy.{key}", "port",
                             port], timeout=5)
        safety.audit("net:proxy", {"mode": mode}, "done")
        return {"mode": mode, "via": "gsettings"}
    # env fallback — session scope
    for var, val in (("http_proxy", http), ("https_proxy", https),
                     ("all_proxy", socks)):
        if val:
            os.environ[var] = f"http://{val}" if "://" not in val else val
        else:
            os.environ.pop(var, None)
    safety.audit("net:proxy", {"mode": mode, "via": "env"}, "done")
    return {"mode": mode, "via": "env"}


# ---------- display ----------

def display_brightness() -> dict:
    if which("brightnessctl"):
        out = run_out(["brightnessctl", "-m"], timeout=4)
        p = out.split(",")
        if len(p) >= 5:
            return {"device": p[0], "value": int(p[2]),
                    "percent": int(p[3].rstrip("%")), "max": int(p[4])}
    # sysfs fallback
    base = "/sys/class/backlight"
    try:
        dev = os.listdir(base)[0]
        with open(f"{base}/{dev}/brightness") as f:
            cur = int(f.read().strip())
        with open(f"{base}/{dev}/max_brightness") as f:
            mx = int(f.read().strip())
        return {"device": dev, "value": cur,
                "percent": round(cur / mx * 100), "max": mx}
    except Exception:
        raise UnsupportedPlatform(
            "no backlight control",
            hint="brightnessctl missing and /sys/class/backlight empty; "
                 "external monitors need ddcutil")


def display_set_brightness(percent: int, confirm_token: str = "") -> dict:
    safety.gate("display:brightness", {"pct": percent}, False, confirm_token)
    if which("brightnessctl"):
        r = run(["brightnessctl", "set", f"{int(percent)}%"], timeout=5)
        if r.returncode != 0:
            raise CuError(f"brightnessctl: {r.stderr.strip()}",
                          hint="needs active session (uaccess) or i2c group")
        return {"percent": int(percent)}
    raise ToolNotFound("brightnessctl")


def display_list() -> list[dict]:
    env = detect.detect_env()
    if env.session_type == "x11" and which("xrandr"):
        out = run_out(["xrandr"], timeout=5)
        outs = []
        for line in out.splitlines():
            m = re.match(r"(\S+)\s+(connected|disconnected)\s+(.*?)(\d+x\d+\+\d+\+\d+)?", line)
            if m:
                outs.append({"name": m.group(1),
                             "connected": m.group(2) == "connected",
                             "primary": "primary" in line,
                             "geometry": m.group(4) or ""})
        return outs
    if which("wlr-randr"):
        try:
            return json.loads(run_out(["wlr-randr", "--json"], timeout=5))
        except Exception:
            pass
    if which("hyprctl"):
        try:
            return json.loads(run_out(["hyprctl", "monitors", "-j"], timeout=5))
        except Exception:
            pass
    if which("kscreen-doctor"):
        try:
            return json.loads(run_out(["kscreen-doctor", "-j"], timeout=5))
        except Exception:
            pass
    return []


def display_night_light(enabled: bool, temp: int = 4000,
                        confirm_token: str = "") -> dict:
    env = detect.detect_env()
    d = env.desktop.upper()
    if "GNOME" in d and which("gsettings"):
        run(["gsettings", "set",
             "org.gnome.settings-daemon.plugins.color",
             "night-light-enabled", "true" if enabled else "false"], timeout=5)
        if enabled:
            run(["gsettings", "set",
                 "org.gnome.settings-daemon.plugins.color",
                 "night-light-temperature", str(int(temp))], timeout=5)
        return {"night_light": enabled, "temp": temp, "via": "gsettings"}
    if "KDE" in d and which("kwriteconfig6"):
        run(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor",
             "--key", "Active", "true" if enabled else "false"], timeout=5)
        if enabled:
            run(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor",
                 "--key", "NightTemperature", str(int(temp))], timeout=5)
        # kwriteconfig does NOT notify KWin — reconfigure required
        run_out(["qdbus6", "org.kde.KWin", "/KWin",
                 "org.kde.KWin.reconfigure"], timeout=5) or \
            run_out(["qdbus", "org.kde.KWin", "/KWin",
                     "org.kde.KWin.reconfigure"], timeout=5)
        return {"night_light": enabled, "temp": temp, "via": "kwinrc"}
    for tool, args in (("gammastep", ["-O", str(int(temp))]),
                       ("wlsunset", ["-T", str(int(temp))]),
                       ("redshift", ["-O", str(int(temp))])):
        if which(tool):
            import subprocess
            subprocess.Popen([tool, *args] if enabled else [tool, "-x"])
            return {"night_light": enabled, "temp": temp, "via": tool}
    raise UnsupportedPlatform("no night-light backend",
                              hint="GNOME gsettings / KDE kwriteconfig6 / "
                                   "gammastep / wlsunset / redshift")


# ---------- devices ----------

def device_block() -> list[dict]:
    out = run_out(["lsblk", "-J", "-o",
                   "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL"], timeout=6)
    try:
        return json.loads(out).get("blockdevices", [])
    except Exception:
        return []


def device_usb() -> list[dict]:
    out = run_out(["lsusb"], timeout=6)
    devs = []
    for line in out.splitlines():
        m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-f:]+) (.*)", line)
        if m:
            devs.append({"bus": m.group(1), "device": m.group(2),
                         "id": m.group(3), "name": m.group(4).strip()})
    return devs


def device_pci() -> list[dict]:
    out = run_out(["lspci", "-nnk"], timeout=6)
    devs = []
    cur = None
    for line in out.splitlines():
        if not line.startswith("\t"):
            m = re.match(r"([0-9a-f:.]+)\s+(.*?):\s+(.*)", line)
            if m:
                cur = {"slot": m.group(1), "class": m.group(2),
                       "name": m.group(3), "driver": ""}
                devs.append(cur)
        elif cur is not None and "Kernel driver in use:" in line:
            cur["driver"] = line.split(":")[-1].strip()
    return devs


def device_printers() -> list[dict]:
    out = run_out(["lpstat", "-t"], timeout=6)
    printers = []
    for line in out.splitlines():
        if line.startswith("printer "):
            m = re.match(r"printer (\S+)(.*)", line)
            if m:
                printers.append({"name": m.group(1),
                                 "info": m.group(2).strip()})
    return printers
