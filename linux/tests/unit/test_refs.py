"""RefStore: generation scoping, staleness, synthetic refs."""
import pytest

import refs
from errors import StaleRef


def test_window_ref_registered():
    s = refs.RefStore()
    s.new_generation()
    w = s.add_window(handle=1234, backend="x11", title="Term")
    assert w.ref == "@w1"
    assert s.get("@w1") is w


def test_generation_mismatch_is_stale():
    s = refs.RefStore()
    s.new_generation()
    s.add_element(role="push button", name="OK", node=object())
    s.new_generation()   # new snapshot clears + bumps
    with pytest.raises(StaleRef):
        s.get("@e1")


def test_unknown_ref_stale():
    s = refs.RefStore()
    s.new_generation()
    with pytest.raises(StaleRef):
        s.get("@e99")


def test_synthetic_ref_resolves_without_node():
    s = refs.RefStore()
    s.new_generation()
    el = s.add_synthetic({"x": 1, "y": 2, "w": 3, "h": 4}, "Found")
    out = s.resolve_element("@e1", resolver=lambda loc: None)
    assert out is el


def test_resolve_element_reresolves_dead_node():
    s = refs.RefStore()
    s.new_generation()

    class Dead:
        def get_state_set(self):
            raise RuntimeError("UnknownObject")

    live = object()
    el = s.add_element(role="push button", name="OK", node=Dead(),
                       bus_name=":1.1", index_path=(0, 1))
    calls = []
    out = s.resolve_element("@e1", resolver=lambda loc: calls.append(loc) or live)
    assert out is el and el.node is live and calls


def test_resolve_element_stale_when_resolver_fails():
    s = refs.RefStore()
    s.new_generation()

    class Dead:
        def get_state_set(self):
            raise RuntimeError("UnknownObject")

    s.add_element(role="push button", name="OK", node=Dead())
    with pytest.raises(StaleRef):
        s.resolve_element("@e1", resolver=lambda loc: None)


def test_window_and_element_namespaces():
    s = refs.RefStore()
    s.new_generation()
    w = s.add_window(handle=1, backend="x11")
    e = s.add_element(role="link")
    assert w.ref == "@w1" and e.ref == "@e1"
    assert s.get("@w1") is w and s.get("@e1") is e
