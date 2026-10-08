"""Windows services — list/status/start/stop/restart/startup-type."""

from __future__ import annotations

import json
from typing import Any

from windows_mcp.powershell.service import PowerShellExecutor


def _ps(cmd: str, timeout: int = 30) -> tuple[Any, int]:
    out, rc = PowerShellExecutor.execute_command(cmd, timeout=timeout)
    if rc != 0:
        return out.strip(), rc
    try:
        return json.loads(out), 0
    except (json.JSONDecodeError, ValueError):
        return out.strip(), rc


def list_services(name_filter: str | None = None, status: str | None = None) -> tuple[Any, int]:
    where = []
    if name_filter:
        safe = name_filter.replace("'", "''")
        where.append(f"$_.Name -like '*{safe}*' -or $_.DisplayName -like '*{safe}*'")
    if status:
        safe = status.replace("'", "''")
        where.append(f"$_.Status -eq '{safe}'")
    filt = (" | Where-Object { " + " -and ".join(where) + " }") if where else ""
    return _ps(
        "Get-Service" + filt + " | Select-Object -First 200 Name,DisplayName,Status,StartType "
        "| ConvertTo-Json -Compress"
    )


def get_service(name: str) -> tuple[Any, int]:
    safe = name.replace("'", "''")
    return _ps(
        f"Get-Service -Name '{safe}' | Select-Object Name,DisplayName,Status,StartType,"
        "CanStop,CanShutdown,DependentServices,ServicesDependedOn | ConvertTo-Json -Compress -Depth 3"
    )


def _svc_action(verb: str, name: str) -> tuple[Any, int]:
    safe = name.replace("'", "''")
    return _ps(
        f"try {{ {verb}-Service -Name '{safe}' -ErrorAction Stop; "
        f"Get-Service -Name '{safe}' | Select-Object Name,Status,StartType | ConvertTo-Json -Compress }} "
        "catch { $_.Exception.Message; exit 1 }"
    )


def start_service(name: str) -> tuple[Any, int]:
    return _svc_action("Start", name)


def stop_service(name: str, force: bool = False) -> tuple[Any, int]:
    safe = name.replace("'", "''")
    f = " -Force" if force else ""
    return _ps(
        f"try {{ Stop-Service -Name '{safe}'{f} -ErrorAction Stop; "
        f"Get-Service -Name '{safe}' | Select-Object Name,Status,StartType | ConvertTo-Json -Compress }} "
        "catch { $_.Exception.Message; exit 1 }"
    )


def restart_service(name: str) -> tuple[Any, int]:
    return _svc_action("Restart", name)


def set_startup_type(name: str, startup_type: str) -> tuple[Any, int]:
    if startup_type not in ("Automatic", "Manual", "Disabled", "Boot", "System"):
        return "startup_type must be Automatic|Manual|Disabled|Boot|System", 1
    safe = name.replace("'", "''")
    return _ps(
        f"try {{ Set-Service -Name '{safe}' -StartupType {startup_type} -ErrorAction Stop; "
        f"Get-Service -Name '{safe}' | Select-Object Name,Status,StartType | ConvertTo-Json -Compress }} "
        "catch { $_.Exception.Message; exit 1 }"
    )
