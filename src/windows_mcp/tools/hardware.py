"""Hardware tools — Audio, Display, Device (PnP/printers), Network."""

import json

from mcp.types import ToolAnnotations
from windows_mcp import safety
from windows_mcp.infrastructure import with_analytics
from windows_mcp.system import audio, device, display, network
from fastmcp import Context


def _fmt(result) -> str:
    if isinstance(result, tuple):
        payload, rc = result
        if rc != 0:
            return f"error: {payload}"
        return json.dumps(payload, ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


def _as_bool(v) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="Audio",
        description=(
            "Audio control via Core Audio API. action: 'get' (master volume+mute), "
            "'set' (level=0-100), 'mute'/'unmute', 'devices' (render devices + default), "
            "'sessions' (per-app volumes), 'set_session' (process='chrome.exe', level=0-100)."
        ),
        annotations=ToolAnnotations(
            title="Audio",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Audio-Tool")
    def audio_tool(
        action: str,
        level: int | None = None,
        process: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"get", "set", "mute", "unmute", "devices", "sessions", "set_session"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action == "set" and level is None:
            raise ValueError("level (0-100) required for action='set'")
        if action == "set_session" and (process is None or level is None):
            raise ValueError("process and level required for action='set_session'")
        dispatch = {
            "get": audio.get_volume,
            "set": lambda: audio.set_volume(level),
            "mute": lambda: audio.set_mute(True),
            "unmute": lambda: audio.set_mute(False),
            "devices": audio.list_devices,
            "sessions": audio.list_sessions,
            "set_session": lambda: audio.set_session_volume(process, level),
        }
        return _fmt(dispatch[action]())

    @mcp.tool(
        name="Display",
        description=(
            "Display control. action: 'brightness' (get), 'set_brightness' (level 0-100, "
            "laptop panels only), 'modes' (per-monitor resolution/hz/primary), "
            "'set_resolution' (width, height, optional hz, optional device='\\\\.\\DISPLAY1')."
        ),
        annotations=ToolAnnotations(
            title="Display",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Display-Tool")
    def display_tool(
        action: str,
        level: int | None = None,
        width: int | None = None,
        height: int | None = None,
        hz: int | None = None,
        device_name: str | None = None,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"brightness", "set_brightness", "modes", "set_resolution"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action == "set_resolution":
            if width is None or height is None:
                raise ValueError("width and height required for set_resolution")
            gated = safety.gate(
                f"display.set_resolution:{width}x{height}",
                f"change display resolution to {width}x{height}",
                confirm,
                dangerous=True,
            )
            if gated:
                return gated
            result = display.set_resolution(device_name, width, height, hz)
            safety.audit("display.set_resolution", str(result))
            return _fmt(result)
        if action == "set_brightness":
            gated = safety.gate(
                f"display.set_brightness:{level}",
                f"set display brightness to {level}",
                confirm,
                dangerous=False,
            )
            if gated:
                return gated
        dispatch = {
            "brightness": display.get_brightness,
            "set_brightness": lambda: display.set_brightness(level if level is not None else 50),
            "modes": display.list_modes,
        }
        return _fmt(dispatch[action]())

    @mcp.tool(
        name="Device",
        description=(
            "PnP devices and printers. action: 'list' (device_class='Mouse'|'Keyboard'|..., "
            "status='OK'|'Error'), 'enable'/'disable' (instance_id, needs elevation), "
            "'printers', 'set_default_printer' (name)."
        ),
        annotations=ToolAnnotations(
            title="Device",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Device-Tool")
    def device_tool(
        action: str,
        device_class: str | None = None,
        status: str | None = None,
        instance_id: str | None = None,
        name: str | None = None,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"list", "enable", "disable", "printers", "set_default_printer"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action in ("enable", "disable"):
            if not instance_id:
                raise ValueError("instance_id required (see action='list')")
            gated = safety.gate(
                f"device.{action}:{instance_id}",
                f"{action} device {instance_id}",
                confirm,
                dangerous=action == "disable",
            )
            if gated:
                return gated
            result = device.set_device_state(instance_id, action == "enable")
            safety.audit(f"device.{action}", instance_id)
            return _fmt(result)
        if action == "set_default_printer":
            if not name:
                raise ValueError("name required for set_default_printer")
            gated = safety.gate(
                f"device.set_default_printer:{name}",
                f"set default printer to {name}",
                confirm,
                dangerous=False,
            )
            if gated:
                return gated
            return _fmt(device.set_default_printer(name))
        if action == "printers":
            return _fmt(device.list_printers())
        return _fmt(device.list_devices(device_class, status))

    @mcp.tool(
        name="Network",
        description=(
            "Network status and config. action: 'adapters', 'ip' (addresses + default gateway), "
            "'profiles' (public/private per connection), 'wifi' (current wlan), 'wifi_networks' "
            "(scan), 'proxy' (get), 'set_proxy' (server='host:port', enabled, bypass), "
            "'test' (host, optional port — TCP/ping reachability)."
        ),
        annotations=ToolAnnotations(
            title="Network",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    @with_analytics(get_analytics(), "Network-Tool")
    def network_tool(
        action: str,
        host: str | None = None,
        port: int | None = None,
        server: str | None = None,
        enabled: bool | str = True,
        bypass: str | None = None,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {
            "adapters",
            "ip",
            "profiles",
            "wifi",
            "wifi_networks",
            "proxy",
            "set_proxy",
            "test",
        }
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action == "set_proxy":
            gated = safety.gate(
                f"network.set_proxy:{safety.digest(server, _as_bool(enabled), bypass)}",
                f"set system proxy to {server!r} enabled={enabled}",
                confirm,
                dangerous=True,
            )
            if gated:
                return gated
            result = network.set_proxy(server, enabled=_as_bool(enabled), bypass=bypass)
            safety.audit("network.set_proxy", f"server={server} enabled={enabled}")
            return _fmt(result)
        if action == "test":
            if not host:
                raise ValueError("host required for action='test'")
            return _fmt(network.test_connection(host, port))
        dispatch = {
            "adapters": network.list_adapters,
            "ip": network.ip_info,
            "profiles": network.connection_profiles,
            "wifi": network.wifi_status,
            "wifi_networks": network.wifi_networks,
            "proxy": network.get_proxy,
        }
        return _fmt(dispatch[action]())
