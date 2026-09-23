"""MCP server wrapping the linux-computer-use bridge.

Spawns `bridge/bridge.py` on the system python (PyGObject/`gi` lives there,
not in the uv-managed venv) and speaks newline-JSON over stdio.

CLI: `linux-computer-use-mcp [serve] | call <cmd> '<json>' | tools |
doctor | setup`.
"""
from __future__ import annotations

import argparse
import base64
import itertools
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

_HERE = Path(__file__).resolve().parent
_BRIDGE_DIR = _HERE.parent / "bridge"
_BRIDGE = _BRIDGE_DIR / "bridge.py"
if not _BRIDGE.exists():  # pragma: no cover
    raise RuntimeError(f"bridge.py not found at {_BRIDGE}")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_id_seq = itertools.count(1)


def _python() -> str:
    # System python carries python3-gi (AT-SPI). A venv python does not.
    for cand in ("/usr/bin/python3", "/usr/bin/python3.13",
                 "/usr/bin/python3.12", "/usr/bin/python3.11",
                 "/usr/bin/python3.10"):
        if Path(cand).exists():
            return cand
    return shutil.which("python3") or "python3"


def _spawn() -> subprocess.Popen:
    env = os.environ.copy()
    p = subprocess.Popen(
        [_python(), str(_BRIDGE)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
    threading.Thread(target=_drain_stderr, args=(p,), daemon=True).start()
    return p


def _drain_stderr(p: subprocess.Popen) -> None:
    try:
        for line in p.stderr or []:
            sys.stderr.write(f"[bridge] {line}")
    except Exception:
        pass


def bridge_call(cmd: str, args: dict[str, Any] | None = None) -> Any:
    """One NDJSON roundtrip. Re-spawns a dead bridge once."""
    global _proc
    with _lock:
        for attempt in range(2):
            if _proc is None or _proc.poll() is not None:
                _proc = _spawn()
            rid = str(next(_id_seq))
            req = {"id": rid, "cmd": cmd, **(args or {})}
            try:
                assert _proc.stdin and _proc.stdout
                _proc.stdin.write(json.dumps(req) + "\n")
                _proc.stdin.flush()
                line = _proc.stdout.readline()
            except (BrokenPipeError, OSError, AssertionError) as e:
                if attempt == 0:
                    _proc = None
                    continue
                raise RuntimeError(
                    json.dumps({"code": "BRIDGE_DEAD", "message": str(e),
                                "hint": "bridge subprocess died",
                                "retryable": True}))
            if not line:
                if attempt == 0:
                    _proc = None
                    continue
                raise RuntimeError(
                    json.dumps({"code": "BRIDGE_DEAD",
                                "message": "bridge closed stdout",
                                "hint": "check [bridge] stderr logs",
                                "retryable": True}))
            resp = json.loads(line)
            if not resp.get("ok"):
                err = resp.get("error")
                raise RuntimeError(json.dumps(err) if isinstance(err, dict)
                                   else json.dumps({"code": "INTERNAL",
                                                    "message": str(err)}))
            return resp.get("result")
    return None


def _structured(fn, *a, **kw):
    """Convert bridge RuntimeError(json-error) back into a dict result."""
    try:
        return fn(*a, **kw)
    except RuntimeError as e:
        try:
            return {"error": json.loads(str(e))}
        except Exception:
            return {"error": {"code": "INTERNAL", "message": str(e)}}


mcp = FastMCP("linux-computer-use")


# ---------- introspection ----------

@mcp.tool()
def capabilities() -> dict:
    """Per-domain support matrix for this session (session type, compositor,
    window/screenshot/input/clipboard/atspi/ocr/audio/network/services)."""
    return _structured(bridge_call, "capabilities")


@mcp.tool()
def doctor() -> dict:
    """Deep environment probe: init, compositor, groups, polkit matrix,
    sudo, virtualization — read-only."""
    return _structured(bridge_call, "probe")


# ---------- windows ----------

@mcp.tool()
def list_windows() -> dict:
    """Enumerate windows with fresh @wN refs (title/pid/geometry/focus)."""
    return _structured(bridge_call, "list_windows")


@mcp.tool()
def window_focus(ref: str) -> dict:
    return _structured(bridge_call, "window_focus", {"ref": ref})


@mcp.tool()
def window_close(ref: str, confirm_token: str = "") -> dict:
    return _structured(bridge_call, "window_close",
                       {"ref": ref, "confirmToken": confirm_token})


@mcp.tool()
def window_move(ref: str, x: int = -9999, y: int = -9999,
                w: int = -1, h: int = -1) -> dict:
    args: dict[str, Any] = {"ref": ref}
    if x != -9999:
        args["x"] = x
    if y != -9999:
        args["y"] = y
    if w > 0:
        args["w"] = w
    if h > 0:
        args["h"] = h
    return _structured(bridge_call, "window_move", args)


@mcp.tool()
def window_state(ref: str, state: str, on: bool = True) -> dict:
    """state: minimize|unminimize|maximize|unmaximize|above|fullscreen|sticky."""
    return _structured(bridge_call, "window_state",
                       {"ref": ref, "state": state, "on": on})


@mcp.tool()
def desktops() -> dict:
    return _structured(bridge_call, "desktops")


@mcp.tool()
def switch_desktop(index: int) -> dict:
    return _structured(bridge_call, "switch_desktop", {"index": index})


@mcp.tool()
def window_to_desktop(ref: str, index: int) -> dict:
    return _structured(bridge_call, "window_to_desktop",
                       {"ref": ref, "index": index})


@mcp.tool()
def cursor_pos() -> dict:
    return _structured(bridge_call, "cursor_pos")


# ---------- snapshot / find ----------

@mcp.tool()
def snapshot(window: str = "", tree: bool = True) -> list:
    """Screenshot + AT-SPI @eN elements + @wN windows + stateId/generation."""
    res = _structured(bridge_call, "snapshot",
                      {"window": window, "tree": tree})
    return _split_image(res)


@mcp.tool()
def screenshot(window: str = "") -> list:
    """PNG only (no tree walk). Empty window = full screen."""
    res = _structured(bridge_call, "screenshot",
                      {"window": window} if window else {})
    return _split_image(res)


@mcp.tool()
def find_elements(role: str = "", name: str = "",
                  states: list[str] | None = None,
                  pid: int = 0, limit: int = 50) -> dict:
    """Server-side AT-SPI search (Collection.get_matches). Returns fresh refs."""
    return _structured(bridge_call, "find_elements",
                       {"role": role, "name": name,
                        "states": states or [], "pid": pid, "limit": limit})


@mcp.tool()
def find_text(text: str, region: dict | None = None,
              limit: int = 10) -> dict:
    """Tiered text search: AT-SPI tree → tesseract → rapidocr.
    Hits become synthetic @eN refs usable with click/act."""
    args: dict[str, Any] = {"text": text, "limit": limit}
    if region:
        args["region"] = region
    return _structured(bridge_call, "find_text", args)


@mcp.tool()
def wait_for(role: str = "", name: str = "", event: str = "",
             timeout: float = 10.0) -> dict:
    """Event-driven wait on AT-SPI signals (object:state-changed:*,
    window:*, text-changed, children-changed...)."""
    return _structured(bridge_call, "wait_for",
                       {"role": role, "name": name, "event": event,
                        "timeout": timeout})


@mcp.tool()
def wait_for_text(text: str, timeout: float = 10.0) -> dict:
    return _structured(bridge_call, "wait_for_text",
                       {"text": text, "timeout": timeout})


# ---------- actions ----------

@mcp.tool()
def act(ref: str, verb: str = "press") -> dict:
    """Semantic action on an @eN — ref-only, no coordinates.
    verb: press|toggle|expand|collapse|select|showmenu|increment|
    decrement|focus. Falls back to index-0 default action."""
    return _structured(bridge_call, "act", {"ref": ref, "verb": verb})


@mcp.tool()
def click(ref: str = "", x: int = -1, y: int = -1,
          button: str = "left", click_count: int = 1,
          method: str = "auto") -> dict:
    """Click @eN/@wN or x,y. method=auto tries AT-SPI action first,
    synthetic pointer fallback; method=action|synthetic to force."""
    args: dict[str, Any] = {"button": button, "clickCount": click_count,
                            "method": method}
    if ref:
        args["ref"] = ref
    if x >= 0:
        args["x"] = x
    if y >= 0:
        args["y"] = y
    return _structured(bridge_call, "click", args)


@mcp.tool()
def type_text(text: str, delay_ms: int = 8) -> dict:
    return _structured(bridge_call, "type_text",
                       {"text": text, "delayMs": delay_ms})


@mcp.tool()
def set_text(ref: str, text: str) -> dict:
    """Replace an @eN's text via EditableText (verified); keyboard fallback."""
    return _structured(bridge_call, "set_text", {"ref": ref, "text": text})


@mcp.tool()
def set_value(ref: str, value: float) -> dict:
    """Slider/spin via AT-SPI Value interface (write + re-read verify)."""
    return _structured(bridge_call, "set_value",
                       {"ref": ref, "value": value})


@mcp.tool()
def select(ref: str, index: int) -> dict:
    """Select child index in a list/menu/tree via AT-SPI Selection."""
    return _structured(bridge_call, "select", {"ref": ref, "index": index})


@mcp.tool()
def keypress(keys: list[str]) -> dict:
    """['Enter'] | ['ctrl','a'] chord | sequence."""
    return _structured(bridge_call, "keypress", {"keys": keys})


@mcp.tool()
def scroll(ref: str = "", x: int = -1, y: int = -1,
           scroll_x: int = 0, scroll_y: int = 0) -> dict:
    args: dict[str, Any] = {"scrollX": scroll_x, "scrollY": scroll_y}
    if ref:
        args["ref"] = ref
    if x >= 0:
        args["x"] = x
    if y >= 0:
        args["y"] = y
    return _structured(bridge_call, "scroll", args)


@mcp.tool()
def move_mouse(ref: str = "", x: int = -1, y: int = -1) -> dict:
    args: dict[str, Any] = {}
    if ref:
        args["ref"] = ref
    if x >= 0:
        args["x"] = x
    if y >= 0:
        args["y"] = y
    return _structured(bridge_call, "move_mouse", args)


@mcp.tool()
def drag(from_ref: str = "", to_ref: str = "",
         x1: int = -1, y1: int = -1, x2: int = -1, y2: int = -1) -> dict:
    """Drag between refs or coords. Wayland: compositor may reject synthetic
    DnD — clipboard+Ctrl+V is the reliable fallback."""
    args: dict[str, Any] = {}
    if from_ref:
        args["from"] = from_ref
    if to_ref:
        args["to"] = to_ref
    for k, v in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
        if v >= 0:
            args[k] = v
    return _structured(bridge_call, "drag", args)


@mcp.tool()
def computer_actions(actions: list[dict], fail_fast: bool = False) -> dict:
    """Batch actions; per-action results; failFast stops on first error."""
    return _structured(bridge_call, "computer_actions",
                       {"actions": actions, "failFast": fail_fast})


# ---------- clipboard / notify / apps ----------

@mcp.tool()
def clipboard_get(what: str = "auto") -> dict:
    """what: auto|text|image|files. Reports available targets too."""
    return _structured(bridge_call, "clipboard_get", {"what": what})


@mcp.tool()
def clipboard_set(text: str = "", png_base64: str = "",
                  files: list[str] | None = None) -> dict:
    args: dict[str, Any] = {}
    if text:
        args["text"] = text
    if png_base64:
        args["pngBase64"] = png_base64
    if files:
        args["files"] = files
    return _structured(bridge_call, "clipboard_set", args)


@mcp.tool()
def notify(title: str, body: str = "", urgency: str = "normal",
           icon: str = "", timeout_ms: int = 5000) -> dict:
    return _structured(bridge_call, "notify",
                       {"title": title, "body": body, "urgency": urgency,
                        "icon": icon, "timeoutMs": timeout_ms})


@mcp.tool()
def launch_app(target: str) -> dict:
    """Launch by .desktop id, path, URI, or shell command."""
    return _structured(bridge_call, "launch_app", {"target": target})


# ---------- system ----------

@mcp.tool()
def identity() -> dict:
    return _structured(bridge_call, "identity")


@mcp.tool()
def service(action: str, name: str = "", scope: str = "system",
            confirm_token: str = "") -> dict:
    """action: list|get|start|stop|restart|enable|disable."""
    return _structured(bridge_call, "service",
                       {"action": action, "name": name, "scope": scope,
                        "confirmToken": confirm_token})


@mcp.tool()
def task(action: str, command: str = "", schedule: str = "",
         on_calendar: str = "", on_active: str = "", name: str = "lcu-job",
         match: str = "", user: bool = True,
         confirm_token: str = "") -> dict:
    """action: list|add_timer|add_cron|remove_cron."""
    return _structured(bridge_call, "task",
                       {"action": action, "command": command,
                        "schedule": schedule, "onCalendar": on_calendar,
                        "onActive": on_active, "name": name, "match": match,
                        "user": user, "confirmToken": confirm_token})


@mcp.tool()
def power(action: str, confirm_token: str = "") -> dict:
    """action: uptime|inhibitors|lock|suspend|hibernate|poweroff|reboot|halt|
    hybrid-sleep|suspend-then-hibernate. Destructive actions need a
    confirmToken from a first call's CONFIRM_REQUIRED response."""
    return _structured(bridge_call, "power",
                       {"action": action, "confirmToken": confirm_token})


@mcp.tool()
def journal(unit: str = "", priority: str = "", since: str = "",
            lines: int = 50, grep: str = "", boot: int = 0,
            user: bool = False) -> dict:
    args: dict[str, Any] = {"unit": unit, "priority": priority,
                            "since": since, "lines": lines, "grep": grep,
                            "user": user}
    if boot:
        args["boot"] = boot
    return _structured(bridge_call, "journal", args)


@mcp.tool()
def process(action: str, name: str = "", pid: int = 0, signal: int = 15,
            confirm_token: str = "") -> dict:
    """action: list|kill."""
    return _structured(bridge_call, "proc",
                       {"action": action, "name": name, "pid": pid,
                        "signal": signal, "confirmToken": confirm_token})


@mcp.tool()
def env(action: str, name: str = "", value: str = "",
        persist: str = "session", confirm_token: str = "") -> dict:
    """action: list|get|set|delete. persist: session|user."""
    return _structured(bridge_call, "env",
                       {"action": action, "name": name, "value": value,
                        "persist": persist, "confirmToken": confirm_token})


@mcp.tool()
def audio(action: str, volume: int = -1, mute: bool | None = None) -> dict:
    """action: get|set|devices. Backend wpctl→pactl→amixer."""
    args: dict[str, Any] = {"action": action}
    if volume >= 0:
        args["volume"] = volume
    if mute is not None:
        args["mute"] = mute
    return _structured(bridge_call, "audio", args)


@mcp.tool()
def network(action: str, ssid: str = "", password: str = "",
            radio: str = "", on: bool = True, mode: str = "none",
            http: str = "", https: str = "", socks: str = "",
            confirm_token: str = "") -> dict:
    """action: adapters|status|wifi_list|wifi_connect|radio|proxy."""
    return _structured(bridge_call, "net",
                       {"action": action, "ssid": ssid, "password": password,
                        "radio": radio, "on": on, "mode": mode,
                        "http": http, "https": https, "socks": socks,
                        "confirmToken": confirm_token})


@mcp.tool()
def display(action: str, percent: int = -1, on: bool = True,
            temp: int = 4000, confirm_token: str = "") -> dict:
    """action: brightness|set_brightness|list|night_light."""
    args: dict[str, Any] = {"action": action, "on": on, "temp": temp,
                            "confirmToken": confirm_token}
    if percent >= 0:
        args["percent"] = percent
    return _structured(bridge_call, "display", args)


@mcp.tool()
def device(action: str) -> dict:
    """action: block|usb|pci|printers."""
    return _structured(bridge_call, "device", {"action": action})


# ---------- helpers ----------

def _split_image(res):
    if isinstance(res, dict) and "error" in res:
        return res
    if not isinstance(res, dict):
        return res
    png_b64 = res.pop("pngBase64", "")
    parts: list = [res]
    if png_b64:
        try:
            parts.append(Image(data=base64.b64decode(png_b64), format="png"))
        except Exception:
            path = f"/tmp/lcu-screenshot-{res.get('stateId', 'x')}.png"
            try:
                Path(path).write_bytes(base64.b64decode(png_b64))
                res["imagePath"] = path
            except Exception:
                pass
    return parts


# ---------- CLI ----------

def _cli() -> int:
    ap = argparse.ArgumentParser(prog="linux-computer-use-mcp")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    c = sub.add_parser("call")
    c.add_argument("name")
    c.add_argument("args", nargs="?", default="{}")
    c.add_argument("--json", action="store_true")
    sub.add_parser("tools")
    sub.add_parser("doctor")
    sub.add_parser("setup")
    ns = ap.parse_args()

    if ns.cmd in (None, "serve"):
        mcp.run()
        return 0
    if ns.cmd == "call":
        try:
            args = json.loads(ns.args)
        except json.JSONDecodeError:
            args = {}
            for kv in ns.args.split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    args[k] = v
        out = _structured(bridge_call, ns.name, args)
        print(json.dumps(out, indent=2, default=str))
        return 0
    if ns.cmd == "tools":
        for t in sorted(_tool_names()):
            print(t)
        return 0
    if ns.cmd == "doctor":
        print(json.dumps(_structured(bridge_call, "probe"),
                         indent=2, default=str))
        return 0
    if ns.cmd == "setup":
        _setup()
        return 0
    return 0


def _tool_names() -> list[str]:
    import asyncio
    async def _names():
        tools = await mcp.get_tools()
        return list(tools.keys())
    try:
        return asyncio.run(_names())
    except Exception:
        return []


def _setup() -> None:
    """Distro-aware dependency instructions + zero-prompt provisioning."""
    res = _structured(bridge_call, "probe")
    print(json.dumps(res, indent=2, default=str))
    print("\n--- suggested packages ---")
    distro = ""
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("ID="):
                distro = line.split("=", 1)[1].strip('"')
    except Exception:
        pass
    pkgs = {
        "debian": "sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core "
                  "xdotool wmctrl scrot xclip wl-clipboard grim slurp "
                  "tesseract-ocr brightnessctl ddcutil libnotify-bin "
                  "yadotool ydotool",
        "ubuntu": "sudo apt install python3-gi gir1.2-atspi-2.0 at-spi2-core "
                  "xdotool wmctrl scrot xclip wl-clipboard grim slurp "
                  "tesseract-ocr brightnessctl ddcutil libnotify-bin ydotool",
        "fedora": "sudo dnf install python3-gobject at-spi2-core xdotool "
                  "wmctrl scrot xclip wl-clipboard grim slurp tesseract "
                  "brightnessctl ddcutil libnotify ydotool",
        "arch":   "sudo pacman -S python-gobject at-spi2-core xdotool wmctrl "
                  "scrot xclip wl-clipboard grim slurp tesseract "
                  "brightnessctl ddcutil libnotify ydotool",
        "opensuse": "sudo zypper install python3-gobject at-spi2-core "
                    "xdotool wmctrl scrot xclip wl-clipboard grim slurp "
                    "tesseract-ocr brightnessctl ddcutil libnotify-tools "
                    "ydotool",
    }
    key = next((k for k in pkgs if k in distro), "debian")
    print(f"# detected distro family: {distro or 'unknown'}")
    print(pkgs[key])
    print("\n# uinput access (Wayland input fallback):")
    print("sudo groupadd -f input && sudo usermod -aG input $USER")
    print("echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' | "
          "sudo tee /etc/udev/rules.d/80-lcu-uinput.rules")
    print("sudo udevadm control --reload && sudo udevadm trigger")
    print("\n# GNOME window management:")
    print("gnome-extensions install window-calls@domandoman.xyz")


def main() -> None:
    sys.exit(_cli())


if __name__ == "__main__":
    main()
