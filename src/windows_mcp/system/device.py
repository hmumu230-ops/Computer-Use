"""PnP devices and printers."""

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


def list_devices(class_name: str | None = None, status: str | None = None) -> tuple[Any, int]:
    where = []
    if class_name:
        where.append(f"$_.Class -eq '{_q(class_name)}'")
    if status:
        where.append(f"$_.Status -eq '{_q(status)}'")
    filt = (" | Where-Object { " + " -and ".join(where) + " }") if where else ""
    return _ps(
        "Get-PnpDevice" + filt + " | Select-Object -First 200 FriendlyName,Class,Status,InstanceId "
        "| ConvertTo-Json -Compress",
        timeout=60,
    )


def set_device_state(instance_id: str, enabled: bool) -> tuple[Any, int]:
    verb = "Enable" if enabled else "Disable"
    return _ps(
        f"try {{ {verb}-PnpDevice -InstanceId '{_q(instance_id)}' -Confirm:$false "
        "-ErrorAction Stop; "
        f"Get-PnpDevice -InstanceId '{_q(instance_id)}' "
        "| Select-Object FriendlyName,Status | ConvertTo-Json -Compress } "
        "catch { $_.Exception.Message; exit 1 }",
        timeout=60,
    )


def list_printers() -> tuple[Any, int]:
    return _ps(
        "Get-Printer | Select-Object Name,DriverName,PortName,PrinterStatus,"
        "Type,@{n='IsDefault';e={$_.Name -eq (Get-CimInstance Win32_Printer "
        '-Filter "Default=`$true").Name}} | ConvertTo-Json -Compress'
    )


def set_default_printer(name: str) -> tuple[Any, int]:
    return _ps(
        f"(Get-CimInstance Win32_Printer -Filter \"Name='{_q(name)}'\") "
        "| Invoke-CimMethod -MethodName SetDefaultPrinter | Out-Null; "
        f"'{name} set as default'"
    )
