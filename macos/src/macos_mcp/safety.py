"""Confirm-token safety gate for destructive operations.

Same model as the Windows/Linux forks: a gated call without a valid token
raises ``ConfirmRequired`` carrying a single-use token bound to the
action + params digest, valid for ``TTL`` seconds.

Policy env ``MACOS_MCP_REQUIRE_CONFIRM``:
  ``dangerous`` (default)  — only calls marked dangerous are gated
  ``all`` / ``1``/``true``/``yes``/``on`` — every gated call needs a token
  ``off`` / ``0``/``false``/``no`` — gating disabled entirely
  comma list of action prefixes (``shell,service``) — only those actions
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time

from .errors import ConfirmRequired

TTL = 60.0
_TOKENS: dict[str, tuple[str, float]] = {}   # token -> (digest, expiry)
_LOCK = threading.Lock()
_MAX_TOKENS = 256

_AUDIT = os.environ.get(
    "MACOS_MCP_AUDIT_LOG",
    os.path.expanduser("~/Library/Application Support/macos-mcp/audit.log"),
)


def _digest(action: str, params: dict | None) -> str:
    blob = json.dumps({"a": action, "p": params or {}}, sort_keys=True,
                      default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def audit(action: str, params: dict | None, outcome: str) -> None:
    """Append one audit record; never raises."""
    try:
        os.makedirs(os.path.dirname(_AUDIT), exist_ok=True)
        with open(_AUDIT, "a") as f:
            f.write(json.dumps({
                "ts": time.time(), "action": action,
                "params": params or {}, "outcome": outcome}) + "\n")
    except Exception:
        pass


def _policy() -> str:
    return os.environ.get("MACOS_MCP_REQUIRE_CONFIRM", "dangerous").strip().lower()


def required(action: str, dangerous: bool = False) -> bool:
    """Whether `action` needs a confirm token under the current policy."""
    pol = _policy()
    if pol in ("off", "0", "false", "no"):
        return False
    if pol in ("all", "1", "true", "yes", "on"):
        return True
    if pol in ("", "dangerous"):
        return dangerous
    return any(action.startswith(p) for p in pol.split(",") if p.strip())


def _sweep_locked(now: float) -> None:
    dead = [t for t, (_, exp) in _TOKENS.items() if exp <= now]
    for t in dead:
        _TOKENS.pop(t, None)
    overflow = len(_TOKENS) - _MAX_TOKENS
    if overflow > 0:
        for t in sorted(_TOKENS, key=lambda k: _TOKENS[k][1])[:overflow]:
            _TOKENS.pop(t, None)


def gate(action: str, params: dict | None, dangerous: bool,
         token: str = "") -> None:
    """Raise ConfirmRequired when policy demands and the token doesn't match."""
    if not required(action, dangerous):
        return
    digest = _digest(action, params)
    now = time.time()
    if token:
        with _LOCK:
            entry = _TOKENS.get(token)
            if entry and entry[0] == digest and entry[1] > now:
                _TOKENS.pop(token)          # single-use, only on a real match
                audit(action, params, "confirmed")
                return
        audit(action, params, "invalid-token")
        raise ConfirmRequired(
            action, hint="token expired or bound to a different action")
    tok = secrets.token_urlsafe(16)
    with _LOCK:
        _sweep_locked(now)
        _TOKENS[tok] = (digest, now + TTL)
    audit(action, params, "confirm-required")
    raise ConfirmRequired(
        action,
        hint=f"re-call with confirmToken='{tok}' within {int(TTL)}s",
        token=tok)
