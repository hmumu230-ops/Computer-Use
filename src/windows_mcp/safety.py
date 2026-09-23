"""Runtime safety gate for dangerous operations.

Dangerous actions (shutdown, service stop, registry writes, device disable,
process kill, file delete, system-feature changes) return CONFIRM_REQUIRED
with a single-use token instead of executing. The caller retries with
``confirm=<token>`` within the TTL to authorize exactly that action.

Policy via ``WINDOWS_MCP_REQUIRE_CONFIRM``:
  ``dangerous`` (default) — gate actions marked dangerous
  ``all``                 — gate every non-readonly action
  ``off``                 — never gate (still logged)

Every gated decision is appended to the audit log at
``%LOCALAPPDATA%\\windows-mcp\\audit.log`` (JSONL) for later review.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from typing import Any

logger = logging.getLogger(__name__)

_TOKEN_TTL = 60.0
_MAX_TOKENS = 256

# token -> (action_key, expiry_epoch)
_tokens: dict[str, tuple[str, float]] = {}

_AUDIT_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "windows-mcp", "audit.log"
)


def _policy() -> str:
    return os.environ.get("WINDOWS_MCP_REQUIRE_CONFIRM", "dangerous").strip().lower()


def _audit(event: dict[str, Any]) -> None:
    event = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    try:
        os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
        with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("audit log write failed", exc_info=True)
    logger.info("safety: %s", event)


def _purge() -> None:
    now = time.time()
    expired = [t for t, (_, exp) in _tokens.items() if exp < now]
    for t in expired:
        del _tokens[t]
    while len(_tokens) > _MAX_TOKENS:
        _tokens.pop(next(iter(_tokens)))


def gate(action_key: str, description: str, confirm: str | None, *, dangerous: bool) -> str | None:
    """Check whether an action may proceed.

    Returns None when allowed. Otherwise returns a CONFIRM_REQUIRED message
    containing a one-shot token to pass back as ``confirm=``.
    ``action_key`` binds the token to this exact operation (e.g.
    "service.stop:Spooler") — a token for one action authorizes no other.
    """
    policy = _policy()
    if policy == "off":
        return None
    if policy == "dangerous" and not dangerous:
        return None
    _purge()
    if confirm:
        entry = _tokens.pop(confirm, None)
        if entry and entry[0] == action_key and entry[1] >= time.time():
            _audit({"event": "confirmed", "action": action_key, "detail": description})
            return None
        _audit({"event": "bad_token", "action": action_key, "detail": description})
        return (
            f"CONFIRM_REQUIRED: invalid or expired confirmation token for "
            f"{description!r}. Call again without 'confirm' to get a fresh token."
        )
    token = secrets.token_hex(8)
    _tokens[token] = (action_key, time.time() + _TOKEN_TTL)
    _audit({"event": "blocked", "action": action_key, "detail": description})
    return (
        f"CONFIRM_REQUIRED: {description}. "
        f"To authorize, call this tool again with confirm='{token}' "
        f"within {int(_TOKEN_TTL)}s."
    )


def audit(action_key: str, detail: str) -> None:
    """Record an executed dangerous action (post-gate)."""
    _audit({"event": "executed", "action": action_key, "detail": detail})
