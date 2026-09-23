"""Unit tests for macos_mcp.refs — pure Python, no pyobjc needed."""

import pytest

from macos_mcp import refs
from macos_mcp.errors import StaleRef


@pytest.fixture
def store():
    return refs.RefStore()


class TestRegistration:
    def test_mints_e_refs(self, store):
        er = store.add_element(element=object(), pid=1, role="AXButton",
                               name="OK", bbox={"x": 0, "y": 0, "w": 10, "h": 5})
        assert er.ref == "@e1"
        assert store.get("@e1") is er

    def test_ordinal_per_role_name(self, store):
        a = store.add_element(object(), 1, "AXButton", "OK")
        b = store.add_element(object(), 1, "AXButton", "OK")
        c = store.add_element(object(), 1, "AXButton", "Cancel")
        assert (a.nth, b.nth, c.nth) == (0, 1, 0)

    def test_window_refs(self, store):
        wr = store.add_window(object(), 42, "Doc", {"x": 0, "y": 0, "w": 1, "h": 1})
        assert wr.ref == "@w1"
        assert store.get("@w1") is wr

    def test_synthetic(self, store):
        er = store.add_synthetic({"x": 1, "y": 2, "w": 3, "h": 4}, "word")
        assert er.synthetic and er.element is None


class TestGeneration:
    def test_new_generation_stales_refs(self, store):
        store.add_element(object(), 1, "AXButton", "OK")
        store.new_generation()
        with pytest.raises(StaleRef):
            store.get("@e1")

    def test_unknown_ref(self, store):
        with pytest.raises(StaleRef):
            store.get("@e99")

    def test_is_ref(self, store):
        assert store.is_ref("@e3") and store.is_ref("@w1")
        assert not store.is_ref("e3") and not store.is_ref("@x1")


class TestResolve:
    def test_live_probe_wins(self, store):
        el = object()
        store.add_element(el, 1, "AXButton", "OK")
        er = store.resolve_element("@e1", probe=lambda e: True,
                                   search=lambda *a: None)
        assert er.element is el

    def test_research_refreshes_element(self, store):
        dead, found = object(), object()
        store.add_element(dead, 1, "AXButton", "OK")
        er = store.resolve_element(
            "@e1",
            probe=lambda e: False,
            search=lambda pid, role, name, nth: found,
        )
        assert er.element is found

    def test_dead_raises_stale(self, store):
        store.add_element(object(), 1, "AXButton", "OK")
        with pytest.raises(StaleRef):
            store.resolve_element("@e1", probe=lambda e: False,
                                  search=lambda *a: None)

    def test_synthetic_resolves_without_probe(self, store):
        store.add_synthetic({"x": 0, "y": 0, "w": 1, "h": 1}, "w")
        er = store.resolve_element("@e1")
        assert er.synthetic

    def test_window_ref_rejected_for_element(self, store):
        store.add_window(object(), 1, "Win")
        with pytest.raises(StaleRef):
            store.resolve_element("@w1")


class TestSafety:
    def test_confirm_flow(self, monkeypatch):
        from macos_mcp import safety
        monkeypatch.setenv("MACOS_MCP_REQUIRE_CONFIRM", "1")
        with pytest.raises(refs.CuError) as ei:
            safety.gate("power:off", {}, True, "")
        tok = ei.value.details["token"]
        assert safety.gate("power:off", {}, True, tok) is None

    def test_wrong_action_does_not_burn_token(self, monkeypatch):
        from macos_mcp import safety
        monkeypatch.setenv("MACOS_MCP_REQUIRE_CONFIRM", "1")
        with pytest.raises(refs.CuError):
            safety.gate("a:x", {}, True, "")
        tok = next(iter(safety._TOKENS))
        with pytest.raises(refs.CuError):
            safety.gate("b:y", {}, True, tok)   # bound to a:x — rejected
        assert safety.gate("a:x", {}, True, tok) is None  # still usable
