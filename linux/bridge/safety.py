"""Safety gate for destructive operations — same model as the Windows fork.

Dangerous calls return CONFIRM_REQUIRED with a single-use token bound to
(action, args) with a 60s TTL. Policy env LINUX_MCP_REQUIRE_CONFIRM =
dangerous | all | off.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time

from errors import ConfirmRequired

_TOKENS: dict[str, tuple[str, float]] = {}
_LOCK = threading.Lock()
TTL = 60.0

_AUDIT = os.environ.get(
    "LCU_AUDIT_LOG",
    os.path.expanduser("~/.local/share/linux-computer-use/audit.log"))


def _policy() -> str:
    return os.environ.get("LINUX_MCP_REQUIRE_CONFIRM", "dangerous").lower()


def _digest(action: str, args: dict) -> str:
    blob = json.dumps({"a": action, "args": args}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def audit(action: str, args: dict, outcome: str) -> None:
    try:
        os.makedirs(os.path.dirname(_AUDIT), exist_ok=True)
        with open(_AUDIT, "a") as f:
            f.write(json.dumps({
                "ts": time.time(), "action": action,
                "args": args, "outcome": outcome}) + "\n")
    except Exception:
        pass


def gate(action: str, args: dict, dangerous: bool, confirm_token: str = ""):
    """Raise ConfirmRequired when policy demands and token doesn't match."""
    policy = _policy()
    if policy == "off":
        return
    if policy == "dangerous" and not dangerous:
        return
    want = _digest(action, args)
    if confirm_token:
        with _LOCK:
            got = _TOKENS.get(confirm_token)
            if got and got[0] == want and got[1] > time.time():
                del _TOKENS[confirm_token]   # single-use on match
                audit(action, args, "confirmed")
                return
        raise ConfirmRequired(
            f"invalid or expired confirm token for {action}",
            token="")
    token = secrets.token_urlsafe(16)
    with _LOCK:
        _TOKENS[token] = (want, time.time() + TTL)
    audit(action, args, "confirm-required")
    raise ConfirmRequired(
        f"'{action}' requires confirmation", token=token)
