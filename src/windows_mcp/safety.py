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

import hashlib
import json
import logging
import os
import re
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


def digest(*parts: object) -> str:
    """Canonical binding digest for action keys — bind *all* parameters that
    change what the operation does, so a token issued for one payload can't
    authorize a different one (e.g. a task created for notepad.exe must not
    confirm the same task name pointed at malware)."""
    return hashlib.sha256(
        "|".join("" if p is None else str(p) for p in parts).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Shell command classification
# ---------------------------------------------------------------------------
#
# PowerShell is the biggest gate-bypass surface: every gated action has a
# cmdlet or shell equivalent. We can't prove a command is safe, so instead we
# only skip the gate when *every* pipeline/statement segment is recognizably
# read-only. Anything unparseable, mutating, or containing output redirection
# is dangerous.

_READONLY_VERBS = re.compile(
    r"^\s*(?:&\s*)?(?:"
    r"get-[a-z][a-z0-9-]*|gci|gcm|gm|gi|gl|gp|gps|gpv|gdr|ghy|"
    r"ls|dir|cd\b|pwd\b|sls\b|cat|type|gc\b|echo\b|"
    r"select-(?:object|string|first|last|skip|unique|property)|"
    r"where(?:-object)?\b|foreach(?:-object)?\b|sort(?:-object)?\b|"
    r"measure-(?:object|command)|format-(?:table|list|wide|custom)|"
    r"out-(?:string|host|null|default)|"
    r"write-(?:output|host|verbose|debug|information|progress)|"
    r"read-host|test-(?:path|connection|netconnection)|"
    r"resolve-(?:path|dnsname)|convertfrom-(?:json|csv|stringdata)|"
    r"convertto-(?:json|csv|xml|html)|compare-object|"
    r"whoami|hostname|systeminfo|ver|date|time|history|"
    r"ipconfig(?:\s+/(?:all|displaydns))?|ping\b|tracert\b|nslookup\b|"
    r"tree\b|where\.exe|which\b|"
    r"\$(?:env:[a-z_]+|\?|true|false|null|pwd)\b|"
    r"[a-z_]+:\s*$"  # bare drive change like 'c:'
    r")",
    re.IGNORECASE,
)

# Tokens that make any command dangerous regardless of verb match.
_MUTATING_TOKENS = re.compile(
    r"(?:"
    r">(?!>)|>>"  # redirection writes files ('->' comparison never appears as '>')
    r"|\b(?:"
    r"stop-|start-|restart-|set-|new-|add-|remove-|clear-|"
    r"rename-|move-|copy-|delete-|disable-|enable-|"
    r"rm\b|del\b|erase\b|rd\b|rmdir\b|ni\b|md\b|mkdir\b|cp\b|copy\b|mv\b|move\b|"
    r"ren\b|kill\b|taskkill\b|shutdown\b|restart-computer|stop-computer|"
    r"reg\b|regsvr32|regedit|"
    r"sc(?:\.exe)?\b|schtasks|wmic\b|"
    r"icacls|takeown|cacls|attrib|compact|cipher\b|"
    r"netsh|route\b|arp\b|"
    r"ipconfig\s+/(?:release|renew|flushdns|registerdns)|"
    r"start-(?:process|service|job|bits|sleep\b)|stop-(?:process|service|job)|"
    r"invoke-(?:expression|command|webrequest|restmethod|wmi|item)|"
    r"iex\b|irm\b|iwr\b|iws\b|wget\b|curl\b|"
    r"set-content|add-content|out-file|tee-object|"
    r"set-executionpolicy|install-|uninstall-|update-|"
    r"format-(?:volume|disk|drive)|fsutil|diskpart|diskshadow|bcdedit|bootcfg|"
    r"vssadmin|wbadmin|powercfg|net\b|net1\b|"
    r"msiexec|winget|choco\b|scoop\b|"
    r"python|py\b|node\b|npm|npx|pip\b|uv\b|git\b|"
    r"ssh\b|scp\b|sftp\b|ftp\b|telnet\b|"
    r"net\s+use|subst\b|mount\b|pnputil|dism\b|sfc\b|chkdsk|defrag|"
    r"auditpol|wevtutil|gpupdate|secedit|certutil|certreq|bitsadmin|"
    r"driverquery|rundll32|mshta|cscript|wscript|hh\b|control\b|mmc\b|"
    r"taskmgr|eventvwr|services\.msc|taskschd|devmgmt|diskmgmt|compmgmt|lusrmgr|"
    r"send-mailmessage|compress-|expand-"
    r")"
    r")",
    re.IGNORECASE,
)


def command_dangerous(command: str) -> bool:
    """Heuristic: True when a shell command is *not* recognizably read-only.

    Used for tools whose danger level depends on their payload (PowerShell).
    Read-only pipelines pass ungated under the default policy; everything
    else asks for confirmation.
    """
    text = command or ""
    if _MUTATING_TOKENS.search(text):
        return True
    # every statement segment must be recognizably read-only
    segments = re.split(r"[;\n]|&&|\|\|", text)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        # split pipelines; each stage must also be read-only
        stages = [s.strip() for s in segment.split("|") if s.strip()]
        for stage in stages:
            if not _READONLY_VERBS.match(stage):
                return True
    return False
