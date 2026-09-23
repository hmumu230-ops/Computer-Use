"""Display control — brightness (WMI), resolution/mode (pywin32), monitor list."""

from __future__ import annotations

from typing import Any

import win32api
import win32con

from windows_mcp.powershell.service import PowerShellExecutor


def get_brightness() -> dict[str, Any]:
    out, rc = PowerShellExecutor.execute_command(
        "Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightness "
        "-ErrorAction Stop | Select-Object -ExpandProperty CurrentBrightness"
    )
    if rc != 0:
        return {
            "error": out.strip(),
            "note": "brightness needs a laptop/internal panel (WMI WmiMonitorBrightness)",
        }
    try:
        return {"brightness": int(out.strip().splitlines()[-1])}
    except ValueError, IndexError:
        return {"brightness": None, "raw": out.strip()}


def set_brightness(level: int) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    out, rc = PowerShellExecutor.execute_command(
        f"(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods "
        f"-ErrorAction Stop).WmiSetBrightness(1, {level}) | Out-Null; 'set to {level}'",
        timeout=20,
    )
    if rc != 0:
        return {"error": out.strip()}
    return get_brightness()


def list_modes() -> dict[str, Any]:
    """Current mode per display device."""
    modes = []
    i = 0
    while True:
        try:
            dev = win32api.EnumDisplayDevices(None, i)
        except Exception:
            break
        if not dev or not dev.DeviceName:
            break
        try:
            settings = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
            modes.append(
                {
                    "device": dev.DeviceName,
                    "name": dev.DeviceString,
                    "width": settings.PelsWidth,
                    "height": settings.PelsHeight,
                    "hz": settings.DisplayFrequency,
                    "primary": bool(dev.StateFlags & 4),  # DISPLAY_DEVICE_PRIMARY_DEVICE
                }
            )
        except Exception:
            pass
        i += 1
    return {"displays": modes}


def set_resolution(
    device: str | None, width: int, height: int, hz: int | None = None
) -> dict[str, Any]:
    """Change a display's resolution. device=None targets the primary display."""
    if device is None:
        for m in list_modes()["displays"]:
            if m["primary"]:
                device = m["device"]
                break
    if device is None:
        raise ValueError("no primary display found; pass device='\\\\.\\DISPLAY1'")
    dm = win32api.EnumDisplaySettings(device, win32con.ENUM_CURRENT_SETTINGS)
    dm.PelsWidth = int(width)
    dm.PelsHeight = int(height)
    if hz:
        dm.DisplayFrequency = int(hz)
    result = win32api.ChangeDisplaySettingsEx(device, dm)
    codes = {
        0: "success",
        1: "restart required",
        -1: "failed — invalid mode",
        -2: "mode not supported",
        -3: "flags not supported",
        -4: "bad parameter",
        -5: "failed to write settings",
    }
    return {
        "device": device,
        "width": width,
        "height": height,
        "result_code": result,
        "result": codes.get(result, str(result)),
    }
