"""Infrastructure layer — cross-cutting concerns: auth, security, analytics, config, oauth.

Exports are resolved lazily (PEP 562): importing this package does not pull
starlette (auth/security/oauth) or the analytics stack, which matters for
cold-start latency on CLI paths that never serve HTTP.
"""

import importlib

_LAZY = {
    "AuthKeyMiddleware": "windows_mcp.infrastructure.auth",
    "OAuthOnlyMiddleware": "windows_mcp.infrastructure.auth",
    "is_loopback_host": "windows_mcp.infrastructure.auth",
    "IPAllowlistMiddleware": "windows_mcp.infrastructure.security",
    "parse_ip_allowlist": "windows_mcp.infrastructure.security",
    "validate_url": "windows_mcp.infrastructure.security",
    "Analytics": "windows_mcp.infrastructure.analytics",
    "PostHogAnalytics": "windows_mcp.infrastructure.analytics",
    "with_analytics": "windows_mcp.infrastructure.analytics",
    "WindowsMCPConfig": "windows_mcp.infrastructure.config",
    "ServerConfig": "windows_mcp.infrastructure.config",
    "SecurityConfig": "windows_mcp.infrastructure.config",
    "ToolsConfig": "windows_mcp.infrastructure.config",
    "CONFIG_DIR": "windows_mcp.infrastructure.config",
    "CONFIG_FILE": "windows_mcp.infrastructure.config",
    "discover_config_path": "windows_mcp.infrastructure.config",
    "load_config": "windows_mcp.infrastructure.config",
    "write_config": "windows_mcp.infrastructure.config",
    "OAuthStore": "windows_mcp.infrastructure.oauth",
    "build_oauth_routes": "windows_mcp.infrastructure.oauth",
    "validate_oauth_token": "windows_mcp.infrastructure.oauth",
    "install_selfpipe_guard": "windows_mcp.infrastructure.eventloop",
}

__all__ = [
    "AuthKeyMiddleware",
    "OAuthOnlyMiddleware",
    "is_loopback_host",
    "IPAllowlistMiddleware",
    "parse_ip_allowlist",
    "validate_url",
    "Analytics",
    "PostHogAnalytics",
    "with_analytics",
    "WindowsMCPConfig",
    "ServerConfig",
    "SecurityConfig",
    "ToolsConfig",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "discover_config_path",
    "load_config",
    "write_config",
    "OAuthStore",
    "build_oauth_routes",
    "validate_oauth_token",
    "install_selfpipe_guard",
]


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
