"""System tools — System (power/session), Window, EventLog, Identity."""

import json

from mcp.types import ToolAnnotations
from windows_mcp import safety
from windows_mcp.infrastructure import with_analytics
from windows_mcp.system import eventlog, identity, power, windows
from fastmcp import Context


def _fmt(result) -> str:
    if isinstance(result, tuple):
        payload, rc = result
        if rc != 0:
            return f"error: {payload}"
        return json.dumps(payload, ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="System",
        description=(
            "System power and session control. action: 'lock' (safe), 'sleep', 'hibernate', "
            "'shutdown', 'restart', 'logoff', 'cancel_shutdown' (abort a pending /t shutdown), "
            "'power_plans', 'get_power_plan', 'set_power_plan' (guid or scheme name), "
            "'battery', 'uptime'. Destructive actions (shutdown/restart/logoff/sleep/hibernate) "
            "require a confirm token when the safety gate is enabled — call once to receive the "
            "token, then repeat with confirm='<token>'."
        ),
        annotations=ToolAnnotations(
            title="System",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "System-Tool")
    def system_tool(
        action: str,
        timeout_sec: int = 0,
        force: bool | str = False,
        plan: str | None = None,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        force_b = force is True or (isinstance(force, str) and force.lower() == "true")

        dangerous = {"shutdown", "restart", "logoff", "sleep", "hibernate"}
        readonly = {"power_plans", "get_power_plan", "battery", "uptime"}
        valid = dangerous | readonly | {"lock", "cancel_shutdown", "set_power_plan"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")

        if action not in readonly:
            # bind every parameter that changes what the action does
            key = f"system.{action}:{safety.digest(timeout_sec, force_b, plan)}"
            gated = safety.gate(
                key, f"System action '{action}'", confirm, dangerous=action in dangerous
            )
            if gated:
                return gated

        dispatch = {
            "lock": power.lock,
            "sleep": power.sleep,
            "hibernate": power.hibernate,
            "shutdown": lambda: power.shutdown(timeout_sec, force_b),
            "restart": lambda: power.restart(timeout_sec, force_b),
            "logoff": power.logoff,
            "cancel_shutdown": power.cancel_shutdown,
            "power_plans": power.list_power_plans,
            "get_power_plan": power.get_active_plan,
            "set_power_plan": lambda: power.set_active_plan(plan or ""),
            "battery": power.battery_status,
            "uptime": power.uptime,
        }
        if action == "set_power_plan" and not plan:
            raise ValueError("plan is required for set_power_plan (guid or scheme name)")
        out, rc = dispatch[action]()
        if action in dangerous and rc == 0:
            safety.audit(
                f"system.{action}:{safety.digest(timeout_sec, force_b, plan)}",
                f"System action '{action}' executed",
            )
        return _fmt((out, rc))

    @mcp.tool(
        name="Window",
        description=(
            "Window management. action: 'list' (all visible windows, optional "
            "window=<substring> filter), 'info', 'minimize', 'maximize', 'restore', "
            "'topmost'/'untopmost', 'move' (x,y,width,height), 'close', 'focus' "
            "(bring to front), 'snap' (side=left|right|up|down, Win+Arrow tiling). "
            "Target a window by hwnd=<int> or window=<title substring> (fails on "
            "ambiguous matches); omit both to use the foreground window."
        ),
        annotations=ToolAnnotations(
            title="Window",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "Window-Tool")
    def window_tool(
        action: str,
        window: str | None = None,
        hwnd: int | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
        side: str = "left",
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {
            "list",
            "info",
            "minimize",
            "maximize",
            "restore",
            "topmost",
            "untopmost",
            "move",
            "close",
            "focus",
            "snap",
        }
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        resolved_hwnd: int | None = None
        if action == "close":
            # resolve the target *before* gating so the token binds the actual
            # hwnd that gets closed (title-string matching would be a TOCTOU —
            # the window set can change between gate and dispatch)
            resolved_hwnd = windows._resolve_window(window, hwnd)
            gated = safety.gate(
                f"window.close:{resolved_hwnd}",
                f"close window hwnd={resolved_hwnd}",
                confirm,
                dangerous=True,
            )
            if gated:
                return gated
        if action == "list":
            return _fmt(windows.list_windows(title_filter=window))
        dispatch = {
            "info": lambda: windows.window_info(window, hwnd),
            "minimize": lambda: windows.set_state(window, "minimize", hwnd),
            "maximize": lambda: windows.set_state(window, "maximize", hwnd),
            "restore": lambda: windows.set_state(window, "restore", hwnd),
            "topmost": lambda: windows.set_topmost(window, True, hwnd),
            "untopmost": lambda: windows.set_topmost(window, False, hwnd),
            "move": lambda: windows.move_resize(window, x, y, width, height, hwnd),
            "close": lambda: windows.close_window(None, resolved_hwnd),
            "focus": lambda: windows.bring_to_front(window, hwnd),
            "snap": lambda: windows.snap(window, side, hwnd),
        }
        result = dispatch[action]()
        if action == "close":
            safety.audit("window.close", f"closed {result}")
        return _fmt(result)

    @mcp.tool(
        name="EventLog",
        description=(
            "Read Windows Event Logs. action: 'query' (log_name='Application'|'System'|..., "
            "max_events, level: 1=Critical 2=Error 3=Warning 4=Information, provider filter), "
            "'list_logs' (logs with records)."
        ),
        annotations=ToolAnnotations(
            title="EventLog",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "EventLog-Tool")
    def eventlog_tool(
        action: str = "query",
        log_name: str = "Application",
        max_events: int = 20,
        level: int | None = None,
        provider: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        if action == "query":
            return _fmt(eventlog.query(log_name, max_events, level, provider))
        if action == "list_logs":
            return _fmt(eventlog.list_logs())
        raise ValueError("action must be 'query' or 'list_logs'")

    @mcp.tool(
        name="Identity",
        description=(
            "Report who the server runs as: user, elevation status, group membership. "
            "Elevation determines whether admin windows and privileged operations are reachable."
        ),
        annotations=ToolAnnotations(
            title="Identity",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics, "Identity-Tool")
    def identity_tool(ctx: Context = None) -> str:
        return _fmt(identity.whoami())
