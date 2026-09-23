"""Scheduled tasks — list/run/enable/disable/info/create."""

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
    except json.JSONDecodeError, ValueError:
        return out.strip(), rc


def _q(s: str) -> str:
    return s.replace("'", "''")


def list_tasks(name_filter: str | None = None, state: str | None = None) -> tuple[Any, int]:
    where = []
    if name_filter:
        safe = _q(name_filter)
        where.append(f"$_.TaskName -like '*{safe}*'")
    if state:
        safe = _q(state)
        where.append(f"$_.State -eq '{safe}'")
    filt = (" | Where-Object { " + " -and ".join(where) + " }") if where else ""
    return _ps(
        "Get-ScheduledTask"
        + filt
        + " | Select-Object -First 200 TaskName,TaskPath,State | ConvertTo-Json -Compress",
        timeout=60,
    )


def task_info(name: str, path: str = "\\") -> tuple[Any, int]:
    return _ps(
        f"Get-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}' -ErrorAction Stop "
        "| ForEach-Object { $info = $_ | Get-ScheduledTaskInfo; "
        "[PSCustomObject]@{ TaskName=$_.TaskName; State=$_.State; "
        "LastRunTime=$info.LastRunTime; LastResult=$info.LastTaskResult; "
        "NextRunTime=$info.NextRunTime; Actions=($_.Actions | ForEach-Object { $_.Execute }) } } "
        "| ConvertTo-Json -Compress"
    )


def run_task(name: str, path: str = "\\") -> tuple[Any, int]:
    return _ps(
        f"Start-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}'; "
        f"Start-Sleep -Milliseconds 500; "
        f"Get-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}' "
        "| Select-Object TaskName,State | ConvertTo-Json -Compress"
    )


def enable_task(name: str, path: str = "\\") -> tuple[Any, int]:
    return _ps(
        f"Enable-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}' "
        "| Select-Object TaskName,State | ConvertTo-Json -Compress"
    )


def disable_task(name: str, path: str = "\\") -> tuple[Any, int]:
    return _ps(
        f"Disable-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}' "
        "| Select-Object TaskName,State | ConvertTo-Json -Compress"
    )


def create_task(
    name: str,
    program: str,
    arguments: str = "",
    trigger: str = "once",
    run_level: str = "Limited",
) -> tuple[Any, int]:
    """Create a basic scheduled task. trigger: once|at_logon|daily|at_startup."""
    triggers = {
        "once": "New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1)",
        "at_logon": "New-ScheduledTaskTrigger -AtLogOn",
        "daily": "New-ScheduledTaskTrigger -Daily -At 09:00",
        "at_startup": "New-ScheduledTaskTrigger -AtStartup",
    }
    if trigger not in triggers:
        return f"trigger must be one of: {', '.join(triggers)}", 1
    if run_level not in ("Limited", "Highest"):
        return "run_level must be Limited or Highest", 1
    cmd = (
        f"$a = New-ScheduledTaskAction -Execute '{_q(program)}' -Argument '{_q(arguments)}'; "
        f"$t = {triggers[trigger]}; "
        f"$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel {run_level}; "
        f"Register-ScheduledTask -TaskName '{_q(name)}' -Action $a -Trigger $t -Principal $p "
        "| Select-Object TaskName,State | ConvertTo-Json -Compress"
    )
    return _ps(cmd)


def delete_task(name: str, path: str = "\\") -> tuple[Any, int]:
    return _ps(
        f"Unregister-ScheduledTask -TaskName '{_q(name)}' -TaskPath '{_q(path)}' "
        "-Confirm:$false; 'deleted'"
    )
