"""Developer mode, optional Windows features, and Explorer file-visibility prefs."""

from __future__ import annotations

import winreg
from typing import Any

from windows_mcp.powershell.service import PowerShellExecutor

_APP_MODEL_UNLOCK = r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock"
_EXPLORER_ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

_FEATURE_ALIASES = {
    "wsl": "Microsoft-Windows-Subsystem-Linux",
    "hyperv": "HypervisorPlatform",
    "hyper-v": "HypervisorPlatform",
    "sandbox": "Containers-DisposableClientVM",
    "vmplatform": "VirtualMachinePlatform",
    "telnet": "TelnetClient",
}


def _q(s: str) -> str:
    """Escape a value for a PowerShell single-quoted string literal."""
    return s.replace("'", "''")


def get_developer_mode() -> dict[str, Any]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _APP_MODEL_UNLOCK) as key:
            value, _ = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
        return {"developer_mode": bool(value), "writable": True}
    except FileNotFoundError:
        return {"developer_mode": False, "writable": True, "note": "value absent = off"}
    except PermissionError:
        return {
            "developer_mode": "unknown",
            "writable": False,
            "note": "HKLM read denied — run the server elevated to query",
        }


def set_developer_mode(enabled: bool) -> dict[str, Any]:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _APP_MODEL_UNLOCK, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(
                key,
                "AllowDevelopmentWithoutDevLicense",
                0,
                winreg.REG_DWORD,
                1 if enabled else 0,
            )
    except PermissionError:
        raise PermissionError(
            "HKLM write denied — the Windows-MCP server must run elevated to toggle Developer Mode"
        )
    return {"developer_mode": bool(enabled), "set": True}


def list_optional_features() -> tuple[Any, int]:
    return PowerShellExecutor.execute_command(
        "Get-WindowsOptionalFeature -Online | "
        "Select-Object FeatureName,State | ConvertTo-Json -Compress",
        timeout=60,
    )


def get_feature(name: str) -> tuple[Any, int]:
    real = _q(_FEATURE_ALIASES.get(name.lower(), name))
    return PowerShellExecutor.execute_command(
        f"Get-WindowsOptionalFeature -Online -FeatureName '{real}' | "
        "Select-Object FeatureName,State | ConvertTo-Json -Compress"
    )


def set_feature(name: str, enabled: bool) -> tuple[Any, int]:
    real = _q(_FEATURE_ALIASES.get(name.lower(), name))
    verb = "Enable" if enabled else "Disable"
    return PowerShellExecutor.execute_command(
        f"{verb}-WindowsOptionalFeature -Online -FeatureName '{real}' -NoRestart "
        "-ErrorAction Stop | Select-Object FeatureName,RestartNeeded | ConvertTo-Json -Compress",
        timeout=120,
    )


def get_explorer_prefs() -> dict[str, Any]:
    out: dict[str, Any] = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _EXPLORER_ADV) as key:
        for name, key_name in (
            ("show_file_extensions", "HideFileExt"),
            ("show_hidden_files", "Hidden"),
            ("show_protected_os_files", "ShowSuperHidden"),
        ):
            try:
                value, _ = winreg.QueryValueEx(key, key_name)
            except FileNotFoundError:
                value = None
            if name == "show_file_extensions":
                out[name] = (value == 0) if value is not None else False
            else:
                out[name] = (value == 1) if value is not None else False
    out["note"] = "changes apply after Explorer reloads folder views (or restart explorer)"
    return out


def set_explorer_pref(name: str, enabled: bool) -> dict[str, Any]:
    mapping = {
        "show_file_extensions": ("HideFileExt", 0 if enabled else 1),
        "show_hidden_files": ("Hidden", 1 if enabled else 2),
        "show_protected_os_files": ("ShowSuperHidden", 1 if enabled else 0),
    }
    if name not in mapping:
        raise ValueError(f"name must be one of: {', '.join(mapping)}")
    key_name, value = mapping[name]
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _EXPLORER_ADV, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, key_name, 0, winreg.REG_DWORD, value)
    return {
        name: bool(enabled),
        "set": True,
        "note": "open Explorer windows may need refresh (F5) to reflect the change",
    }
