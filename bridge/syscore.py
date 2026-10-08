"""Core system domains: identity, services, timers/tasks, power, logs,
processes, env vars. JSON-first parsing with text fallbacks; every write op
declares its permission requirement and goes through safety.gate.
"""
from __future__ import annotations

import json
import os
import re

import detect
import safety
from errors import CuError, PermissionRequired, UnsupportedPlatform
from util import run, run_out, which


# ---------- identity ----------

def identity() -> dict:
    return {
        "user": run_out(["id", "-un"], timeout=3).strip(),
        "uid": os.getuid(),
        "groups": run_out(["id", "-Gn"], timeout=3).split(),
        "sudo_nopasswd": which("sudo") is not None and
            run(["sudo", "-n", "true"], timeout=3).returncode == 0,
        "session_active": run_out(
            ["loginctl", "show-session",
             os.environ.get("XDG_SESSION_ID", ""), "-p", "Active",
             "--value"], timeout=3).strip() == "yes" if which("loginctl") else None,
        "hostname": run_out(["hostnamectl", "--static"], timeout=3).strip()
            or run_out(["hostname"], timeout=3).strip(),
        "virt": detect.detect_env().virtualization,
        "container": detect.detect_env().in_container,
    }


# ---------- services ----------

def service_list(scope: str = "system") -> list[dict]:
    _need_systemd()
    base = ["systemctl"] + (["--user"] if scope == "user" else [])
    if detect.detect_env().systemd_version >= 250:
        out = run_out(base + ["list-units", "--type=service", "--all",
                              "-o", "json", "--no-pager"])
        try:
            arr = json.loads(out)
            return [{"name": u.get("unit"), "load": u.get("load"),
                     "active": u.get("active"), "sub": u.get("sub"),
                     "description": u.get("description")}
                    for u in arr]
        except Exception:
            pass
    out = run_out(base + ["list-units", "--type=service", "--all",
                          "--no-legend", "--plain", "--no-pager"])
    svcs = []
    for line in out.splitlines():
        p = line.split(None, 4)
        if len(p) >= 4:
            svcs.append({"name": p[0], "load": p[1], "active": p[2],
                         "sub": p[3], "description": p[4] if len(p) > 4 else ""})
    return svcs


def service_get(name: str, scope: str = "system") -> dict:
    _need_systemd()
    base = ["systemctl"] + (["--user"] if scope == "user" else [])
    keys = ["Id", "LoadState", "ActiveState", "SubState", "UnitFileState",
            "ExecMainStatus", "MainPID", "Description", "FragmentPath"]
    out = run_out(base + ["show", name,
                          "-p", ",".join(keys), "--no-pager"])
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k] = v
    return d


def _svc_action(verb: str, name: str, scope: str, confirm_token: str = "",
                extra: list[str] | None = None) -> dict:
    _need_systemd()
    dangerous = verb in ("stop", "restart", "disable", "mask", "kill")
    safety.gate(f"service:{verb}", {"unit": name, "scope": scope},
                dangerous, confirm_token)
    base = ["systemctl"] + (["--user"] if scope == "user" else [])
    cmd = base + [verb, name] + (extra or [])
    if getattr(os, "geteuid", lambda: 1)() != 0 and scope == "system" and which("sudo"):
        # polkit will prompt on desktop; sudo -n for NOPASSWD; else let
        # systemctl's own polkit path try (it returns a clean error)
        pass
    r = run(cmd, timeout=20)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if "authentication" in err.lower() or "access denied" in err.lower():
            raise PermissionRequired(
                f"systemctl {verb} {name}: {err}",
                permission="polkit:org.freedesktop.systemd1.manage-units",
                hint="run in an active desktop session, add a polkit rule, "
                     "or use sudo")
        raise CuError(f"systemctl {verb} failed: {err}")
    safety.audit(f"service:{verb}", {"unit": name}, "done")
    return {"unit": name, "verb": verb, "ok": True}


def service_start(name, scope="system", token=""):
    return _svc_action("start", name, scope, token)


def service_stop(name, scope="system", token=""):
    return _svc_action("stop", name, scope, token)


def service_restart(name, scope="system", token=""):
    return _svc_action("restart", name, scope, token)


def service_enable(name, scope="system", token=""):
    return _svc_action("enable", name, scope, token, ["--now"])


def service_disable(name, scope="system", token=""):
    return _svc_action("disable", name, scope, token, ["--now"])


def _need_systemd():
    if detect.detect_env().init != "systemd":
        raise UnsupportedPlatform(
            f"init system is '{detect.detect_env().init}', not systemd",
            hint="sysvinit: `service X start|status`; openrc: `rc-service`")


# ---------- timers / cron ----------

def task_list() -> dict:
    out: dict = {"timers": [], "cron": [], "at": []}
    if detect.detect_env().init == "systemd":
        raw = run_out(["systemctl", "list-timers", "--all", "--no-legend",
                       "--no-pager"], timeout=8)
        for line in raw.splitlines():
            p = line.split(None, 4)
            if len(p) >= 5:
                out["timers"].append({"next": f"{p[0]} {p[1]}",
                                      "unit": p[4].split()[0]})
        raw = run_out(["systemctl", "--user", "list-timers", "--all",
                       "--no-legend", "--no-pager"], timeout=8)
        for line in raw.splitlines():
            p = line.split(None, 4)
            if len(p) >= 5:
                out["timers"].append({"next": f"{p[0]} {p[1]}",
                                      "unit": p[4].split()[0],
                                      "scope": "user"})
    if which("crontab"):
        raw = run_out(["crontab", "-l"], timeout=5)
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out["cron"].append(line)
    if which("atq"):
        for line in run_out(["atq"], timeout=5).splitlines():
            p = line.split()
            if p:
                out["at"].append({"job": p[0], "when": " ".join(p[1:6])})
    return out


def task_add_timer(command: str, on_calendar: str = "",
                   on_active: str = "", name: str = "lcu-job",
                   user: bool = True) -> dict:
    _need_systemd()
    if not which("systemd-run"):
        raise UnsupportedPlatform("systemd-run missing")
    cmd = ["systemd-run"] + (["--user"] if user else [])
    cmd += ["--unit", name, "--description", f"lcu task {name}"]
    if on_calendar:
        cmd += ["--on-calendar", on_calendar]
    if on_active:
        cmd += ["--on-active", on_active]
    if not (on_calendar or on_active):
        raise CuError("timer needs on_calendar or on_active")
    import shlex
    cmd += ["--"] + shlex.split(command)
    r = run(cmd, timeout=15)
    if r.returncode != 0:
        raise CuError(f"systemd-run failed: {r.stderr.strip()}")
    safety.audit("task:timer", {"cmd": command, "unit": name}, "done")
    return {"unit": f"{name}.timer", "command": command}


def task_add_cron(schedule: str, command: str) -> dict:
    if not which("crontab"):
        raise UnsupportedPlatform("crontab missing",
                                  hint="install cron/cronie or use timers")
    # '%' must be escaped in cron command lines
    command = command.replace("%", "\\%")
    cur = run_out(["crontab", "-l"], timeout=5)
    new = (cur.rstrip() + "\n" if cur.strip() else "") + \
        f"{schedule} {command}\n"
    r = run(["crontab", "-"], input_text=new, timeout=5)
    if r.returncode != 0:
        raise CuError(f"crontab install failed: {r.stderr.strip()}")
    safety.audit("task:cron", {"schedule": schedule, "cmd": command}, "done")
    return {"installed": f"{schedule} {command}"}


def task_remove_cron(match: str, confirm_token: str = "") -> dict:
    safety.gate("task:remove_cron", {"match": match}, True, confirm_token)
    cur = run_out(["crontab", "-l"], timeout=5)
    kept = [l for l in cur.splitlines() if match not in l]
    r = run(["crontab", "-"], input_text="\n".join(kept) + "\n", timeout=5)
    if r.returncode != 0:
        raise CuError(f"crontab update failed: {r.stderr.strip()}")
    removed = len(cur.splitlines()) - len(kept)
    safety.audit("task:remove_cron", {"match": match, "removed": removed}, "done")
    return {"removed": removed}


# ---------- power ----------

_POWER_ACTIONS = {"poweroff", "reboot", "suspend", "hibernate",
                  "hybrid-sleep", "suspend-then-hibernate", "halt", "lock"}


def power(action: str, confirm_token: str = "") -> dict:
    if action not in _POWER_ACTIONS:
        raise CuError(f"unknown power action {action}",
                      hint=f"one of {sorted(_POWER_ACTIONS)}")
    if action == "lock":
        r = run(["loginctl", "lock-session"], timeout=8)
        if r.returncode != 0:
            raise CuError(f"lock failed: {r.stderr.strip()}")
        return {"action": action, "ok": True}
    safety.gate(f"power:{action}", {}, True, confirm_token)
    can = run_out(["busctl", "call", "org.freedesktop.login1",
                   "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                   _can_method(action), "b", "true"], timeout=6)
    if "challenge" in can or "na" == can.strip().strip('()s"'):
        raise PermissionRequired(
            f"{action} requires authorization", permission="polkit:login1",
            hint="active local session or sudo required")
    r = run(["systemctl", action], timeout=15)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "authentication" in err.lower() or "access denied" in err.lower():
            raise PermissionRequired(f"{action}: {err}",
                                     permission="polkit:login1")
        raise CuError(f"{action} failed: {err}")
    safety.audit(f"power:{action}", {}, "done")
    return {"action": action, "ok": True}


def _can_method(action: str) -> str:
    return {"poweroff": "CanPowerOff", "reboot": "CanReboot",
            "suspend": "CanSuspend", "hibernate": "CanHibernate",
            "hybrid-sleep": "CanHybridSleep",
            "suspend-then-hibernate": "CanSuspendThenHibernate",
            "halt": "CanHalt"}.get(action, "CanPowerOff")


def uptime() -> dict:
    return {"uptime": run_out(["uptime", "-p"], timeout=3).strip(),
            "since": run_out(["uptime", "-s"], timeout=3).strip(),
            "boot_id": run_out(["cat", "/proc/sys/kernel/random/boot_id"],
                               timeout=3).strip()}


def inhibit_list() -> list[dict]:
    out = run_out(["systemd-inhibit", "--list", "--no-legend"], timeout=5)
    rows = []
    for line in out.splitlines():
        p = line.split(None, 5)
        if len(p) >= 6:
            rows.append({"who": p[0], "uid": p[1], "pid": p[2],
                         "comm": p[3], "what": p[4], "why": p[5]})
    return rows


# ---------- logs ----------

def journal(unit: str = "", priority: str = "", since: str = "",
            lines: int = 50, grep: str = "", boot: int | None = None,
            user: bool = False) -> list[dict]:
    if not which("journalctl"):
        raise UnsupportedPlatform("journalctl missing")
    cmd = ["journalctl", "-o", "json", "--no-pager", "-n", str(int(lines))]
    if user:
        cmd.append("--user")
    if unit:
        cmd += ["-u", unit]
    if priority:
        cmd += ["-p", priority]
    if since:
        cmd += ["--since", since]
    if grep:
        cmd += ["-g", grep]
    if boot is not None:
        cmd += ["-b", str(boot)]
    r = run(cmd, timeout=15)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "permission" in err.lower():
            raise PermissionRequired(
                f"journalctl: {err}", permission="group:systemd-journal",
                hint="usermod -aG systemd-journal $USER or use sudo")
        raise CuError(f"journalctl failed: {err}")
    out = []
    for line in r.stdout.splitlines():
        try:
            e = json.loads(line)
            msg = e.get("MESSAGE", "")
            if isinstance(msg, list):  # binary MESSAGE → byte array
                msg = bytes(msg).decode("utf-8", "replace")
            out.append({
                "ts": e.get("__REALTIME_TIMESTAMP"),
                "unit": e.get("_SYSTEMD_UNIT") or e.get("UNIT", ""),
                "priority": e.get("PRIORITY"),
                "comm": e.get("_COMM", ""),
                "pid": e.get("_PID"),
                "message": msg,
            })
        except Exception:
            continue
    return out


def dmesg(lines: int = 50, level: str = "") -> list[str]:
    cmd = ["dmesg", "--level", level] if level else ["dmesg"]
    r = run(cmd + ["-T"], timeout=8)
    if r.returncode != 0:
        raise PermissionRequired(
            f"dmesg: {r.stderr.strip()}",
            permission="cap:CAP_SYSLOG",
            hint="kernel.dmesg_restrict=1 — needs root or CAP_SYSLOG")
    return r.stdout.splitlines()[-int(lines):]


# ---------- processes ----------

def proc_list(name: str = "", limit: int = 200) -> list[dict]:
    try:
        import psutil
        out = []
        for p in psutil.process_iter(
                ["pid", "name", "username", "status", "cpu_percent",
                 "memory_percent", "exe"]):
            i = p.info
            if name and name.lower() not in (i.get("name") or "").lower():
                continue
            out.append({k: i.get(k) for k in
                        ("pid", "name", "username", "status",
                         "cpu_percent", "memory_percent", "exe")})
            if len(out) >= limit:
                break
        return out
    except ImportError:
        pass
    out = run_out(["ps", "-eo", "pid,ppid,user,%cpu,%mem,stat,comm",
                   "--sort=-%cpu", "--no-headers"], timeout=6)
    rows = []
    for line in out.splitlines():
        p = line.split(None, 6)
        if len(p) >= 7:
            if name and name.lower() not in p[6].lower():
                continue
            rows.append({"pid": int(p[0]), "ppid": int(p[1]),
                         "user": p[2], "cpu": float(p[3]),
                         "mem": float(p[4]), "stat": p[5], "name": p[6]})
        if len(rows) >= limit:
            break
    return rows


def proc_kill(pid: int, signal: int = 15, confirm_token: str = "") -> dict:
    safety.gate("proc:kill", {"pid": pid, "sig": signal}, True, confirm_token)
    r = run(["kill", f"-{int(signal)}", str(int(pid))], timeout=5)
    if r.returncode != 0:
        raise CuError(f"kill failed: {r.stderr.strip()}")
    safety.audit("proc:kill", {"pid": pid, "sig": signal}, "done")
    return {"pid": pid, "signal": signal, "ok": True}


# ---------- environment ----------

def env_get(name: str) -> dict:
    return {"name": name, "value": os.environ.get(name)}


def env_list() -> dict:
    return dict(os.environ)


def env_set(name: str, value: str, persist: str = "session",
            confirm_token: str = "") -> dict:
    """persist: session (this bridge+children) | user (systemd --user +
    environment.d) — machine scope needs root and edits /etc/environment."""
    if persist == "user":
        safety.gate("env:set", {"name": name, "persist": persist},
                    True, confirm_token)
        r = run(["systemctl", "--user", "set-environment",
                 f"{name}={value}"], timeout=5)
        ok = r.returncode == 0
        # environment.d for next login
        try:
            d = os.path.expanduser("~/.config/environment.d")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "90-lcu.conf")
            lines = {}
            if os.path.exists(path):
                with open(path) as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            lines[k] = v
            lines[name] = value
            with open(path, "w") as f:
                for k, v in lines.items():
                    f.write(f"{k}={v}\n")
        except Exception:
            pass
        safety.audit("env:set", {"name": name, "persist": "user"}, "done")
        return {"name": name, "persist": "user", "systemd": ok}
    os.environ[name] = value
    return {"name": name, "persist": "session"}


def env_delete(name: str, persist: str = "session",
               confirm_token: str = "") -> dict:
    if persist == "user":
        safety.gate("env:delete", {"name": name}, True, confirm_token)
        run(["systemctl", "--user", "set-environment", f"{name}="], timeout=5)
        path = os.path.expanduser("~/.config/environment.d/90-lcu.conf")
        try:
            if os.path.exists(path):
                lines = {}
                with open(path) as f:
                    for line in f:
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            lines[k] = v
                lines.pop(name, None)
                with open(path, "w") as f:
                    for k, v in lines.items():
                        f.write(f"{k}={v}\n")
        except Exception:
            pass
        safety.audit("env:delete", {"name": name}, "done")
        return {"name": name, "deleted": True, "persist": "user"}
    os.environ.pop(name, None)
    return {"name": name, "deleted": True, "persist": "session"}
