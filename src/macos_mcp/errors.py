"""Structured errors for the enhanced macOS-MCP surface.

Mirrors the Windows/Linux fork error shape so agents see the same
{code, message, hint, retryable} contract on every platform.
"""

from __future__ import annotations


class CuError(Exception):
    """Base structured error.

    Attributes:
        code: Stable machine-readable code (e.g. ``STALE_REF``).
        message: Human-readable description.
        hint: Actionable remediation shown to the agent.
        retryable: Whether retrying the same call could succeed.
    """

    code = "ERROR"
    retryable = False

    def __init__(self, message: str, hint: str = "", **kw):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = kw

    def __str__(self) -> str:
        out = f"{self.code}: {self.message}"
        if self.hint:
            out += f" | hint: {self.hint}"
        return out

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "retryable": self.retryable,
            **self.details,
        }


class InvalidArgs(CuError):
    code = "INVALID_ARGS"


class StaleRef(CuError):
    """A @eN/@wN ref no longer resolves — tree was re-captured or the
    element died. Caller should take a fresh Snapshot."""

    code = "STALE_REF"
    retryable = True


class UnsupportedCapability(CuError):
    code = "UNSUPPORTED"


class PermissionRequired(CuError):
    """A TCC/macos permission or confirm token is needed."""

    code = "PERMISSION_REQUIRED"


class ConfirmRequired(CuError):
    """Dangerous op without a matching confirm token."""

    code = "CONFIRM_REQUIRED"

    def __init__(self, action: str, hint: str = "", **kw):
        super().__init__(
            f"'{action}' requires a confirm token",
            hint=hint or "call with confirm=true to get a token, then pass it back",
            **kw,
        )


class ToolNotFound(CuError):
    code = "TOOL_NOT_FOUND"

    def __init__(self, tool: str, hint: str = "", **kw):
        super().__init__(
            f"required tool '{tool}' not found",
            hint=hint or f"install {tool} (e.g. via brew)",
            **kw,
        )


class EngineUnavailable(CuError):
    code = "ENGINE_UNAVAILABLE"
