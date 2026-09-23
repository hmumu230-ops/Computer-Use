"""Windows Event Log — structured reads via Get-WinEvent."""

from __future__ import annotations

import json
from typing import Any

from windows_mcp.powershell.service import PowerShellExecutor


def _q(s: str) -> str:
    return s.replace("'", "''")


def query(
    log_name: str = "Application",
    max_events: int = 20,
    level: int | None = None,
    provider: str | None = None,
) -> tuple[Any, int]:
    """Read events. level: 1=Critical 2=Error 3=Warning 4=Information 5=Verbose."""
    filters = [f"LogName='{_q(log_name)}'"]
    if level is not None:
        filters.append(f"Level={int(level)}")
    if provider:
        filters.append(f"ProviderName='{_q(provider)}'")
    hashtable = ";".join(filters)
    out, rc = PowerShellExecutor.execute_command(
        f"Get-WinEvent -FilterHashtable @{{{hashtable}}} -MaxEvents {int(max_events)} "
        "-ErrorAction Stop | Select-Object TimeCreated,Id,LevelDisplayName,"
        "ProviderName,Message | ConvertTo-Json -Compress -Depth 3",
        timeout=60,
    )
    if rc != 0:
        return out.strip(), rc
    try:
        return json.loads(out), 0
    except json.JSONDecodeError, ValueError:
        return out.strip(), rc


def list_logs() -> tuple[Any, int]:
    out, rc = PowerShellExecutor.execute_command(
        "Get-WinEvent -ListLog * -ErrorAction SilentlyContinue | "
        "Where-Object { $_.RecordCount -gt 0 } | Select-Object -First 50 "
        "LogName,RecordCount,IsEnabled | ConvertTo-Json -Compress",
        timeout=60,
    )
    if rc != 0:
        return out.strip(), rc
    try:
        return json.loads(out), 0
    except json.JSONDecodeError, ValueError:
        return out.strip(), rc
