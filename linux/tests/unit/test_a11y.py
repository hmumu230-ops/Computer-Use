"""a11y layer against FakeAtspi: walk, verbs, locator, actions."""
import pytest

import a11y
from conftest import FakeNode
from errors import StaleRef, UnsupportedPlatform


def _btn(name="OK", actions=None, **kw):
    acts = actions if actions is not None else [("click", True)]
    return FakeNode(role="push button", name=name, actions=acts, **kw)


def test_walk_finds_interesting(fake_atspi):
    app = fake_atspi(children=[
        FakeNode(role="frame", name="W", children=[_btn("OK"), _btn("Cancel")]),
        FakeNode(role="filler", name="", children=[
            FakeNode(role="static text", name="hi")])])
    nodes = a11y.walk(app)
    roles = sorted(n.role for n in nodes)
    assert roles == ["push button", "push button"]
    assert {n.name for n in nodes} == {"OK", "Cancel"}


def test_walk_skips_defunct(fake_atspi):
    dead = _btn("Ghost")
    dead.dead = True
    app = fake_atspi(children=[dead, _btn("Live")])
    nodes = a11y.walk(app)
    assert [n.name for n in nodes] == ["Live"]


def test_index_path_and_resolve(fake_atspi):
    inner = _btn("Deep")
    app = fake_atspi(children=[
        FakeNode(role="frame", name="F", children=[
            FakeNode(role="panel", children=[inner])])])
    ax = a11y.describe(inner)
    node = a11y.resolve_locator(ax.bus_name, ax.pid, ax.index_path,
                                ax.role, ax.name)
    assert node is inner


def test_resolve_locator_dead_returns_none(fake_atspi):
    inner = _btn("Deep")
    app = fake_atspi(children=[inner])
    ax = a11y.describe(inner)
    inner.dead = True
    assert a11y.resolve_locator(ax.bus_name, ax.pid, ax.index_path,
                              ax.role, ax.name) is None


def test_index_path_drift_fingerprint_search(fake_atspi):
    """If the index path lands on a different node, fingerprint search
    finds the real one elsewhere in the app tree."""
    target = _btn("Save")
    other = _btn("Other")
    app = fake_atspi(children=[
        FakeNode(role="panel", children=[other]),
        FakeNode(role="panel", children=[target])])
    ax = a11y.describe(target)
    # corrupt the path to point at `other`
    bad_path = list(ax.index_path)
    bad_path[0] = 0
    node = a11y.resolve_locator(ax.bus_name, ax.pid, tuple(bad_path),
                                ax.role, ax.name)
    assert node is target


def test_act_press_uses_named_action(fake_atspi):
    calls = []
    btn = _btn(actions=[("Press", lambda: calls.append(1) or True)])
    app = fake_atspi(children=[btn])
    r = a11y.act(btn, "press")
    assert r["method"] == "action" and r["action"] == "Press"
    assert calls == [1]


def test_act_normalizes_toolkit_names(fake_atspi):
    """Qt 'Show Menu' / Chromium 'doDefault' normalize to our verbs."""
    btn = _btn(actions=[("doDefault", True)])
    fake_atspi(children=[btn])
    assert a11y.act(btn, "press")["action"] == "doDefault"

    menu = FakeNode(role="push button", name="File",
                    actions=[("Show Menu", True)])
    fake_atspi(children=[menu])
    assert a11y.act(menu, "showmenu")["action"] == "Show Menu"


def test_act_falls_back_to_index0(fake_atspi):
    btn = _btn(actions=[("weirdName", True)])
    fake_atspi(children=[btn])
    r = a11y.act(btn, "press")
    assert r["action"] == "default(index0)"


def test_act_descendant_bfs(fake_atspi):
    """GTK MenuButton: outer push button 0 actions; descendant has click."""
    inner = FakeNode(role="toggle button", name="",
                     actions=[("click", True)])
    outer = _btn(name="Menu", actions=[], children=[inner])
    fake_atspi(children=[outer])
    r = a11y.act(outer, "press")
    assert r["method"] == "descendant-action"


def test_act_unsupported_raises(fake_atspi):
    node = FakeNode(role="icon", name="i", ifaces=["component"])
    fake_atspi(children=[node])
    with pytest.raises(UnsupportedPlatform):
        a11y.act(node, "press")


def test_act_on_dead_is_stale(fake_atspi):
    btn = _btn()
    fake_atspi(children=[btn])
    btn.dead = True
    with pytest.raises(StaleRef):
        a11y.act(btn, "press")


def test_set_text_verified(fake_atspi):
    e = FakeNode(role="entry", name="Name",
                 states={"enabled", "sensitive", "showing", "editable"},
                 ifaces=["component", "text", "editabletext"])
    fake_atspi(children=[e])
    r = a11y.set_text(e, "hello")
    assert r["verified"] is True and e._text == "hello"


def test_set_text_not_editable(fake_atspi):
    lbl = FakeNode(role="label", name="static", ifaces=["component", "text"])
    fake_atspi(children=[lbl])
    with pytest.raises(UnsupportedPlatform):
        a11y.set_text(lbl, "x")


def test_set_value_roundtrip(fake_atspi):
    s = FakeNode(role="slider", name="Vol", ifaces=["component", "value"])
    fake_atspi(children=[s])
    r = a11y.set_value(s, 42.0)
    assert r["verified"] is True and s._value == 42.0


def test_effective_name_labelled_by(fake_atspi):
    class Rel:
        def get_relation_type(self):
            return a11y.ats().RelationType.LABELLED_BY
        def get_n_targets(self):
            return 1
        def get_target(self, i):
            return FakeNode(role="label", name="User name")

    node = FakeNode(role="entry", name="", ifaces=["component", "text"])
    node.get_relation_set = lambda: [Rel()]
    fake_atspi(children=[node])
    assert a11y.effective_name(node) == "User name"


def test_find_elements_dfs(fake_atspi):
    app = fake_atspi(children=[
        _btn("Open"), _btn("Close"),
        FakeNode(role="check box", name="Agree")])
    hits = a11y.find_elements(app, role="push button")
    assert {h.name for h in hits} == {"Open", "Close"}
    hits = a11y.find_elements(app, name="agr")
    assert [h.name for h in hits] == ["Agree"]
