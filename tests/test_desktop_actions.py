"""Pattern-first action tests — observe/diff/format + the _CLICK_ORDER ladder.

UIA patterns are faked with stubs; only `GetPattern` dispatch is monkeypatched
where needed.
"""

from __future__ import annotations

import windows_mcp.uia as uia
from windows_mcp.desktop import actions
from windows_mcp.refs.locator import ElementLocator


class FakeRect:
    left, top = 10, 20

    def width(self):
        return 100

    def height(self):
        return 30


class FakePattern:
    """Callable pattern recording invocations and returning a fixed result."""

    def __init__(self, result=True, **fields):
        self._result = result
        for k, v in fields.items():
            setattr(self, k, v)
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.calls.append(name)
            if name in ("Expand",):
                self.ExpandCollapseState = int(uia.ExpandCollapseState.Expanded)
            if name in ("Collapse",):
                self.ExpandCollapseState = int(uia.ExpandCollapseState.Collapsed)
            return self._result

        return call


class FakeControl:
    """Control stub with a pattern table {PatternId: FakePattern | None}."""

    def __init__(self, patterns=None, name="btn", alive=True):
        self.Name = name
        self.IsEnabled = True
        self.HasKeyboardFocus = False
        self.IsOffscreen = False
        self.BoundingRectangle = FakeRect()
        self._patterns = patterns or {}
        self._alive = alive
        self._focus = False

    def GetPattern(self, pattern_id):  # noqa: N802
        if not self._alive:
            raise RuntimeError("dead")
        return self._patterns.get(pattern_id)

    def SetFocus(self):  # noqa: N802
        if not self._alive:
            raise RuntimeError("dead")
        self._focus = True


def _locator(control, control_type="ButtonControl", synthetic=False) -> ElementLocator:
    return ElementLocator(control=control, control_type=control_type, synthetic=synthetic)


INVOKE = uia.PatternId.InvokePattern
TOGGLE = uia.PatternId.TogglePattern
SELECT = uia.PatternId.SelectionItemPattern
VALUE = uia.PatternId.ValuePattern
EXPAND = uia.PatternId.ExpandCollapsePattern
LEGACY = uia.PatternId.LegacyIAccessiblePattern


# -- observe/diff/format ----------------------------------------------------


def test_observe_element_dead_returns_empty():
    assert actions.observe_element(None) == {}

    class Dead:
        @property
        def Name(self):  # noqa: N802
            raise RuntimeError("gone")

    assert actions.observe_element(Dead()) == {}


def test_observe_collects_available_fields():
    control = FakeControl(patterns={TOGGLE: FakePattern(ToggleState=1)})
    state = actions.observe_element(control)
    assert state["name"] == "btn"
    assert state["enabled"] is True
    assert "toggle" in state


def test_diff_state_detects_changes_and_disappearance():
    before = {"name": "a", "enabled": True}
    after = {"name": "a", "enabled": False, "focused": True}
    diff = actions.diff_state(before, after)
    assert diff["enabled"] == "True -> False"
    assert diff["focused"] == "None -> True"
    assert "name" not in diff
    assert actions.diff_state(before, {}) == {"element": "disappeared"}


def test_format_observed_variants():
    assert "disappeared" in actions.format_observed({}, {})
    assert "no visible" in actions.format_observed({}, {"x": 1})
    assert "toggle" in actions.format_observed({"toggle": "x -> y"}, {"x": 1})


# -- activate ladder ---------------------------------------------------------


def test_activate_button_prefers_invoke():
    inv = FakePattern()
    control = FakeControl(patterns={INVOKE: inv, LEGACY: FakePattern()})
    result = actions.activate(_locator(control, "ButtonControl"))
    assert result is not None
    assert result["method"] == "invoke"
    assert inv.calls == ["Invoke"]


def test_activate_checkbox_prefers_toggle():
    tog = FakePattern()
    inv = FakePattern()
    control = FakeControl(patterns={TOGGLE: tog, INVOKE: inv})
    result = actions.activate(_locator(control, "CheckBoxControl"))
    assert result["method"] == "toggle"
    assert inv.calls == []


def test_activate_falls_through_when_pattern_fails():
    inv = FakePattern(result=False)
    legacy = FakePattern()
    control = FakeControl(patterns={INVOKE: inv, LEGACY: legacy})
    result = actions.activate(_locator(control, "ButtonControl"))
    assert result["method"] == "legacy"


def test_activate_returns_none_when_nothing_applies():
    control = FakeControl(patterns={})
    assert actions.activate(_locator(control, "ButtonControl")) is None


def test_activate_synthetic_short_circuits():
    control = FakeControl(patterns={INVOKE: FakePattern()})
    assert actions.activate(_locator(control, synthetic=True)) is None
    assert actions.activate(ElementLocator(control=None, synthetic=True)) is None


def test_activate_edit_prefers_focus():
    control = FakeControl(patterns={INVOKE: FakePattern()})
    result = actions.activate(_locator(control, "EditControl"))
    assert result["method"] == "focus"
    assert control._focus is True


def test_activate_expand_toggles_state():
    pat = FakePattern(ExpandCollapseState=int(uia.ExpandCollapseState.Collapsed))
    control = FakeControl(patterns={EXPAND: pat})
    result = actions.activate(_locator(control, "ComboBoxControl"))
    assert result["method"] == "expand"
    assert "Expand" in pat.calls


def test_activate_select_already_selected_noop():
    pat = FakePattern(IsSelected=True)
    control = FakeControl(patterns={SELECT: pat})
    result = actions.activate(_locator(control, "ListItemControl"))
    assert result["method"] == "select"
    assert pat.calls == []  # no Select() dispatched


def test_activate_reports_state_changes():
    tog = FakePattern(ToggleState=0)
    control = FakeControl(patterns={TOGGLE: tog})

    # after Toggle() the observed ToggleState should flip
    original = FakePattern.__getattr__

    def flip(self, name):
        f = original(self, name)
        if name == "Toggle":
            def toggled(*a, **k):
                self.calls.append(name)
                self.ToggleState = 1
                return True

            return toggled
        return f

    import unittest.mock as mock

    with mock.patch.object(FakePattern, "__getattr__", flip):
        result = actions.activate(_locator(control, "CheckBoxControl"))
    assert result["method"] == "toggle"
    assert "toggle" in result["changes"]


# -- fill_value ---------------------------------------------------------------


def test_fill_value_uses_setvalue():
    val = FakePattern(Value="old")
    control = FakeControl(patterns={VALUE: val})
    result = actions.fill_value(_locator(control, control_type="EditControl"), "hello")
    assert result is not None
    assert result["method"] == "setvalue"
    assert "SetValue" in val.calls


def test_fill_value_none_without_pattern():
    control = FakeControl(patterns={})
    assert actions.fill_value(_locator(control), "x") is None


def test_fill_value_none_on_failure():
    val = FakePattern(result=False)
    control = FakeControl(patterns={VALUE: val})
    assert actions.fill_value(_locator(control), "x") is None


def test_fill_value_synthetic_short_circuits():
    control = FakeControl(patterns={VALUE: FakePattern()})
    assert actions.fill_value(_locator(control, synthetic=True), "x") is None
