"""Input tools — Click, Type, Scroll, Move, Shortcut, Wait, WaitFor."""

import json
import math
import time
from collections.abc import Callable, Iterator
from typing import Any, Literal

from mcp.types import ToolAnnotations
from windows_mcp.infrastructure import with_analytics
from fastmcp import Context

from windows_mcp.desktop import actions
from windows_mcp.refs import RefStore
from windows_mcp.refs.locator import ElementLocator


WaitForCondition = Literal[
    "text_exists",
    "active_window",
    "element_exists",
    "element_enabled",
    "focused_element",
]


def _resolve_label(desktop: Any, label: int) -> list[int]:
    """Resolve a UI element label to screen coordinates."""
    if desktop.desktop_state is None:
        raise ValueError("Desktop state is empty. Please call Snapshot first.")
    try:
        return list(desktop.get_coordinates_from_label(label))
    except Exception as e:
        raise ValueError(f"Failed to find element with label {label}: {e}")


def _resolve_target(
    desktop: Any,
    loc: list | None,
    label: int | None,
    ref: str | None,
) -> tuple[int, int, str, ElementLocator | None]:
    """Resolve a click target to (x, y, via_note, locator).

    Precedence: ref > label > loc. ref/label resolve through the ref store to a
    live element (fresh coordinates, survives relayout); loc is raw screen
    coordinates with no element identity (locator=None). The `via` note is
    appended to tool responses for transparency.
    """
    if ref is not None:
        locator = desktop.ref_store.resolve(RefStore.parse_ref(ref))
        x, y = desktop._locator_center(locator)
        return x, y, f"@e{locator.ref} ({locator.control_type} {locator.name!r})", locator
    if label is not None:
        locator = desktop.resolve_label_locator(label)
        if locator is not None:
            x, y = desktop._locator_center(locator)
            return (
                x,
                y,
                f"label {label} -> @e{locator.ref} ({locator.control_type} {locator.name!r})",
                locator,
            )
        x, y = _resolve_label(desktop, label)
        return x, y, f"label {label}", None
    if loc is None or len(loc) != 2:
        raise ValueError("Provide ref, label, or loc=[x, y].")
    return loc[0], loc[1], f"({loc[0]},{loc[1]})", None


def _check_method(method: str) -> str:
    normalized = method.strip().lower()
    if normalized not in ("auto", "invoke", "synthetic"):
        raise ValueError("method must be one of: auto, invoke, synthetic")
    return normalized


def _pattern_required(method: str) -> bool:
    """True when the caller forbids the synthetic-input fallback."""
    return method == "invoke"


def _as_bool(value: bool | str, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{name} must be true or false")


def _validate_finite_number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _as_loc(value: list | str | None) -> list | None:
    """Coerce a JSON-stringified list back to a list.

    Claude Desktop strips anyOf schemas and the model serializes lists as
    strings (e.g. '[100, 200]'). Parsing here keeps the tools working.
    """
    if value is None or isinstance(value, list):
        return value
    return json.loads(value)


def _as_point(value: object, name: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be a list of exactly 2 integers [x, y]")
    parsed = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError(f"{name} must contain integers, not booleans")
        if isinstance(item, int):
            parsed.append(item)
            continue
        if isinstance(item, str):
            stripped = item.strip()
            if stripped and stripped.lstrip("+-").isdigit():
                parsed.append(int(stripped))
                continue
        raise ValueError(f"{name} must contain exactly 2 integers")
    return parsed


def _text_matches(value: object | None, expected: str | None) -> bool:
    if expected is None:
        return True
    if value is None:
        return False
    return expected.casefold() in str(value).casefold()


def _metadata_text_matches(metadata: dict[str, object], expected: str | None) -> bool:
    return any(_text_matches(value, expected) for value in metadata.values())


def _iter_nodes(desktop_state: Any) -> Iterator[Any]:
    tree_state = getattr(desktop_state, "tree_state", None)
    if tree_state is None:
        return
    yield from getattr(tree_state, "interactive_nodes", [])
    yield from getattr(tree_state, "scrollable_nodes", [])


def _iter_text_sources(desktop_state: Any) -> Iterator[object]:
    active_window = getattr(desktop_state, "active_window", None)
    if active_window is not None:
        yield active_window.name

    for window in getattr(desktop_state, "windows", []):
        yield window.name

    tree_state = getattr(desktop_state, "tree_state", None)
    if tree_state is None:
        return

    for node in _iter_nodes(desktop_state):
        yield node.name
        yield node.control_type
        yield node.window_name
        for value in getattr(node, "metadata", {}).values():
            yield value

    for node in getattr(tree_state, "dom_informative_nodes", []):
        yield getattr(node, "text", "")


def _node_matches(node: Any, text: str | None, window_name: str | None) -> bool:
    metadata: dict[str, object] = getattr(node, "metadata", {})
    return (
        _text_matches(getattr(node, "name", ""), text)
        or _text_matches(getattr(node, "control_type", ""), text)
        or _metadata_text_matches(metadata, text)
    ) and _text_matches(getattr(node, "window_name", ""), window_name)


def _matches_wait_condition(
    desktop_state: Any,
    condition: WaitForCondition,
    text: str | None,
    window_name: str | None,
) -> tuple[bool, str]:
    if condition == "text_exists":
        for source in _iter_text_sources(desktop_state):
            if _text_matches(source, text):
                return True, f"text {text!r} appeared"
        return False, f"text {text!r} was absent"

    if condition == "active_window":
        expected = window_name or text
        active_window = getattr(desktop_state, "active_window", None)
        active_name = active_window.name if active_window else ""
        if _text_matches(active_name, expected):
            return True, f"active window matched {active_name!r}"
        return False, f"active window was {active_name!r}"

    if condition in {"element_exists", "element_enabled"}:
        for node in _iter_nodes(desktop_state):
            if _node_matches(node, text, window_name):
                return True, f"element matched {getattr(node, 'name', '')!r}"
        return False, "matching element was absent"

    if condition == "focused_element":
        for node in _iter_nodes(desktop_state):
            metadata = getattr(node, "metadata", {})
            if metadata.get("has_focused") and _node_matches(node, text, window_name):
                return True, f"focused element matched {getattr(node, 'name', '')!r}"
        return False, "matching focused element was absent"

    raise ValueError(f"Unsupported WaitFor condition: {condition}")


def _validate_wait_for_args(
    condition: str,
    text: str | None,
    window_name: str | None,
    timeout: float,
    interval: float,
) -> WaitForCondition:
    _validate_finite_number(timeout, "timeout")
    _validate_finite_number(interval, "interval")

    normalized = condition.strip().lower().replace("-", "_")
    aliases = {
        "text": "text_exists",
        "window": "active_window",
        "element": "element_exists",
        "enabled": "element_enabled",
        "focused": "focused_element",
    }
    normalized = aliases.get(normalized, normalized)
    valid_conditions = {
        "text_exists",
        "active_window",
        "element_exists",
        "element_enabled",
        "focused_element",
    }
    if normalized not in valid_conditions:
        raise ValueError(
            "condition must be one of: text_exists, active_window, element_exists, "
            "element_enabled, focused_element"
        )

    if timeout <= 0 or timeout > 120:
        raise ValueError("timeout must be greater than 0 and at most 120 seconds")
    if interval <= 0 or interval > 5:
        raise ValueError("interval must be greater than 0 and at most 5 seconds")

    if normalized == "text_exists" and not text:
        raise ValueError("text is required when condition is text_exists")
    if normalized == "active_window" and not (text or window_name):
        raise ValueError("text or window_name is required when condition is active_window")
    if normalized in {"element_exists", "element_enabled"} and not (text or window_name):
        raise ValueError(
            "text or window_name is required when condition is element_exists or element_enabled"
        )

    return normalized


def register(
    mcp: Any,
    *,
    get_desktop: Callable[[], Any],
    get_analytics: Callable[[], Any],
) -> None:
    @mcp.tool(
        name="Click",
        description=(
            "Performs mouse clicks at specified coordinates [x, y], a UI element's label/id, "
            "or an @eN ref from the latest Snapshot (preferred: resolves to a live element, "
            "survives relayout). "
            "Supports button types: 'left' for selection/activation, 'right' for context menus, 'middle'. "
            "Supports clicks: 0=hover only (no click), 1=single click (select/focus), 2=double click (open/activate). "
            "method controls execution: 'auto' (default) tries UIA patterns (invoke/toggle/select — no cursor "
            "movement, works in background) then falls back to synthetic input; 'invoke' requires a pattern and "
            "never touches the mouse (errors when unsupported); 'synthetic' always uses real mouse input. "
            "Provide one of ref, label, or loc."
        ),
        annotations=ToolAnnotations(
            title="Click",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Click-Tool")
    def click_tool(
        loc: list[int] | str | None = None,
        label: int | None = None,
        ref: str | None = None,
        button: Literal["left", "right", "middle"] = "left",
        clicks: int = 1,
        method: Literal["auto", "invoke", "synthetic"] = "auto",
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        loc = _as_loc(loc)
        method = _check_method(method)
        x, y, via, locator = _resolve_target(desktop, loc, label, ref)
        num_clicks = {0: "Hover", 1: "Single", 2: "Double"}

        if locator is not None and method != "synthetic" and button == "left" and clicks == 1:
            result = actions.activate(locator)
            if result is not None:
                observed = actions.format_observed(result["changes"], result["after"])
                return f"Single left clicked {via} at ({x},{y}) via {result['method']}.{observed}"
            if _pattern_required(method):
                raise ValueError(
                    f"method='invoke' but no UIA pattern applies to {via} "
                    f"({locator.control_type} {locator.name!r}). Use method='auto' to allow "
                    "synthetic input fallback."
                )
        elif _pattern_required(method) and locator is None:
            raise ValueError(
                "method='invoke' requires ref or label targeting a UIA element; "
                "raw loc has no element to invoke."
            )

        desktop.click(loc=[x, y], button=button, clicks=clicks)
        suffix = " (synthetic)" if locator is not None and method == "auto" else ""
        return f"{num_clicks.get(clicks)} {button} clicked at ({x},{y}) on {via}{suffix}."

    @mcp.tool(
        name="Type",
        description="Types text at specified coordinates [x, y], a UI element's label/id, or an @eN ref from the latest Snapshot (preferred). Set clear=True to clear existing text first, False to append. Set press_enter=True to submit after typing. Set caret_position to 'start' (beginning), 'end' (end), or 'idle' (default). method: 'auto' uses UIA ValuePattern (instant, no focus steal) when clear=True and the element supports it; 'invoke' requires it; 'synthetic' always simulates keystrokes. Provide one of ref, label, or loc.",
        annotations=ToolAnnotations(
            title="Type",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Type-Tool")
    def type_tool(
        text: str,
        loc: list[int] | str | None = None,
        label: int | None = None,
        ref: str | None = None,
        clear: bool | str = False,
        caret_position: Literal["start", "idle", "end"] = "idle",
        press_enter: bool | str = False,
        method: Literal["auto", "invoke", "synthetic"] = "auto",
        raw: bool = False,
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        loc = _as_loc(loc)
        method = _check_method(method)
        x, y, via, locator = _resolve_target(desktop, loc, label, ref)
        clear_bool = _as_bool(clear, "clear")
        enter_bool = _as_bool(press_enter, "press_enter")

        # ValuePattern is full-content replace — only correct for clear-and-set,
        # and can't satisfy caret positioning or a trailing Enter. raw=True asks
        # for real keystrokes, so it must stay on the synthetic path too.
        setvalue_ok = (
            locator is not None
            and method != "synthetic"
            and not raw
            and clear_bool
            and not enter_bool
            and caret_position == "idle"
        )
        if setvalue_ok:
            result = actions.fill_value(locator, text)
            if result is not None:
                observed = actions.format_observed(result["changes"], result["after"])
                return f"Typed {text!r} into {via} via setvalue.{observed}"
            if _pattern_required(method):
                raise ValueError(
                    f"method='invoke' but ValuePattern is not supported by {via} "
                    f"({locator.control_type} {locator.name!r}). Use method='auto' to allow "
                    "synthetic typing fallback."
                )
        elif _pattern_required(method) and locator is None:
            raise ValueError(
                "method='invoke' requires ref or label targeting a UIA element; "
                "raw loc has no element."
            )

        desktop.type(
            loc=[x, y],
            text=text,
            caret_position=caret_position,
            clear=clear,
            press_enter=press_enter,
            raw=raw,
        )
        suffix = " (synthetic)" if locator is not None and method == "auto" else ""
        if raw:
            suffix += " (scan code)"
        return f"Typed {text} at ({x},{y}) on {via}{suffix}."

    @mcp.tool(
        name="Scroll",
        description="Scrolls at coordinates [x, y], a UI element's label/id, an @eN ref, or current mouse position if all are omitted. Type: vertical (default) or horizontal. Direction: up/down for vertical, left/right for horizontal. wheel_times controls amount (1 wheel ≈ 3-5 lines). Use for navigating long content, lists, and web pages.",
        annotations=ToolAnnotations(
            title="Scroll",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Scroll-Tool")
    def scroll_tool(
        loc: list[int] | str | None = None,
        label: int | None = None,
        ref: str | None = None,
        type: Literal["horizontal", "vertical"] = "vertical",
        direction: Literal["up", "down", "left", "right"] = "down",
        wheel_times: int = 1,
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        loc = _as_loc(loc)
        via = "current position"
        if ref is not None or label is not None:
            x, y, via, _locator = _resolve_target(desktop, loc, label, ref)
            loc = [x, y]
        if loc and len(loc) != 2:
            raise ValueError("Location must be a list of exactly 2 integers [x, y]")
        response = desktop.scroll(loc, type, direction, wheel_times)
        if response:
            return response
        return (
            f"Scrolled {type} {direction} by {wheel_times} wheel times"
            + f" at ({loc[0]},{loc[1]}) on {via}."
            if loc
            else ""
        )

    @mcp.tool(
        name="Move",
        description=(
            "Moves mouse cursor to coordinates [x, y], a UI element's label/id, or an @eN ref. "
            "Set drag=True to perform a drag-and-drop operation from the current mouse position "
            "to the target coordinates, or provide from_loc=[x, y] to make the drag explicit-start "
            "and atomic in one tool call. Optional duration controls bounded intermediate movement. "
            "Default (drag=False) is a simple cursor move (hover). "
            "Provide one of ref, label, or loc."
        ),
        annotations=ToolAnnotations(
            title="Move",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Move-Tool")
    def move_tool(
        loc: list[int] | str | None = None,
        label: int | None = None,
        ref: str | None = None,
        drag: bool | str = False,
        from_loc: list[int] | str | None = None,
        duration: float | int | str | None = None,
        ctx: Context = None,
    ) -> str:
        desktop = get_desktop()
        loc = _as_loc(loc)
        from_loc = _as_loc(from_loc)
        drag = _as_bool(drag, "drag")
        via = None
        if ref is not None or label is not None:
            x, y, via, _locator = _resolve_target(desktop, loc, label, ref)
            loc = [x, y]
        if not isinstance(loc, list) or len(loc) != 2:
            raise ValueError("Provide ref, label, or loc=[x, y].")
        if from_loc is not None and (not isinstance(from_loc, list) or len(from_loc) != 2):
            raise ValueError("from_loc must be a list of exactly 2 integers [x, y]")
        has_drag_only_options = any(
            value is not None
            for value in (
                from_loc,
                duration,
            )
        )
        if has_drag_only_options and not drag:
            raise ValueError("from_loc and duration require drag=True")
        if drag:
            loc = _as_point(loc, "loc")
            if from_loc is not None:
                from_loc = _as_point(from_loc, "from_loc")
        x, y = loc[0], loc[1]
        if drag:
            result = desktop.drag(
                loc,
                from_loc=from_loc,
                duration=duration,
            )
            start_x, start_y = result["start"]
            effective_duration = result["duration"]
            if effective_duration is None:
                return f"Dragged from ({start_x},{start_y}) to ({x},{y})."
            return (
                f"Dragged from ({start_x},{start_y}) to ({x},{y}) "
                f"over {effective_duration:.3f} seconds."
            )
        else:
            desktop.move(loc)
            return f"Moved the mouse pointer to ({x},{y})."

    @mcp.tool(
        name="Shortcut",
        description='Executes keyboard shortcuts using key combinations separated by +. Examples: "ctrl+c" (copy), "ctrl+v" (paste), "alt+tab" (switch apps), "win+r" (Run dialog), "win" (Start menu), "ctrl+shift+esc" (Task Manager). Set raw=True to send scan codes (KEYEVENTF_SCANCODE) instead of virtual keys — needed by apps that ignore VK input (some games, remote-desktop windows, low-level hooks). Use for quick actions and system commands.',
        annotations=ToolAnnotations(
            title="Shortcut",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Shortcut-Tool")
    def shortcut_tool(shortcut: str, raw: bool = False, ctx: Context = None):
        get_desktop().shortcut(shortcut, raw=raw)
        return f"Pressed {shortcut}{' (scan code)' if raw else ''}."

    @mcp.tool(
        name="Wait",
        description="Pauses execution for specified duration in seconds. Use when waiting for: applications to launch/load, UI animations to complete, page content to render, dialogs to appear, or between rapid actions. Helps ensure UI is ready before next interaction.",
        annotations=ToolAnnotations(
            title="Wait",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Wait-Tool")
    def wait_tool(duration: int, ctx: Context = None) -> str:
        time.sleep(duration)
        return f"Waited for {duration} seconds."

    @mcp.tool(
        name="WaitFor",
        description=(
            "Waits until a UI condition is satisfied, polling the Windows accessibility tree "
            "inside the tool to avoid repeated Snapshot calls. Conditions: text_exists, "
            "active_window, element_exists, element_enabled, focused_element. Provide text "
            "and/or window_name depending on the condition. Set use_dom=True for browser DOM text."
        ),
        annotations=ToolAnnotations(
            title="WaitFor",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "WaitFor-Tool")
    def wait_for_tool(
        condition: str,
        text: str | None = None,
        window_name: str | None = None,
        timeout: float = 10.0,
        interval: float = 0.25,
        use_dom: bool | str = False,
        ctx: Context = None,
    ) -> str:
        normalized = _validate_wait_for_args(
            condition=condition,
            text=text,
            window_name=window_name,
            timeout=timeout,
            interval=interval,
        )
        desktop = get_desktop()
        use_dom_bool = _as_bool(use_dom, "use_dom")
        started_at = time.monotonic()
        deadline = started_at + timeout
        attempts = 0
        last_detail = "condition was not evaluated"

        while True:
            attempts += 1
            desktop_state = desktop.get_state(
                use_vision=False,
                use_dom=use_dom_bool,
                use_ui_tree=True,
                use_annotation=False,
            )
            matched, last_detail = _matches_wait_condition(
                desktop_state=desktop_state,
                condition=normalized,
                text=text,
                window_name=window_name,
            )
            if matched:
                elapsed = time.monotonic() - started_at
                return (
                    f"WaitFor condition '{normalized}' satisfied after "
                    f"{elapsed:.2f}s and {attempts} attempt(s): {last_detail}."
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Timed out after {timeout:.2f}s waiting for '{normalized}': {last_detail}."
                )
            time.sleep(min(interval, remaining))
