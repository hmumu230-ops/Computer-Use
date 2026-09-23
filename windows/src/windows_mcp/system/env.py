"""Environment variables — user/machine scope via winreg + WM_SETTINGCHANGE.

Bypasses PowerShell entirely: writes land in the registry hive directly and a
HWND_BROADCAST WM_SETTINGCHANGE tells Explorer/Conhost to reload — new
processes see the variable without a logoff.
"""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes

_USER_ENV = "Environment"
_MACHINE_ENV = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

_REG_SZ_TYPES = (winreg.REG_SZ, winreg.REG_EXPAND_SZ)


def _hive(scope: str):
    if scope == "user":
        return winreg.HKEY_CURRENT_USER, _USER_ENV
    if scope == "machine":
        return winreg.HKEY_LOCAL_MACHINE, _MACHINE_ENV
    raise ValueError("scope must be 'user' or 'machine'")


def _broadcast_change() -> None:
    """Tell running apps the environment changed (SendMessageTimeout)."""
    try:
        SendMessageTimeoutW = ctypes.windll.user32.SendMessageTimeoutW
        SendMessageTimeoutW.restype = wintypes.LPARAM
        SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPCWSTR,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(wintypes.DWORD),
        ]
        result = wintypes.DWORD(0)
        SendMessageTimeoutW(0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
    except Exception:
        pass  # broadcast is best-effort; the registry write is authoritative


def get(name: str, scope: str = "user") -> dict:
    hkey, subkey = _hive(scope)
    with winreg.OpenKey(hkey, subkey) as key:
        value, reg_type = winreg.QueryValueEx(key, name)
    return {
        "name": name,
        "scope": scope,
        "value": value,
        "type": "REG_EXPAND_SZ" if reg_type == winreg.REG_EXPAND_SZ else "REG_SZ",
    }


def set_value(name: str, value: str, scope: str = "user") -> dict:
    hkey, subkey = _hive(scope)
    reg_type = winreg.REG_EXPAND_SZ if "%" in value else winreg.REG_SZ
    with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, reg_type, value)
    _broadcast_change()
    return {"name": name, "scope": scope, "value": value, "set": True}


def delete(name: str, scope: str = "user") -> dict:
    hkey, subkey = _hive(scope)
    with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, name)
    _broadcast_change()
    return {"name": name, "scope": scope, "deleted": True}


def list_all(scope: str = "user") -> dict:
    hkey, subkey = _hive(scope)
    out = {}
    with winreg.OpenKey(hkey, subkey) as key:
        i = 0
        while True:
            try:
                name, value, reg_type = winreg.EnumValue(key, i)
            except OSError:
                break
            if reg_type in _REG_SZ_TYPES:
                out[name] = value
            i += 1
    return {"scope": scope, "variables": out, "count": len(out)}
