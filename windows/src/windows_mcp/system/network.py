"""Network — adapters, IPs, profiles, proxy, Wi-Fi, connectivity."""

from __future__ import annotations

import json
import winreg
from typing import Any

from windows_mcp.powershell.service import PowerShellExecutor

_PROXY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _ps(cmd: str, timeout: int = 30) -> tuple[Any, int]:
    out, rc = PowerShellExecutor.execute_command(cmd, timeout=timeout)
    if rc != 0:
        return out.strip(), rc
    try:
        return json.loads(out), 0
    except json.JSONDecodeError, ValueError:
        return out.strip(), rc


def list_adapters() -> tuple[Any, int]:
    return _ps(
        "Get-NetAdapter | Select-Object Name,Status,InterfaceDescription,"
        "LinkSpeed,MacAddress | ConvertTo-Json -Compress",
        timeout=60,
    )


def ip_info() -> tuple[Any, int]:
    return _ps(
        "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne '127.0.0.1' } "
        "| Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json -Compress; "
        "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object -First 3 "
        "InterfaceAlias,NextHop | ConvertTo-Json -Compress",
        timeout=60,
    )


def connection_profiles() -> tuple[Any, int]:
    return _ps(
        "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,"
        "NetworkCategory,IPv4Connectivity,IPv6Connectivity | ConvertTo-Json -Compress"
    )


def wifi_status() -> tuple[Any, int]:
    return _ps("netsh wlan show interfaces")


def wifi_networks() -> tuple[Any, int]:
    return _ps("netsh wlan show networks mode=bssid", timeout=30)


def get_proxy() -> dict[str, Any]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PROXY_KEY) as key:

        def val(n):
            try:
                v, _ = winreg.QueryValueEx(key, n)
                return v
            except FileNotFoundError:
                return None

        return {
            "enabled": bool(val("ProxyEnable")),
            "server": val("ProxyServer"),
            "bypass": val("ProxyOverride"),
            "autoconfig_url": val("AutoConfigURL"),
        }


def set_proxy(
    server: str | None, *, enabled: bool = True, bypass: str | None = None
) -> dict[str, Any]:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PROXY_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enabled else 0)
        if server is not None:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
        if bypass is not None:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, bypass)
    # Notify running apps (same broadcast Explorer uses)
    try:
        import ctypes
        from ctypes import wintypes

        InternetSetOptionW = ctypes.windll.wininet.InternetSetOptionW
        InternetSetOptionW.restype = wintypes.BOOL
        for opt in (39, 37):  # INTERNET_OPTION_SETTINGS_CHANGED / REFRESH
            InternetSetOptionW(0, opt, 0, 0)
    except Exception:
        pass
    return get_proxy()


def test_connection(host: str, port: int | None = None) -> tuple[Any, int]:
    if port:
        return _ps(
            f"Test-NetConnection -ComputerName '{host}' -Port {port} "
            "-InformationLevel Detailed | ConvertTo-Json -Compress",
            timeout=60,
        )
    return _ps(
        f"Test-Connection -ComputerName '{host}' -Count 2 -ErrorAction SilentlyContinue "
        "| Select-Object Address,StatusCode,ResponseTime | ConvertTo-Json -Compress",
        timeout=30,
    )
