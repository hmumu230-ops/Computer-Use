"""Test harness: sys.path, FakeAtspi tree fixture, subprocess fakes.

Unit tests must run on any host (incl. Windows/WSL dev machines) — every
external boundary (gi, subprocess, D-Bus) is faked or monkeypatched.
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bridge"))
sys.path.insert(0, ROOT)


# ---------- FakeAtspi ----------

class FakeRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self.x, self.y, self.width, self.height = x, y, w, h


class FakeState:
    def __init__(self, nick):
        self.value_nick = nick


class FakeActionIface:
    def __init__(self, node):
        self._node = node
        self.calls = []

    def get_n_actions(self):
        return len(self._node._actions)

    def get_action_name(self, i):
        return self._node._actions[i][0]

    def do_action(self, i):
        self.calls.append(i)
        fn = self._node._actions[i][1]
        return fn() if callable(fn) else bool(fn)


class FakeTextIface:
    def __init__(self, node):
        self._node = node

    def get_character_count(self):
        return len(self._node._text)

    def get_text(self, s, e):
        return self._node._text[s:e if e >= 0 else len(self._node._text)]


class FakeEditableText:
    def __init__(self, node):
        self._node = node

    def set_text_contents(self, t):
        self._node._text = t
        return True


class FakeValue:
    def __init__(self, node):
        self._node = node

    def get_current_value(self):
        return self._node._value

    def set_current_value(self, v):
        self._node._value = v
        return True

    def get_minimum_value(self):
        return 0.0

    def get_maximum_value(self):
        return 100.0


class FakeNode:
    """A fake Atspi.Accessible."""
    def __init__(self, role="push button", name="", text="",
                 actions=None, states=None, bbox=None, children=None,
                 ifaces=None, pid=4242, bus_name=":1.99"):
        self._role = role
        self._name = name
        self._text = text
        self._value = 0.0
        self._actions = actions or []           # [(name, fn|bool)]
        self._states = set(states or {"enabled", "sensitive", "showing",
                                      "visible", "focusable"})
        self._bbox = bbox or {"x": 10, "y": 10, "w": 50, "h": 20}
        self._children = list(children or [])
        self._parent = None
        for c in self._children:
            c._parent = self
        self._ifaces = set(ifaces or ["component", "action"])
        self._pid = pid
        self._bus = bus_name
        self.dead = False
        self.focused = False

    # Accessible basics
    def get_role_name(self):
        if self.dead:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        return self._role

    def get_name(self):
        if self.dead:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        return self._name

    def get_description(self):
        return ""

    def get_help_text(self):
        return ""

    def get_attributes(self):
        return {}

    def get_relation_set(self):
        return []

    def get_accessible_id(self):
        return None

    def get_parent(self):
        return self._parent

    def get_index_in_parent(self):
        return self._parent._children.index(self) if self._parent else 0

    def get_child_count(self):
        if self.dead:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        return len(self._children)

    def get_child_at_index(self, i):
        if self.dead:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        return self._children[i] if 0 <= i < len(self._children) else None

    def get_state_set(self):
        if self.dead:
            raise RuntimeError("org.freedesktop.DBus.Error.UnknownObject")
        ss = type("SS", (), {})()
        ss.get_states = lambda: [FakeState(s) for s in self._states]
        return ss

    def get_interfaces(self):
        return list(self._ifaces)

    # Component
    def get_extents(self, ct):
        b = self._bbox
        return FakeRect(b["x"], b["y"], b["w"], b["h"])

    def grab_focus(self):
        self.focused = True
        self._states.add("focused")
        return True

    def scroll_to(self, st):
        return True

    # interfaces
    def get_action_iface(self):
        return FakeActionIface(self) if "action" in self._ifaces else None

    def get_text_iface(self):
        return FakeTextIface(self) if "text" in self._ifaces else None

    def get_editable_text_iface(self):
        return FakeEditableText(self) if "editabletext" in self._ifaces \
            else None

    def get_value_iface(self):
        return FakeValue(self) if "value" in self._ifaces else None

    def get_selection_iface(self):
        return None

    def get_collection_iface(self):
        return None

    def get_application(self):
        app = type("App", (), {})()
        app.get_process_id = lambda: self._pid
        app.get_property = lambda k: self._bus if k == "bus-name" else ""
        return app


class FakeDesktop:
    def __init__(self, apps):
        self._apps = apps

    def get_child_count(self):
        return len(self._apps)

    def get_child_at_index(self, i):
        return self._apps[i]


class FakeAtspi:
    """Minimal gi.repository.Atspi stand-in."""
    class CoordType:
        SCREEN = 0
        WINDOW = 1
        PARENT = 2

    class ScrollType:
        ANYWHERE = 6

    class StateType:
        SHOWING = "showing"

    class RelationType:
        LABELLED_BY = 2

    class CollectionMatchType:
        ALL = 0
        ANY = 1
        NONE = 2
        EMPTY = 3

    class CollectionSortOrder:
        CANONICAL = 0

    class Role:
        PUSH_BUTTON = "push button"

    class StateSet:
        @staticmethod
        def new(states):
            return states

    class MatchRule:
        @staticmethod
        def new(*a, **kw):
            return (a, kw)

    class KeySynthType:
        STRING = 4
        PRESSRELEASE = 2

    class EventListener:
        @staticmethod
        def new(cb):
            l = type("L", (), {})()
            l.register = lambda t: None
            l.deregister = lambda t: None
            return l

    _desktop = None

    @staticmethod
    def init():
        return True

    @staticmethod
    def set_timeout(a, b):
        pass

    @staticmethod
    def get_desktop(i):
        return FakeAtspi._desktop

    @staticmethod
    def event_main():
        pass

    @staticmethod
    def generate_keyboard_event(kv, s, t):
        return True

    @staticmethod
    def generate_mouse_event(x, y, name):
        return True


@pytest.fixture
def fake_atspi():
    """Inject FakeAtspi into a11y; returns a helper to build trees."""
    import a11y
    a11y._inject_fake(FakeAtspi)

    def make_app(children=None, pid=4242, bus=":1.99"):
        app = FakeNode(role="application", name="app", pid=pid,
                       bus_name=bus, children=children or [])
        FakeAtspi._desktop = FakeDesktop([app])
        return app

    yield make_app
    a11y._inject_fake(None)  # reset to lazy-gi mode


@pytest.fixture
def fake_run(monkeypatch):
    """Capture util.run calls; queue canned CompletedProcess outputs."""
    import subprocess
    import util
    calls = []
    queue = []

    def fake(cmd, timeout=10.0, check=False, env=None, input_text=None,
             binary=False):
        calls.append(list(cmd))
        while queue:
            r = queue.pop(0)
            if r.get("match") is None or any(m in " ".join(cmd)
                                             for m in r["match"]):
                return subprocess.CompletedProcess(
                    cmd, r.get("rc", 0), r.get("stdout", ""),
                    r.get("stderr", ""))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(util, "run", fake)
    monkeypatch.setattr("syscore.run", fake)
    monkeypatch.setattr("syshw.run", fake)
    return {"calls": calls, "queue": queue}
