"""Shared helpers: logging, subprocess runner, PATH checks.

All human-readable command output is forced to English/POSIX locale
(LC_ALL=C) — several tools localize output or emit locale-broken JSON.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

def _base_env() -> dict:
    """Subprocess env computed at call time — never a stale snapshot.

    `env_for_gui()` may inject DISPLAY/DBUS into os.environ after import;
    a module-level `dict(os.environ)` captured before that point would
    hide the recovered session from every spawned tool.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["SYSTEMD_PAGER"] = ""
    env["PAGER"] = "cat"
    return env


def log(msg: str) -> None:
    print(f"[lcu] {msg}", file=sys.stderr, flush=True)


def which(tool: str) -> str | None:
    return shutil.which(tool)


def run(cmd: list[str], timeout: float = 10.0, check: bool = False,
        env: dict | None = None, input_text: str | None = None,
        binary: bool = False) -> subprocess.CompletedProcess:
    """Run a command, POSIX-locale, no pager. Raises TimeoutExpired/FileNotFoundError."""
    return subprocess.run(
        cmd, capture_output=True, text=not binary, timeout=timeout,
        check=check, env=env or _base_env(), input=input_text,
    )


def run_out(cmd: list[str], timeout: float = 10.0) -> str:
    """stdout or "" — never raises on non-zero exit."""
    try:
        return run(cmd, timeout=timeout).stdout
    except Exception:
        return ""


def env_for_gui() -> dict:
    """Best-effort completion of GUI session env vars for headless/SSH contexts.

    MCP clients may spawn us without DISPLAY/DBUS_SESSION_BUS_ADDRESS etc.
    Pull them from `systemctl --user show-environment` when available.
    """
    env = dict(os.environ)
    need = ["DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
            "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP",
            "XAUTHORITY"]
    missing = [k for k in need if not env.get(k)]
    if not missing:
        return env
    uid = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if not env.get("XDG_RUNTIME_DIR") and os.path.isdir(uid):
        env["XDG_RUNTIME_DIR"] = uid
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={uid}/bus")
    try:
        out = run(["systemctl", "--user", "show-environment"], timeout=5,
                  env=env).stdout
        for line in out.splitlines():
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k in missing and v and k not in env:
                env[k] = v
    except Exception:
        pass
    return env


def detect_scale_fallback(img_px_w: int, logical_w: int) -> float:
    if logical_w <= 0:
        return 1.0
    return img_px_w / logical_w


class Debounce:
    """Tiny monotonic-time debounce for rate-limited backends."""

    def __init__(self, interval: float):
        self.interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def ready(self) -> bool:
        import time
        with self._lock:
            now = time.monotonic()
            if now - self._last >= self.interval:
                self._last = now
                return True
            return False
