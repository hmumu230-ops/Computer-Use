"""Identity & privilege — who the server runs as and what it can reach."""

from __future__ import annotations

from windows_mcp.desktop.utils import is_elevated
from windows_mcp.powershell.service import PowerShellExecutor


def whoami() -> dict:
    out, _ = PowerShellExecutor.execute_command("whoami")
    groups_out, _ = PowerShellExecutor.execute_command(
        "(whoami /groups /fo csv | ConvertFrom-Csv | "
        "Select-Object -ExpandProperty 'Group Name') -join ', '"
    )
    return {
        "user": out.strip(),
        "elevated": is_elevated(),
        "groups": groups_out.strip(),
        "note": (
            "Elevated server can drive admin windows (regedit, services.msc) "
            "and UIA elements of elevated apps. Non-elevated server gets "
            "ACCESS_DENIED on those."
            if not is_elevated()
            else "Server is elevated — full UI access including admin windows."
        ),
    }
