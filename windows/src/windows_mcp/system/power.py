"""Power & session — lock/sleep/hibernate/shutdown/restart/logoff + power plans."""

from __future__ import annotations

from windows_mcp.powershell.service import PowerShellExecutor


def _q(s: str) -> str:
    """Escape a value for a PowerShell single-quoted string literal."""
    return s.replace("'", "''")


def lock() -> tuple[str, int]:
    return PowerShellExecutor.execute_command(
        "rundll32.exe user32.dll,LockWorkStation; Start-Sleep -Milliseconds 500; "
        "'Workstation lock requested'"
    )


def sleep() -> tuple[str, int]:
    # SetSuspendState via System.Windows.Forms — rundll32 powrprof is
    # unreliable on modern builds (hibernates instead of sleeping when
    # hibernation is enabled).
    return PowerShellExecutor.execute_command(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false) | Out-Null; "
        "'Sleep requested'"
    )


def hibernate() -> tuple[str, int]:
    return PowerShellExecutor.execute_command(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.Application]::SetSuspendState('Hibernate', $true, $true) | Out-Null; "
        "'Hibernate requested'"
    )


def shutdown(timeout_sec: int = 0, force: bool = False) -> tuple[str, int]:
    flag = "/f" if force else ""
    return PowerShellExecutor.execute_command(
        f"shutdown.exe /s /t {int(timeout_sec)} {flag}"
    )


def restart(timeout_sec: int = 0, force: bool = False) -> tuple[str, int]:
    flag = "/f" if force else ""
    return PowerShellExecutor.execute_command(
        f"shutdown.exe /r /t {int(timeout_sec)} {flag}"
    )


def logoff() -> tuple[str, int]:
    return PowerShellExecutor.execute_command("shutdown.exe /l")


def cancel_shutdown() -> tuple[str, int]:
    return PowerShellExecutor.execute_command("shutdown.exe /a")


def list_power_plans() -> tuple[str, int]:
    return PowerShellExecutor.execute_command("powercfg /list")


def get_active_plan() -> tuple[str, int]:
    return PowerShellExecutor.execute_command("powercfg /getactivescheme")


def set_active_plan(guid_or_name: str) -> tuple[str, int]:
    return PowerShellExecutor.execute_command(
        f"powercfg /setactive '{_q(guid_or_name)}'"
    )


def battery_status() -> tuple[str, int]:
    return PowerShellExecutor.execute_command(
        "$b = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue; "
        "if ($b) { $b | Select-Object EstimatedChargeRemaining, BatteryStatus, "
        "EstimatedRunTime | ConvertTo-Json -Compress } else { 'no battery (desktop/VM)' }"
    )


def uptime() -> tuple[str, int]:
    return PowerShellExecutor.execute_command(
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$up = (Get-Date) - $os.LastBootUpTime; "
        "('{0}d {1}h {2}m {3}s since {4}' -f $up.Days, $up.Hours, $up.Minutes, $up.Seconds, "
        "$os.LastBootUpTime)"
    )
