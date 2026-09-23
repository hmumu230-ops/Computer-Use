"""Admin tools — Service, Task (scheduled), Env, DevMode."""

import json

from mcp.types import ToolAnnotations
from windows_mcp import safety
from windows_mcp.infrastructure import with_analytics
from windows_mcp.system import devmode, env, service, tasks
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
        name="Service",
        description=(
            "Windows services. action: 'list' (name/status filters), 'get' (name — includes "
            "dependencies), 'start'/'stop'/'restart' (name, force for stop), 'startup_type' "
            "(name + startup_type=Automatic|Manual|Disabled). Stop/disable are gated — "
            "repeat with confirm='<token>'."
        ),
        annotations=ToolAnnotations(
            title="Service",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Service-Tool")
    def service_tool(
        action: str,
        name: str | None = None,
        status: str | None = None,
        startup_type: str | None = None,
        force: bool | str = False,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"list", "get", "start", "stop", "restart", "startup_type"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action != "list" and not name:
            raise ValueError(f"name required for action='{action}'")

        key = f"service.{action}:{name}"
        if action in ("stop", "startup_type"):
            desc = (
                f"stop service {name}"
                if action == "stop"
                else f"set service {name} startup to {startup_type}"
            )
            gated = safety.gate(key, desc, confirm, dangerous=True)
            if gated:
                return gated

        dispatch = {
            "list": lambda: service.list_services(name, status),
            "get": lambda: service.get_service(name),
            "start": lambda: service.start_service(name),
            "stop": lambda: service.stop_service(name, _as_bool(force)),
            "restart": lambda: service.restart_service(name),
            "startup_type": lambda: service.set_startup_type(name, startup_type or "Manual"),
        }
        result = dispatch[action]()
        if action in ("stop", "startup_type"):
            safety.audit(key, str(result)[:200])
        return _fmt(result)

    @mcp.tool(
        name="Task",
        description=(
            "Scheduled tasks. action: 'list' (name/state filters), 'info' (name[, path] — "
            "last/next run, actions), 'run'/'enable'/'disable' (name[, path]), "
            "'create' (name, program, arguments, trigger=once|at_logon|daily|at_startup, "
            "run_level=Limited|Highest), 'delete' (name[, path])."
        ),
        annotations=ToolAnnotations(
            title="Task",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Task-Tool")
    def task_tool(
        action: str,
        name: str | None = None,
        path: str = "\\",
        state: str | None = None,
        program: str | None = None,
        arguments: str = "",
        trigger: str = "once",
        run_level: str = "Limited",
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"list", "info", "run", "enable", "disable", "create", "delete"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action != "list" and not name:
            raise ValueError(f"name required for action='{action}'")

        if action in ("disable", "delete", "create"):
            gated = safety.gate(
                f"task.{action}:{name}",
                f"{action} scheduled task {name}",
                confirm,
                dangerous=True,
            )
            if gated:
                return gated

        dispatch = {
            "list": lambda: tasks.list_tasks(name, state),
            "info": lambda: tasks.task_info(name, path),
            "run": lambda: tasks.run_task(name, path),
            "enable": lambda: tasks.enable_task(name, path),
            "disable": lambda: tasks.disable_task(name, path),
            "create": lambda: tasks.create_task(name, program or "", arguments, trigger, run_level),
            "delete": lambda: tasks.delete_task(name, path),
        }
        if action == "create" and not program:
            raise ValueError("program required for action='create'")
        result = dispatch[action]()
        if action in ("disable", "delete", "create"):
            safety.audit(f"task.{action}", name)
        return _fmt(result)

    @mcp.tool(
        name="Env",
        description=(
            "Environment variables. action: 'get' (name, scope=user|machine), 'set' "
            "(name, value, scope — broadcasts WM_SETTINGCHANGE so new processes see it), "
            "'delete' (name, scope), 'list' (scope). Machine scope needs elevation."
        ),
        annotations=ToolAnnotations(
            title="Env",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Env-Tool")
    def env_tool(
        action: str,
        name: str | None = None,
        value: str | None = None,
        scope: str = "user",
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {"get", "set", "delete", "list"}
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        if action in ("get", "set", "delete") and not name:
            raise ValueError(f"name required for action='{action}'")
        if action == "set" and value is None:
            raise ValueError("value required for action='set'")
        if action in ("set", "delete"):
            gated = safety.gate(
                f"env.{action}:{scope}:{name}",
                f"{action} environment variable {scope}:{name}",
                confirm,
                dangerous=scope == "machine",
            )
            if gated:
                return gated
        dispatch = {
            "get": lambda: env.get(name, scope),
            "set": lambda: env.set_value(name, value, scope),
            "delete": lambda: env.delete(name, scope),
            "list": lambda: env.list_all(scope),
        }
        result = dispatch[action]()
        if action in ("set", "delete"):
            safety.audit(f"env.{action}", f"{scope}:{name}")
        return _fmt(result)

    @mcp.tool(
        name="DevMode",
        description=(
            "Developer-mode and Windows optional features. action: 'developer_mode' (get), "
            "'set_developer_mode' (enabled, needs elevation), 'features' (list optional "
            "features), 'feature' (name — aliases: wsl, hyperv, sandbox, vmplatform, telnet), "
            "'set_feature' (name, enabled — needs elevation, may need reboot), "
            "'explorer_prefs' (get), 'set_explorer_pref' (name=show_file_extensions|"
            "show_hidden_files|show_protected_os_files, enabled)."
        ),
        annotations=ToolAnnotations(
            title="DevMode",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "DevMode-Tool")
    def devmode_tool(
        action: str,
        name: str | None = None,
        enabled: bool | str = True,
        confirm: str | None = None,
        ctx: Context = None,
    ) -> str:
        action = action.strip().lower()
        valid = {
            "developer_mode",
            "set_developer_mode",
            "features",
            "feature",
            "set_feature",
            "explorer_prefs",
            "set_explorer_pref",
        }
        if action not in valid:
            raise ValueError(f"action must be one of: {', '.join(sorted(valid))}")
        enabled_b = _as_bool(enabled)

        gated_actions = {"set_developer_mode", "set_feature"}
        if action in gated_actions:
            target = name or "developer_mode"
            gated = safety.gate(
                f"devmode.{action}:{target}",
                f"{action} {'enable' if enabled_b else 'disable'} {target}",
                confirm,
                dangerous=True,
            )
            if gated:
                return gated

        dispatch = {
            "developer_mode": devmode.get_developer_mode,
            "set_developer_mode": lambda: devmode.set_developer_mode(enabled_b),
            "features": devmode.list_optional_features,
            "feature": lambda: devmode.get_feature(name or ""),
            "set_feature": lambda: devmode.set_feature(name or "", enabled_b),
            "explorer_prefs": devmode.get_explorer_prefs,
            "set_explorer_pref": lambda: devmode.set_explorer_pref(name or "", enabled_b),
        }
        if action in ("feature", "set_feature") and not name:
            raise ValueError(f"name required for action='{action}'")
        if action == "set_explorer_pref" and not name:
            raise ValueError("name required for set_explorer_pref")
        result = dispatch[action]()
        if action in gated_actions:
            safety.audit(f"devmode.{action}", f"{name or 'developer_mode'}={enabled_b}")
        return _fmt(result)
