"""RefStore resolution ladder — parse, issue, live probe, re-resolve, evict.

UIA controls are faked with lightweight stubs; the uia module functions that
touch COM are monkeypatched.
"""

from __future__ import annotations

import threading

import pytest

from windows_mcp.refs import RefStore, RefError
from windows_mcp.refs.locator import ElementLocator
from windows_mcp.refs import store as store_mod


class FakeControl:
    """Minimal stand-in for a uia.Control proxy."""

    def __init__(
        self,
        *,
        pid: int = 0,
        runtime_id=(42, 1, 7),
        name: str = "OK",
        automation_id: str = "",
        alive: bool = True,
    ):
        # 0 → own pid so psutil.pid_exists in _probe_alive passes
        self.ProcessId = pid or __import__("os").getpid()
        self.Name = name
        self._runtime_id = runtime_id
        self.AutomationId = automation_id
        self._alive = alive
        self.BoundingRectangle = None

    @property
    def BoundingRectangle(self):  # noqa: N802 — mirrors the real attr
        if not self._alive:
            raise RuntimeError("element is dead")
        return None

    @BoundingRectangle.setter
    def BoundingRectangle(self, value):  # noqa: N802
        self._stored_rect = value

    def GetRuntimeId(self):  # noqa: N802
        if not self._alive:
            raise RuntimeError("element is dead")
        return list(self._runtime_id)


class FakeWindow(FakeControl):
    """Control with scripted control-view children / FindFirst results."""

    def __init__(self, *, children=None, find_first=None, **kw):
        super().__init__(**kw)
        self._children = children or []
        self._find_first = find_first

    def FindAll(self, scope, condition):  # noqa: N802
        return list(self._children)

    def GetChildren(self):  # noqa: N802
        return list(self._children)

    def FindFirst(self, scope, condition):  # noqa: N802
        return self._find_first


def _locator(**kw) -> ElementLocator:
    import os

    defaults = dict(
        runtime_id=(42, 1, 7),
        name="OK",
        control_type="ButtonControl",
        window_handle=1234,
        process_id=os.getpid(),  # matches FakeWindow's default so hwnd check passes
    )
    defaults.update(kw)
    return ElementLocator(**defaults)


@pytest.fixture
def store() -> RefStore:
    return RefStore(capacity=8)


# -- parse_ref --------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("e5", 5), ("@e5", 5), ("#e5", 5), ("5", 5), (5, 5), (" @e12 ", 12)],
)
def test_parse_ref_valid(value, expected):
    assert RefStore.parse_ref(value) == expected


@pytest.mark.parametrize("value", ["x", "", "e0", "e-1", 0, -3, True, "@e"])
def test_parse_ref_invalid(value):
    with pytest.raises(RefError) as exc:
        RefStore.parse_ref(value)
    assert exc.value.code == "INVALID_REF"


# -- issuance ---------------------------------------------------------------


def test_rebuild_assigns_sequential_refs_and_publishes_latest(store):
    locators = [_locator(), _locator(), _locator()]
    store.rebuild(locators)
    assert [loc.ref for loc in locators] == [1, 2, 3]
    assert store.latest[0] is locators[0]
    assert store.latest[2] is locators[2]
    assert store.generation == 1


def test_rebuild_keeps_old_refs_registered(store):
    first = _locator()
    store.rebuild([first])
    store.rebuild([_locator()])
    # old ref still resolves (its fake control is alive)
    assert store.get(first.ref) is first
    assert len(store.latest) == 1  # latest replaced, not appended


def test_register_issues_ref_outside_snapshot(store):
    ref = store.register(_locator(synthetic=True))
    assert ref == 1
    assert store.get(ref).synthetic


def test_eviction_drops_oldest_refs(store):
    for _ in range(10):
        store.register(_locator(synthetic=True))
    assert len(store._locators) <= store.capacity
    assert store.get(10).ref == 10
    with pytest.raises(RefError) as exc:
        store.get(1)
    assert exc.value.code == "UNKNOWN_REF"


def test_unknown_ref_raises(store):
    with pytest.raises(RefError) as exc:
        store.get(99)
    assert exc.value.code == "UNKNOWN_REF"


def test_resolve_index_requires_snapshot_entry(store):
    with pytest.raises(RefError) as exc:
        store.resolve_index(0)
    assert exc.value.code == "ELEMENT_NOT_FOUND"


# -- resolution ladder ------------------------------------------------------


def test_resolve_live_control_short_circuits(store):
    control = FakeControl(alive=True)
    locator = _locator(control=control)
    store.register(locator)
    assert store.resolve(locator.ref).control is control


def test_resolve_synthetic_returns_locator(store):
    locator = _locator(control=None, synthetic=True)
    store.register(locator)
    assert store.resolve(locator.ref) is locator


def test_stale_element_raises_stale_ref(store, monkeypatch):
    locator = _locator(control=FakeControl(alive=False))
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: None)
    monkeypatch.setattr(
        store_mod.uia,
        "GetRootControl",
        lambda: FakeWindow(children=[]),
    )
    with pytest.raises(RefError) as exc:
        store.resolve(locator.ref)
    assert exc.value.code == "STALE_REF"


def test_index_path_replays_via_control_view(store, monkeypatch):
    target = FakeControl(alive=True, runtime_id=(42, 1, 7))
    window = FakeWindow(children=[FakeControl(), target])
    locator = _locator(
        control=FakeControl(alive=False),
        index_path=(1,),
        runtime_id=(42, 1, 7),
        automation_id="",
    )
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: window)
    resolved = store.resolve(locator.ref)
    assert resolved.control is target


def test_index_path_out_of_range_falls_through(store, monkeypatch):
    window = FakeWindow(children=[FakeControl()])
    locator = _locator(
        control=FakeControl(alive=False),
        index_path=(5,),
        automation_id="",
        runtime_id=None,
    )
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: window)
    with pytest.raises(RefError) as exc:
        store.resolve(locator.ref)
    assert exc.value.code == "STALE_REF"


def test_automation_id_hit_rejects_name_mismatch(store, monkeypatch):
    imposter = FakeControl(alive=True, name="Cancel", automation_id="btn1")
    window = FakeWindow(find_first=imposter)
    locator = _locator(
        control=FakeControl(alive=False),
        index_path=(),
        automation_id="btn1",
        name="OK",
        runtime_id=None,
    )
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: window)
    monkeypatch.setattr(store_mod.uia, "CreatePropertyCondition", lambda *a: object())
    monkeypatch.setattr(store_mod.uia, "CreateAndCondition", lambda a, b: (a, b))
    monkeypatch.setattr(store_mod.uia.ControlType, "ButtonControl", 50000, raising=False)
    with pytest.raises(RefError) as exc:
        store.resolve(locator.ref)
    assert exc.value.code == "STALE_REF"


def test_automation_id_hit_with_matching_name(store, monkeypatch):
    match = FakeControl(alive=True, name="OK", automation_id="btn1")
    window = FakeWindow(find_first=match)
    locator = _locator(
        control=FakeControl(alive=False),
        index_path=(),
        automation_id="btn1",
        name="OK",
        runtime_id=None,
    )
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: window)
    monkeypatch.setattr(store_mod.uia, "CreatePropertyCondition", lambda *a: object())
    monkeypatch.setattr(store_mod.uia, "CreateAndCondition", lambda a, b: (a, b))
    monkeypatch.setattr(store_mod.uia.ControlType, "ButtonControl", 50000, raising=False)
    assert store.resolve(locator.ref).control is match


def test_hwnd_reuse_rejected_when_pid_differs(store, monkeypatch):
    foreign_window = FakeControl(pid=9999)
    import os

    locator = _locator(control=FakeControl(alive=False), process_id=os.getpid())
    store.register(locator)
    monkeypatch.setattr(store_mod.uia, "ControlFromHandle", lambda h: foreign_window)
    monkeypatch.setattr(
        store_mod.uia,
        "GetRootControl",
        lambda: FakeWindow(children=[]),
    )
    with pytest.raises(RefError) as exc:
        store.resolve(locator.ref)
    assert exc.value.code == "STALE_REF"


def test_pid_fallback_finds_window_in_roots(store, monkeypatch):
    import os

    target = FakeControl(alive=True, runtime_id=(42, 1, 7))
    window = FakeWindow(pid=os.getpid(), children=[target])
    locator = _locator(
        control=FakeControl(alive=False),
        window_handle=0,  # no hwnd — must go the process route
        index_path=(0,),
        runtime_id=(42, 1, 7),
    )
    store.register(locator)
    monkeypatch.setattr(
        store_mod.uia, "ControlFromHandle", lambda h: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        store_mod.uia,
        "GetRootControl",
        lambda: FakeWindow(children=[FakeWindow(pid=1), window]),
    )
    assert store.resolve(locator.ref).control is target


def test_concurrent_rebuild_and_resolve_no_torn_state(store):
    stop = threading.Event()
    errors = []

    def churn():
        while not stop.is_set():
            store.rebuild([_locator(control=FakeControl(alive=True))])

    def reader():
        while not stop.is_set():
            try:
                store.resolve_index(0)
            except RefError:
                pass
            except Exception as e:  # torn reads must not leak
                errors.append(e)

    threads = [threading.Thread(target=churn) for _ in range(3)]
    threads += [threading.Thread(target=reader) for _ in range(3)]
    for t in threads:
        t.start()
    stop.wait(0.3)
    stop.set()
    for t in threads:
        t.join()
    assert errors == []
