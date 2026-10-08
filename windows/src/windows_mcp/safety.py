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
    # JSON encoding avoids separator collisions — ("a|b","c") vs ("a","b|c")
    # would otherwise hash identically and cross-authorize.
    return hashlib.sha256(
        json.dumps(["" if p is None else str(p) for p in parts]).encode("utf-8")
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
    r"send-mailmessage|compress-|expand-|"
    r"invoke-[a-z][a-z0-9-]*"  # invoke-* cmdlets dispatch code by name
    r")"
    r")",
    re.IGNORECASE,
)

# Constructs that evaluate code regardless of the leading verb:
#   [IO.File]::Delete(x)   — static .NET method dispatch
#   \\host\share           — UNC coercion → outbound NTLM capture
_DANGEROUS_SYNTAX = re.compile(r"::|\\\\")

# A segment that is an expression rather than a command invocation —
# variable/literal/property predicates inside Where-Object {} blocks
# (e.g. `$_.CPU -gt 10`, `$x = 1`, `if (...)`) are safe to leave ungated.
_EXPRESSION = re.compile(
    r"^\s*(?:\$|@|\(|\[|'|\"|!|-?\d|true\b|false\b|null\b|"
    r"if\b|else\b|elseif\b|for\b|foreach\b|while\b|switch\b|"
    r"try\b|catch\b|finally\b|return\b|param\b|throw\b|in\b|not\b|"
    r"[A-Za-z_][\w.-]*\s*=)",  # bare assignment/hashtable entry: name = value
    re.IGNORECASE,
)


def _split_top(text: str, pipes: bool = False) -> list[str]:
    """Split on ; \\n && || (and | when `pipes`) at bracket depth 0 only.

    Naive splitting breaks `@{a=1;b={...}}` mid-hashtable and `a | f {x|y}`
    mid-scriptblock — both let payloads hide inside what looks like a
    readonly statement.
    """
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    quote = ""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(depth - 1, 0)
        if depth == 0:
            two = text[i : i + 2]
            if two in ("&&", "||"):
                parts.append("".join(cur))
                cur = []
                i += 2
                continue
            if ch in ";\n" or (pipes and ch == "|"):
                parts.append("".join(cur))
                cur = []
                i += 1
                continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _code_spans(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, inner, kind) for $(...) @(...) @{...} and {...} regions.

    These regions evaluate code wherever they appear — their contents are
    classified recursively by `command_dangerous` instead of trusting the
    leading verb of the enclosing stage. kind is 'code' for statement
    regions and 'hashtable' for @{key=value;...}.
    """
    spans: list[tuple[int, int, str, str]] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"":
            j = i + 1
            while j < n and text[j] != ch:
                j += 1
            i = j + 1
            continue
        inner_start = None
        close = ""
        kind = "code"
        if text.startswith("$(", i) or text.startswith("@(", i):
            inner_start, close = i + 2, ")"
        elif text.startswith("@{", i):
            inner_start, close, kind = i + 2, "}", "hashtable"
        elif ch == "{":
            inner_start, close = i + 1, "}"
        if inner_start is None:
            i += 1
            continue
        open_ch = text[inner_start - 1]
        depth, j = 1, inner_start
        while j < n and depth:
            if text[j] in "'\"":
                q = text[j]
                j += 1
                while j < n and text[j] != q:
                    j += 1
                j += 1
                continue
            if text[j] == open_ch:
                depth += 1
            elif text[j] == close:
                depth -= 1
            j += 1
        spans.append((i, j, text[inner_start : j - 1], kind))
        i = j
    return spans


def _inner_dangerous(inner: str, kind: str, depth: int) -> bool:
    """Classify the contents of one extracted code/hashtable span."""
    if kind == "hashtable":
        # @{key=value; ...} — entries are data; classify each value/expression
        for piece in _split_top(inner):
            piece = piece.strip()
            if piece and _segment_dangerous(piece, depth):
                return True
        return False
    for piece in _split_top(inner):
        piece = piece.strip()
        if not piece:
            continue
        if _MUTATING_TOKENS.search(piece):
            return True
        if _segment_dangerous(piece, depth):
            return True
    return False


def _segment_dangerous(segment: str, _depth: int = 0) -> bool:
    """Classify one statement segment (may contain pipelines + code spans)."""
    if _depth > 6:  # pathological nesting — treat as dangerous
        return True
    # code spans are classified recursively; strip them from the stage text
    # so the enclosing verb match sees only the pipeline shape.
    stage = ""
    pos = 0
    nested: list[tuple[str, str]] = []
    for start, end, inner, kind in _code_spans(segment):
        stage += segment[pos:start] + " "
        nested.append((inner, kind))
        pos = end
    stage += segment[pos:]
    for inner, kind in nested:
        if _inner_dangerous(inner, kind, _depth + 1):
            return True
    if _DANGEROUS_SYNTAX.search(stage):
        return True
    for pipe_stage in _split_top(stage, pipes=True):
        pipe_stage = pipe_stage.strip()
        if not pipe_stage:
            continue
        if not (_READONLY_VERBS.match(pipe_stage) or _EXPRESSION.match(pipe_stage)):
            return True
    return False


def command_dangerous(command: str) -> bool:
    """Heuristic: True when a shell command is *not* recognizably read-only.

    Used for tools whose danger level depends on their payload (PowerShell).
    Read-only pipelines pass ungated under the default policy; everything
    else asks for confirmation. $(...) @(...) and {...} regions evaluate
    code regardless of the leading verb — their contents are classified
    recursively, so `echo $(payload)` and `ForEach-Object { payload }`
    can't smuggle execution past a readonly verb.
    """
    text = command or ""
    if _MUTATING_TOKENS.search(text):
        return True
    # every statement segment must be recognizably read-only; split
    # depth-aware so ; inside @{...} doesn't fragment a hashtable
    for segment in _split_top(text):
        segment = segment.strip()
        if not segment:
            continue
        if _segment_dangerous(segment):
            return True
    return False
