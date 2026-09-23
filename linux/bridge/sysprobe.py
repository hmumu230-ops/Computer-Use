"""System probe: init, session, permissions matrix — read-only discovery."""
from __future__ import annotations

import os

import detect
from util import run, run_out, which


def probe() -> dict:
    env = detect.detect_env()
    groups = run_out(["id", "-Gn"], timeout=3).split()
    sudo_rc = run(["sudo", "-n", "true"], timeout=3).returncode \
        if which("sudo") else -1
    polkit = {}
    for action in ("org.freedesktop.login1.power-off",
                   "org.freedesktop.login1.suspend",
                   "org.freedesktop.login1.manage-inhibitors",
                   "org.freedesktop.systemd1.manage-units",
                   "org.freedesktop.NetworkManager.settings.modify.system"):
        rc = _pkcheck(action)
        polkit[action.split(".")[-1]] = rc
    return {
        "env": env.to_dict(),
        "user": {
            "name": run_out(["id", "-un"], timeout=3).strip(),
            "uid": os.getuid(),
            "groups": groups,
            "sudo_nopasswd": sudo_rc == 0,
        },
        "polkit": polkit,
        "session": {
            "id": os.environ.get("XDG_SESSION_ID", ""),
            "active": _session_prop("Active"),
            "remote": _session_prop("Remote"),
        },
    }


def _session_prop(prop: str) -> str:
    sid = os.environ.get("XDG_SESSION_ID", "")
    if not sid or not which("loginctl"):
        return ""
    return run_out(["loginctl", "show-session", sid, "-p", prop, "--value"],
                   timeout=3).strip()


def _pkcheck(action: str) -> str:
    """0=authorized 1=denied 2=error 3=needs-auth — string for JSON."""
    if not which("pkcheck"):
        return "unavailable"
    try:
        rc = run(["pkcheck", "--action-id", action, "--process",
                  str(os.getpid())], timeout=4).returncode
        return {0: "yes", 1: "no", 2: "error", 3: "needs-auth"}.get(rc, str(rc))
    except Exception:
        return "error"


def pkcheck_bool(action: str) -> bool:
    return _pkcheck(action) == "yes"


def preflight(action: str, required: str) -> dict:
    """Map a declared requirement to current capability.
    required: none|uaccess|group:NAME|polkit:ACTION|cap:NAME|root|sudo"""
    if required in ("none", ""):
        return {"ok": True}
    if required == "root":
        return {"ok": os.geteuid() == 0,
                "how": "run as root or configure polkit/sudo"}
    if required == "sudo":
        ok = run(["sudo", "-n", "true"], timeout=3).returncode == 0 \
            if which("sudo") else False
        return {"ok": ok, "how": "NOPASSWD sudoers or cached credentials"}
    if required.startswith("group:"):
        g = required.split(":", 1)[1]
        ok = g in run_out(["id", "-Gn"], timeout=3).split()
        return {"ok": ok, "how": f"usermod -aG {g} $USER (re-login)"}
    if required.startswith("polkit:"):
        act = required.split(":", 1)[1]
        r = _pkcheck(act)
        return {"ok": r == "yes", "polkit": r,
                "how": "interactive session auth or polkit rule"}
    if required.startswith("cap:"):
        # crude: check CapEff via /proc/self/status
        try:
            eff = 0
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("CapEff:"):
                        eff = int(line.split()[1], 16)
            caps = {"CAP_NET_ADMIN": 12, "CAP_SYS_NICE": 23,
                    "CAP_SYSLOG": 34}
            bit = caps.get(required.split(":", 1)[1], -1)
            return {"ok": bit >= 0 and bool(eff & (1 << bit))}
        except Exception:
            return {"ok": False}
    if required == "uaccess":
        return {"ok": _session_prop("Active") == "yes",
                "how": "needs active local session (logind uaccess)"}
    return {"ok": False, "how": f"unknown requirement {required}"}
