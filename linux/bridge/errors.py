"""Structured error model for the bridge.

Every failure surfaces as {"code", "message", "hint", "retryable", "permission"?}.
Codes are stable strings — agents should branch on `code`, never on message text.
"""
from __future__ import annotations


class CuError(Exception):
    code = "INTERNAL"
    retryable = False

    def __init__(self, message: str, hint: str = "", permission: str | None = None,
                 retryable: bool | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.permission = permission
        if retryable is not None:
            self.retryable = retryable

    def to_dict(self) -> dict:
        d: dict = {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "retryable": self.retryable,
        }
        if self.permission:
            d["permission"] = self.permission
        return d


class StaleRef(CuError):
    code = "STALE_REF"
    retryable = True


class AmbiguousRef(CuError):
    code = "AMBIGUOUS_REF"
    retryable = False

    def __init__(self, message: str, candidates: list | None = None, **kw):
        super().__init__(message, **kw)
        self.candidates = candidates or []

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["candidates"] = self.candidates
        return d


class Timeout(CuError):
    code = "TIMEOUT"
    retryable = True


class UnsupportedPlatform(CuError):
    code = "UNSUPPORTED_PLATFORM"


class UnsupportedCompositor(CuError):
    code = "UNSUPPORTED_COMPOSITOR"

    def __init__(self, message: str, compositor: str = "", **kw):
        super().__init__(message, **kw)
        self.compositor = compositor

    def to_dict(self) -> dict:
        d = super().to_dict()
        if self.compositor:
            d["compositor"] = self.compositor
        return d


class PermissionRequired(CuError):
    code = "PERMISSION_REQUIRED"


class ConfirmRequired(CuError):
    code = "CONFIRM_REQUIRED"

    def __init__(self, message: str, token: str = "", **kw):
        super().__init__(message, **kw)
        self.token = token

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["confirmToken"] = self.token
        return d


class EngineUnavailable(CuError):
    code = "ENGINE_UNAVAILABLE"


class InvalidArgs(CuError):
    code = "INVALID_ARGS"


class UnknownCommand(CuError):
    code = "UNKNOWN_COMMAND"


class BridgeDead(CuError):
    code = "BRIDGE_DEAD"
    retryable = True


class ToolNotFound(CuError):
    code = "TOOL_NOT_FOUND"

    def __init__(self, tool: str, hint: str = ""):
        super().__init__(
            f"required tool not on PATH: {tool}",
            hint=hint or f"install it (e.g. see `linux-computer-use-mcp setup` output)",
        )
        self.tool = tool


def to_error_dict(e: Exception) -> dict:
    """Normalize any exception into the wire error shape."""
    if isinstance(e, CuError):
        return e.to_dict()
    if isinstance(e, TimeoutError):
        return Timeout(str(e) or "operation timed out").to_dict()
    if isinstance(e, FileNotFoundError):
        return ToolNotFound(e.filename or str(e)).to_dict()
    if isinstance(e, PermissionError):
        return PermissionRequired(str(e), permission="os").to_dict()
    return {"code": "INTERNAL", "message": str(e) or type(e).__name__,
            "hint": "", "retryable": False}
