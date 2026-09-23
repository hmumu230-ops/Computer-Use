"""Pattern-first element actions with post-action observation.

When a ref/label resolves to a live UIA control we try the semantic control
pattern (Invoke / Toggle / SelectionItem / Value / ExpandCollapse /
LegacyIAccessible) before synthetic mouse input. Pattern calls don't move the
cursor, don't need the window in the foreground, and fire the same handlers a
real click fires — strictly better when available.

Every action observes the element's state before and after, returning the
fields that actually changed so the caller sees what happened — not just that
a call was dispatched.
"""

from __future__ import annotations

import logging
from typing import Any

import windows_mcp.uia as uia
from windows_mcp.refs.locator import ElementLocator

logger = logging.getLogger(__name__)

# Methods, in preference order, for a plain left click per control type.
# Names map to `_try_<method>` handlers below. Control types not listed use
# _DEFAULT_CLICK_ORDER.
_CLICK_ORDER: dict[str, tuple[str, ...]] = {
    "CheckBoxControl": ("toggle", "invoke", "select", "legacy"),
    "RadioButtonControl": ("select", "toggle", "invoke", "legacy"),
    "ListItemControl": ("select", "invoke", "legacy"),
    "TabItemControl": ("select", "invoke", "legacy"),
    "TreeItemControl": ("select", "invoke", "legacy"),
    "DataItemControl": ("select", "invoke", "legacy"),
    "ComboBoxControl": ("expand", "select", "invoke", "legacy"),
    "MenuItemControl": ("invoke", "expand", "legacy"),
    "SplitButtonControl": ("invoke", "expand", "legacy"),
    "ButtonControl": ("invoke", "toggle", "legacy"),
    "HyperlinkControl": ("invoke", "legacy"),
    "ImageControl": ("invoke", "select", "legacy"),
    "EditControl": ("focus", "invoke", "legacy"),
    "DocumentControl": ("focus", "invoke", "legacy"),
    "TextControl": ("invoke", "select", "legacy"),
}
_DEFAULT_CLICK_ORDER: tuple[str, ...] = ("invoke", "toggle", "select", "legacy")


# -- element state observation -----------------------------------------------


def observe_element(control: Any) -> dict[str, Any]:
    """Read a bounded set of state fields from a live UIA control.

    Returns {} for a dead/unprobed element — callers compare pre/post dicts.
    """
    state: dict[str, Any] = {}
    if control is None:
        return state
    try:
        state["name"] = control.Name
    except Exception:
        return state  # element died — treat as gone
    try:
        rect = control.BoundingRectangle
        state["rect"] = (rect.left, rect.top, rect.width(), rect.height())
    except Exception:
        pass
    for prop, key in (
        ("IsEnabled", "enabled"),
        ("HasKeyboardFocus", "focused"),
        ("IsOffscreen", "offscreen"),
    ):
        try:
            state[key] = bool(getattr(control, prop))
        except Exception:
            pass
    toggle = control.GetPattern(uia.PatternId.TogglePattern)
    if toggle is not None:
        try:
            state["toggle"] = uia.ToggleState(toggle.ToggleState).name
        except Exception:
            try:
                state["toggle"] = int(toggle.ToggleState)
            except Exception:
                pass
    value = control.GetPattern(uia.PatternId.ValuePattern)
    if value is not None:
        try:
            state["value"] = value.Value
        except Exception:
            pass
    expand = control.GetPattern(uia.PatternId.ExpandCollapsePattern)
    if expand is not None:
        try:
            state["expand"] = uia.ExpandCollapseState(expand.ExpandCollapseState).name
        except Exception:
            try:
                state["expand"] = int(expand.ExpandCollapseState)
            except Exception:
                pass
    selection = control.GetPattern(uia.PatternId.SelectionItemPattern)
    if selection is not None:
        try:
            state["selected"] = bool(selection.IsSelected)
        except Exception:
            pass
    range_value = control.GetPattern(uia.PatternId.RangeValuePattern)
    if range_value is not None:
        try:
            state["range_value"] = range_value.Value
        except Exception:
            pass
    return state


def diff_state(before: dict[str, Any], after: dict[str, Any]) -> dict[str, str]:
    """Fields that changed between two observations, as 'old -> new'."""
    diff: dict[str, str] = {}
    if not after and before:
        return {"element": "disappeared"}
    for key, new in after.items():
        old = before.get(key)
        if old != new:
            diff[key] = f"{old!r} -> {new!r}"
    return diff


def format_observed(changes: dict[str, str], after: dict[str, Any]) -> str:
    """Human/LLM-readable observation suffix for tool responses."""
    if not after:
        return " observed: element disappeared after the action."
    if changes:
        fields = ", ".join(f"{k}: {v}" for k, v in changes.items())
        return f" observed: {fields}."
    return " observed: no visible state change."


# -- pattern execution --------------------------------------------------------


def _scroll_into_view(control: Any) -> None:
    """Best-effort ScrollIntoView so offscreen items become actionable."""
    try:
        if getattr(control, "IsOffscreen", False):
            item = control.GetPattern(uia.PatternId.ScrollItemPattern)
            if item is not None:
                item.ScrollIntoView(waitTime=0)
    except Exception:
        pass


def _try_invoke(control: Any) -> bool:
    pattern = control.GetPattern(uia.PatternId.InvokePattern)
    return pattern is not None and bool(pattern.Invoke(waitTime=0))


def _try_toggle(control: Any) -> bool:
    pattern = control.GetPattern(uia.PatternId.TogglePattern)
    return pattern is not None and bool(pattern.Toggle(waitTime=0))


def _try_select(control: Any) -> bool:
    pattern = control.GetPattern(uia.PatternId.SelectionItemPattern)
    if pattern is None:
        return False
    try:
        if pattern.IsSelected:
            return True  # already selected — click would be a no-op anyway
    except Exception:
        pass
    return bool(pattern.Select(waitTime=0))


def _try_expand(control: Any) -> bool:
    pattern = control.GetPattern(uia.PatternId.ExpandCollapsePattern)
    if pattern is None:
        return False
    try:
        state = uia.ExpandCollapseState(pattern.ExpandCollapseState)
    except Exception:
        return False
    if state == uia.ExpandCollapseState.Collapsed:
        return bool(pattern.Expand(waitTime=0))
    if state == uia.ExpandCollapseState.Expanded:
        return bool(pattern.Collapse(waitTime=0))
    return False


def _try_legacy(control: Any) -> bool:
    pattern = control.GetPattern(uia.PatternId.LegacyIAccessiblePattern)
    if pattern is None:
        return False
    try:
        pattern.DoDefaultAction()
        return True
    except Exception:
        return False


def _try_focus(control: Any) -> bool:
    try:
        control.SetFocus()
        return True
    except Exception:
        return False


_PATTERN_HANDLERS = {
    "invoke": _try_invoke,
    "toggle": _try_toggle,
    "select": _try_select,
    "expand": _try_expand,
    "legacy": _try_legacy,
    "focus": _try_focus,
}


def activate(
    locator: ElementLocator,
    *,
    observe: bool = True,
) -> dict[str, Any] | None:
    """Try pattern-based activation on the locator's live control.

    Returns a result dict {method, before, after, changes} on success, or
    None when no pattern applies / all failed — caller should then fall back
    to synthetic input. The element being gone after the action is a valid
    outcome (e.g. a Close button) and still returns a result.
    """
    control = locator.control
    if control is None or locator.synthetic:
        return None
    order = _CLICK_ORDER.get(locator.control_type, _DEFAULT_CLICK_ORDER)
    before = observe_element(control) if observe else {}
    _scroll_into_view(control)
    for method in order:
        handler = _PATTERN_HANDLERS.get(method)
        if handler is None:
            continue
        try:
            if handler(control):
                after = observe_element(control) if observe else {}
                return {
                    "method": method,
                    "before": before,
                    "after": after,
                    "changes": diff_state(before, after),
                }
        except Exception:
            continue
    return None


def fill_value(
    locator: ElementLocator,
    text: str,
    *,
    observe: bool = True,
) -> dict[str, Any] | None:
    """Try ValuePattern.SetValue — full-content replace, no focus needed.

    Returns a result dict on success, None when the pattern is unsupported —
    caller falls back to synthetic typing. SetValue replaces the element's
    entire value, so it is only correct for clear-and-set semantics.
    """
    control = locator.control
    if control is None or locator.synthetic:
        return None
    pattern = control.GetPattern(uia.PatternId.ValuePattern)
    if pattern is None:
        return None
    before = observe_element(control) if observe else {}
    try:
        if not pattern.SetValue(text, waitTime=0):
            return None
    except Exception:
        return None
    after = observe_element(control) if observe else {}
    return {
        "method": "setvalue",
        "before": before,
        "after": after,
        "changes": diff_state(before, after),
    }
