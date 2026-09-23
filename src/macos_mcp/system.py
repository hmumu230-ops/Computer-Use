"""System administration domains for macOS, all via shell commands.

Every function returns a dict and raises ``CuError`` on failure. Write /
privileged operations are marked ``dangerous`` by the tool layer which
routes them through ``safety.gate``.

Kept PyObjC-free so the module imports anywhere (useful for unit tests);
commands simply fail with ``TOOL_NOT_FOUND`` on non-macOS hosts.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from .errors import CuError, PermissionRequired, ToolNotFound


def _run(cmd: list[str], timeout: float = 15, check: bool = True) -> str:
    if shutil.which(cmd[0]) is None:
        raise ToolNotFound(cmd[0])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CuError(f"{' '.join(cmd)} timed out")
    if check and proc.returncode != 0:
        raise CuError(
            f"{' '.join(cmd)} exited {proc.returncode}",
            hint=proc.stderr.strip()[:300])
    return proc.stdout


def _kv_lines(text: str) -> Dict[str, str]:
    """Parse 'key: value' or 'key = value' line formats."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([^:=]+?)\s*[:=]\s*(.+?)\s*$", line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


# ---------------- probe / identity ----------------

def probe() -> Dict[str, Any]:
    """Environment probe: OS, arch, SIP, session context."""
    info: Dict[str, Any] = {"platform": "macos"}
    try:
        info["sw_vers"] = _kv_lines(_run(["sw_vers"], check=False))
    except CuError as exc:
        info["sw_vers_error"] = str(exc)
    try:
        info["arch"] = _run(["uname", "-m"], check=False).strip()
        info["kernel"] = _run(["uname", "-r"], check=False).strip()
    except CuError:
        pass
    try:
        info["sip"] = _run(["csrutil", "status"], check=False).strip()
    except CuError:
        info["sip"] = "unknown"
    info["session"] = {
        "user": _run(["id", "-un"], check=False).strip(),
        "uid": _run(["id", "-u"], check=False).strip(),
        "gui_session": bool(__import__("os").environ.get("TERM_PROGRAM")
                            or __import__("os").environ.get("SSH_TTY") is None),
    }
    info["tools"] = {
        t: bool(shutil.which(t))
        for t in ("pbcopy", "osascript", "launchctl", "pmset", "log",
                  "networksetup", "system_profiler", "caffeinate",
                  "brightness", "SwitchAudioSource")
    }
    return info


def identity() -> Dict[str, Any]:
    return {
        "user": _run(["id", "-un"], check=False).strip(),
        "uid": _run(["id", "-u"], check=False).strip(),
        "groups": _run(["id", "-Gn"], check=False).strip().split(),
        "hostname": _run(["hostname"], check=False).strip(),
        "uptime": _run(["uptime"], check=False).strip(),
    }


# ---------------- process ----------------

def process_list(name: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    out = _run(["ps", "-axo", "pid,comm,%cpu,%mem,args"], check=False)
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, comm, cpu, mem, args = parts
        if name and name.casefold() not in (comm + " " + args).casefold():
            continue
        procs.append({"pid": int(pid), "comm": comm,
                      "cpu": float(cpu), "mem": float(mem),
                      "args": args.strip()})
        if len(procs) >= limit:
            break
    return procs


def process_kill(pid: int, sig: str = "TERM") -> str:
    sig_num = {"TERM": "15", "KILL": "9", "HUP": "1", "INT": "2"}.get(
        sig.upper(), sig)
    _run(["kill", f"-{sig_num}", str(pid)])
    return f"sent SIG{sig.upper()} to pid {pid}"


# ---------------- service (launchd) ----------------

def service_list(filter: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    out = _run(["launchctl", "list"], check=False)
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[2]
        if filter and filter.casefold() not in label.casefold():
            continue
        rows.append({"pid": parts[0], "last_exit": parts[1],
                     "label": label})
        if len(rows) >= limit:
            break
    return rows


def service_control(action: str, label: str,
                    domain: str = "gui") -> str:
    """launchctl mutations: kickstart/enable/disable/bootout."""
    uid = _run(["id", "-u"], check=False).strip()
    target = f"{domain}/{uid}/{label}" if domain in ("gui", "user") \
        else f"{domain}/{label}"
    if action == "kickstart":
        _run(["launchctl", "kickstart", "-k", target])
    elif action in ("enable", "disable"):
        _run(["launchctl", action, target])
    elif action == "bootout":
        _run(["launchctl", "bootout", target])
    else:
        raise CuError(f"unknown service action '{action}'",
                      hint="kickstart|enable|disable|bootout")
    return f"{action} {label} ok"


# ---------------- audio ----------------

def audio_get() -> Dict[str, Any]:
    script = (
        'set v to output volume of (get volume settings)\n'
        'set m to output muted of (get volume settings)\n'
        'return (v as text) & "|" & (m as text)')
    raw = _run(["osascript", "-e", script]).strip()
    vol, _, muted = raw.partition("|")
    return {"volume": int(vol or 0), "muted": muted.strip() == "true"}


def audio_set(volume: int) -> str:
    volume = max(0, min(100, int(volume)))
    _run(["osascript", "-e", f"set volume output volume {volume}"])
    return f"volume={volume}"


def audio_mute(muted: bool = True) -> str:
    _run(["osascript", "-e",
          f"set volume output muted {'true' if muted else 'false'}"])
    return f"muted={muted}"


# ---------------- network ----------------

def network_status() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        ports = _run(["networksetup", "-listallhardwareports"], check=False)
        devices = re.findall(
            r"Hardware Port: (.+?)\nDevice: (\S+)", ports)
        out["interfaces"] = [{"port": p, "device": d} for p, d in devices]
    except CuError as exc:
        out["interfaces_error"] = str(exc)
    try:
        wifi = _run(["networksetup", "-getairportnetwork", "en0"],
                    check=False)
        out["wifi"] = wifi.strip()
    except CuError:
        pass
    try:
        out["proxy"] = _run(["scutil", "--proxy"], check=False).strip()
    except CuError:
        pass
    try:
        ips = _run(["ipconfig", "getsummary", "en0"], check=False)
        m = re.search(r"yiaddr\s*=\s*(\S+)", ips)
        if m:
            out["ip"] = m.group(1)
    except CuError:
        pass
    return out


def network_wifi(power: str) -> str:
    """power: 'on'|'off' — toggles the en0 airport interface."""
    if power not in ("on", "off"):
        raise CuError("power must be 'on' or 'off'")
    _run(["networksetup", "-setairportpower", "en0", power])
    return f"wifi {power}"


# ---------------- display / device ----------------

def display_list() -> List[Dict[str, Any]]:
    try:
        plist = _run(["system_profiler", "SPDisplaysDataType", "-json"])
        import json
        data = json.loads(plist)
        gpus = data.get("SPDisplaysDataType", [])
        out = []
        for gpu in gpus:
            for disp in gpu.get("spdisplays_ndrvs", []) or []:
                out.append({
                    "name": disp.get("_name", ""),
                    "resolution": disp.get("_spdisplays_resolution", ""),
                    "main": disp.get("spdisplays_main", "") == "spdisplays_yes",
                })
        return out
    except CuError:
        raise
    except Exception as exc:
        raise CuError("display enumeration failed", hint=str(exc))


def device_list(kind: str = "hardware") -> Any:
    types = {"hardware": "SPHardwareDataType", "usb": "SPUSBDataType",
             "bluetooth": "SPBluetoothDataType",
             "storage": "SPStorageDataType"}
    dtype = types.get(kind)
    if not dtype:
        raise CuError(f"unknown device kind '{kind}'",
                      hint="|".join(types))
    raw = _run(["system_profiler", dtype, "-json"], timeout=30)
    import json
    data = json.loads(raw)
    return data.get(dtype, data)


# ---------------- power ----------------

def power_status() -> Dict[str, Any]:
    return {
        "battery": _run(["pmset", "-g", "batt"], check=False).strip(),
        "assertions": _run(["pmset", "-g", "assertions"],
                          check=False).strip()[:2000],
    }


def power_action(action: str) -> str:
    """Dangerous power actions — tool layer must gate these."""
    if action == "sleep":
        _run(["pmset", "sleepnow"])
    elif action == "caffeinate":
        subprocess.Popen(["caffeinate", "-d", "-t", "3600"])
        return "caffeinate started (60min display-on)"
    else:
        raise CuError(f"unknown power action '{action}'",
                      hint="sleep|caffeinate")
    return f"{action} ok"


# ---------------- env ----------------

def env_get(name: str) -> Dict[str, str]:
    out = _run(["launchctl", "getenv", name], check=False).strip()
    return {name: out}


def env_set(name: str, value: str) -> str:
    _run(["launchctl", "setenv", name, value])
    return f"{name} set for GUI session"


def env_list() -> Dict[str, str]:
    # launchctl has no "list all" — read the user domain's export
    out = _run(["launchctl", "print", f"gui/{_run(['id','-u'],check=False).strip()}"],
               check=False, timeout=10)
    envs = {}
    m = re.search(r"environment = \{(.*?)\}", out, re.S)
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"\s*(\S+) => (.*)", line)
            if kv:
                envs[kv.group(1)] = kv.group(2).strip()
    return envs


# ---------------- event log ----------------

def log_query(predicate: str = "", last: str = "5m",
              limit: int = 100, style: str = "compact") -> List[str]:
    """`log show` — predicate e.g. 'process == "loginwindow"'."""
    cmd = ["log", "show", "--last", last, "--style", style]
    if predicate:
        cmd += ["--predicate", predicate]
    out = _run(cmd, timeout=30, check=False)
    lines = out.splitlines()
    return lines[-limit:] if len(lines) > limit else lines
