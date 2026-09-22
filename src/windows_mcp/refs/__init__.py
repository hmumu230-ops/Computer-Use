"""Stable element references ("refs") for UI elements.

A ref (``@eN``) is a durable handle to a UI element captured during a Snapshot.
Unlike the legacy numeric ``label`` (a positional index into the last tree
capture), a ref is never reused across snapshots and resolves through element
identity — live UIA element probe, RuntimeId comparison, AutomationId subtree
search, and a structural index-path fallback — so it keeps working across
window moves, relayouts, and mild UI churn.
"""

from windows_mcp.refs.locator import ElementLocator
from windows_mcp.refs.store import RefError, RefStore

__all__ = ["ElementLocator", "RefError", "RefStore"]
