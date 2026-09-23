"""Confirm-token safety gate for destructive operations.

Mirrors the Linux bridge gate: a dangerous call without a token raises
``ConfirmRequired`` and the caller receives a single-use token bound to
the action + params digest, valid for ``TTL`` seconds. Set env
``MACOS_MCP_REQUIRE_CONFIRM`` (``1/true/yes/on`` or a comma list of action
prefixes) to require gating; ``dangerous`` actions are always gated when
the env is set.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from .errors import ConfirmRequired

TTL = 120.0
_TOKENS: dict[str, tuple[str, float]] = {}   # token -> (digest, expiry)


def _digest(action: str, params: dict | None) -> str:
    blob = json.dumps({"a": action, "p": params or {}}, sort_keys=True,
                      default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _policy() -> set[str] | bool:
    raw = os.environ.get("MACOS_MCP_REQUIRE_CONFIRM", "")
    if raw.lower() in ("1", "true", "yes", "on", "all", "dangerous"):
        return True
    if not raw:
        return False
    return {s.strip() for s in raw.split(",") if s.strip()}


def required(action: str) -> bool:
    pol = _policy()
    if pol is True:
        return True
    if pol is False:
        return False
    return any(action.startswith(p) for p in pol)


def gate(action: str, params: dict | None, dangerous: bool,
         token: str = "") -> dict | None:
    """Gate a possibly-destructive action.

    Returns ``{"confirm_required": True, "token": ...}``... actually raises
    ConfirmRequired carrying the fresh token in ``details["token"]`` when
    gating applies and no valid token was supplied; otherwise returns None
    and lets the caller proceed.
    """
    if not (dangerous or required(action)):
        return None
    digest = _digest(action, params)
    if token:
        entry = _TOKENS.get(token)
        if entry and entry[0] == digest and entry[1] > time.time():
            _TOKENS.pop(token)          # single-use, only on a real match
            return None
        if entry:
            raise ConfirmRequired(action,
                                  hint="token expired or bound to a different action")
        raise ConfirmRequired(action, hint="invalid or unknown token")
    import secrets
    tok = secrets.token_urlsafe(16)
    _TOKENS[tok] = (digest, time.time() + TTL)
    raise ConfirmRequired(
        action,
        hint=f"re-call with confirmToken='{tok}' within {int(TTL)}s",
        token=tok)


def sweep() -> int:
    """Drop expired tokens; returns count removed."""
    now = time.time()
    dead = [t for t, (_, exp) in _TOKENS.items() if exp <= now]
    for t in dead:
        _TOKENS.pop(t, None)
    return len(dead)
