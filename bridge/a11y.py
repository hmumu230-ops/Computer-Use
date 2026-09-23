"""AT-SPI2 accessibility layer via `gi.repository.Atspi` (pyatspi2 is EOL).

Design notes (from research):
- `Accessible` implements all ifaces; use get_*_iface() accessors.
- Identity = (bus_name, index_path from app root) + (role, name) fingerprint.
- Semantic verbs normalize per-toolkit action names (GTK click/press,
  Qt Press/Toggle/Show Menu, Chromium doDefault, Firefox jump/press).
- Runtime enable: set org.a11y.Status.IsEnabled=true on the session bus —
  makes GTK/Qt/Chromium expose trees retroactively. NEVER set
  ScreenReaderEnabled (auto-launches Orca under GNOME).

All gi access is lazy so this module imports on any platform (tests inject
a fake Atspi module via `a11y._ATS`).
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from errors import StaleRef, Timeout, UnsupportedPlatform

_ATS = None          # gi.repository.Atspi or a test fake
_GLIB = None
_GIO = None
_INITED = False

INTERESTING_ROLES = {
    "push button", "toggle button", "link", "text", "entry", "password text",
    "list item", "menu item", "check menu item", "radio menu item",
    "check box", "radio button", "combo box", "combo box text",
    "tab", "page tab", "page tab list", "slider", "spin button",
    "tree item", "table cell", "menu", "tool bar", "scroll bar",
    "scroll pane", "dialog", "alert", "notification", "status bar",
    "heading", "tree", "tree table", "terminal", "form", "switch",
    "internal frame", "split pane", "embedded", "suggestion",
    "description list", "description term", "description value",
}
WALK_MAX_DEPTH = 16
WALK_MAX_ELEMENTS = 300

# semantic verb -> normalized action names (lower(), strip _ - space)
VERBS = {
    "press":    ["click", "press", "activate", "dodefault", "invoke",
                 "jump", "open", "select", "go"],
    "toggle":   ["toggle", "check", "uncheck", "click", "press"],
    "expand":   ["expand", "open", "expandorcontract", "activate", "click"],
    "collapse": ["collapse", "close", "expandorcontract", "activate", "click"],
    "select":   ["select", "click", "press"],
    "showmenu": ["showcontextmenu", "menu", "showmenu", "popup", "show menu"],
    "increment": ["increment", "increase"],
    "decrement": ["decrement", "decrease"],
    "focus":    ["focus", "setfocus"],
}


def _norm(s: str) -> str:
    return s.lower().replace("_", "").replace("-", "").replace(" ", "")


def ats():
    """Return the Atspi module, raising UnsupportedPlatform if absent."""
    global _ATS, _GLIB, _GIO
    if _ATS is not None:
        return _ATS
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib, Gio
        _ATS, _GLIB, _GIO = Atspi, GLib, Gio
    except Exception as e:
        raise UnsupportedPlatform(
            f"AT-SPI unavailable: {e}",
            hint="install python3-gi + gir1.2-atspi-2.0 and run on system python")
    return _ATS


def _inject_fake(ats, glib=None, gio=None):
    """Test hook: inject a fake Atspi module."""
    global _ATS, _GLIB, _GIO, _INITED
    _ATS, _GLIB, _GIO = ats, glib, gio
    _INITED = True


def init() -> None:
    """Idempotent init + IsEnabled warmup."""
    global _INITED
    A = ats()
    if _INITED:
        return
    try:
        A.init()
    except Exception:
        pass
    A.set_timeout(800, 3000)
    _enable_a11y_bus()
    _INITED = True


def _enable_a11y_bus() -> None:
    """Set org.a11y.Status.IsEnabled=true on the session bus."""
    try:
        if _GIO is None or _GLIB is None:
            return
        bus = _GIO.bus_get_sync(_GIO.BusType.SESSION, None)
        bus.call_sync(
            "org.a11y.Bus", "/org/a11y/bus",
            "org.freedesktop.DBus.Properties", "Set",
            _GLIB.Variant("(ssv)", ("org.a11y.Status", "IsEnabled",
                                    _GLIB.Variant("b", True))),
            None, _GIO.DBusCallFlags.NONE, -1, None)
    except Exception:
        pass


def _iface_names(node) -> set[str]:
    try:
        return {n.split(".")[-1].lower() for n in (node.get_interfaces() or [])}
    except Exception:
        return set()


def _states(node) -> frozenset:
    try:
        return frozenset(
            getattr(s, "value_nick", "") for s in node.get_state_set().get_states())
    except Exception:
        return frozenset()


def _actions(node) -> frozenset:
    out = set()
    try:
        ai = node.get_action_iface()
        if ai is None:
            return frozenset()
        for k in range(ai.get_n_actions()):
            try:
                out.add(_norm(ai.get_action_name(k) or ""))
            except Exception:
                pass
    except Exception:
        pass
    return frozenset(out)


def is_alive(node) -> bool:
    if node is None:
        return False
    try:
        states = node.get_state_set().get_states()
    except Exception:
        return False    # D-Bus UnknownObject/NoReply = dead remote object
    nicks = {getattr(s, "value_nick", "") for s in states}
    return "defunct" not in nicks and "stale" not in nicks


def index_path(node) -> tuple:
    """Child indices from app root (pyatspi utils.getPath algorithm)."""
    path = []
    cur = node
    try:
        while cur is not None and cur.get_parent() is not None:
            path.append(cur.get_index_in_parent())
            cur = cur.get_parent()
    except Exception:
        pass
    return tuple(reversed(path))


def app_for(node):
    try:
        return node.get_application()
    except Exception:
        return None


def app_bus_name(node) -> str:
    app = app_for(node)
    if app is None:
        return ""
    try:
        return app.get_property("bus-name") or ""
    except Exception:
        try:
            return app.bus_name or ""
        except Exception:
            return ""


def app_pid(node) -> int:
    app = app_for(node)
    try:
        return app.get_process_id() if app else 0
    except Exception:
        return 0


def nth_of(node) -> int:
    """Position among same-(role,name) siblings — disambiguates index_path."""
    try:
        parent = node.get_parent()
        if parent is None:
            return 0
        role, name = node.get_role_name(), node.get_name() or ""
        n = 0
        for i in range(parent.get_child_count()):
            c = parent.get_child_at_index(i)
            if c is None:
                continue
            try:
                if c.get_role_name() == role and (c.get_name() or "") == name:
                    if c.get_index_in_parent() == node.get_index_in_parent():
                        return n
                    n += 1
            except Exception:
                continue
    except Exception:
        pass
    return 0


def extents(node, coord_screen: bool = True) -> dict | None:
    A = ats()
    for ct in ((A.CoordType.SCREEN, A.CoordType.WINDOW) if coord_screen
               else (A.CoordType.WINDOW,)):
        try:
            ext = node.get_extents(ct)
            if ext and ext.width > 0 and ext.height > 0:
                return {"x": ext.x, "y": ext.y, "w": ext.width, "h": ext.height}
        except Exception:
            continue
    return None


def effective_name(node) -> str:
    """name → LABELLED_BY relation → description → attributes fallback."""
    try:
        n = node.get_name() or ""
        if n:
            return n
    except Exception:
        pass
    try:
        for rel in node.get_relation_set() or []:
            if rel.get_relation_type() == ats().RelationType.LABELLED_BY:
                for i in range(rel.get_n_targets()):
                    t = rel.get_target(i)
                    if t is not None:
                        tn = t.get_name() or ""
                        if tn:
                            return tn
    except Exception:
        pass
    for getter in ("get_description", "get_help_text"):
        try:
            v = getattr(node, getter)() or ""
            if v:
                return v
        except Exception:
            pass
    try:
        attrs = node.get_attributes() or {}
        for k in ("placeholder-text", "placeholder", "id", "class"):
            if attrs.get(k):
                return str(attrs[k])
    except Exception:
        pass
    return ""


@dataclass
class AXNode:
    role: str
    name: str
    bbox: dict | None
    bus_name: str
    pid: int
    index_path: tuple
    nth: int
    states: frozenset
    actions: frozenset
    interfaces: frozenset
    node: object          # live Accessible proxy

    @property
    def can_press(self) -> bool:
        return bool(self.actions & frozenset(_norm(v) for v in VERBS["press"])) \
            or "action" in self.interfaces

    @property
    def can_set_text(self) -> bool:
        return "editabletext" in self.interfaces or "editable" in self.states

    @property
    def can_focus(self) -> bool:
        return "focusable" in self.states or "component" in self.interfaces


def describe(node) -> AXNode:
    st = _states(node)
    if "showing" not in st and "visible" not in st:
        pass  # keep invisible nodes — callers filter; showing flag is in states
    return AXNode(
        role=(lambda: (node.get_role_name() or ""))(),
        name=effective_name(node)[:160],
        bbox=extents(node),
        bus_name=app_bus_name(node),
        pid=app_pid(node),
        index_path=index_path(node),
        nth=nth_of(node),
        states=st,
        actions=_actions(node),
        interfaces=frozenset(_iface_names(node)),
        node=node,
    )


def walk(root, max_depth: int = WALK_MAX_DEPTH,
         max_elements: int = WALK_MAX_ELEMENTS,
         interesting_only: bool = True) -> list[AXNode]:
    """DFS the AT-SPI subtree. Skips DEFUNCT; respects MANAGES_DESCENDANTS
    (children of virtualized containers still walked but flagged)."""
    out: list[AXNode] = []

    def visit(node, depth: int, virtual_parent: bool) -> None:
        if len(out) >= max_elements or depth > max_depth or node is None:
            return
        st = _states(node)
        if "defunct" in st:
            return
        if "manages_descendants" in st:
            virtual_parent = True
        try:
            role = node.get_role_name() or ""
        except Exception:
            return
        if not interesting_only or role in INTERESTING_ROLES:
            ax = describe(node)
            if virtual_parent:
                ax.states = ax.states | frozenset({"virtualized"})
            out.append(ax)
        try:
            nc = node.get_child_count()
        except Exception:
            return
        for j in range(nc):
            if len(out) >= max_elements:
                return
            try:
                child = node.get_child_at_index(j)
            except Exception:
                continue
            visit(child, depth + 1, virtual_parent)

    visit(root, 0, False)
    return out


def app_roots() -> list:
    A = ats()
    try:
        desktop = A.get_desktop(0)
        return [desktop.get_child_at_index(i)
                for i in range(desktop.get_child_count())]
    except Exception:
        return []


def app_root_for_pid(pid: int):
    for app in app_roots():
        if app is None:
            continue
        try:
            if app.get_process_id() == pid:
                return app
        except Exception:
            continue
    return None


def app_root_for_bus(bus_name: str):
    for app in app_roots():
        if app is None:
            continue
        if app_bus_name(app) == bus_name:
            return app
    return None


def resolve_locator(bus_name: str, pid: int, path: tuple,
                    role: str = "", name: str = ""):
    """Re-resolve an element: walk index_path from the app root, then
    validate the fingerprint. Returns live node or None."""
    root = app_root_for_bus(bus_name) if bus_name else app_root_for_pid(pid)
    if root is None:
        return None
    node = root
    for idx in path:
        try:
            node = node.get_child_at_index(idx)
        except Exception:
            return None
        if node is None:
            return None
    if role or name:
        try:
            if role and node.get_role_name() != role:
                # index drift (GTK4 virtualization) — try fingerprint search
                return find_in_subtree(root, role, name)
            if name and (node.get_name() or "") != name:
                return find_in_subtree(root, role, name)
        except Exception:
            return None
    return node if is_alive(node) else None


def find_in_subtree(root, role: str = "", name: str = "",
                    max_hits: int = 8) -> object | None:
    """Fingerprint search fallback for index-path drift. Returns single
    match or None (ambiguous matches also return None — caller walks
    Collection for the full list)."""
    hits = find_elements(root, role=role, name=name, limit=max_hits + 1)
    if len(hits) == 1:
        return hits[0].node
    return None


def find_elements(root, role: str = "", name: str = "",
                  states: tuple = (), limit: int = 50) -> list[AXNode]:
    """Collection.get_matches server-side search, DFS fallback."""
    A = ats()
    if root is None:
        return []
    coll = None
    try:
        coll = root.get_collection_iface()
    except Exception:
        coll = None
    if coll is not None and (role or states):
        try:
            state_set = None
            if states:
                st_list = []
                for s in states:
                    try:
                        st_list.append(A.StateType[s.upper()])
                    except Exception:
                        pass
                if st_list:
                    state_set = A.StateSet.new(st_list)
            roles = []
            if role:
                for k in dir(A.Role):
                    if k.replace("_", " ").lower() == role.replace("_", " ").lower():
                        roles.append(getattr(A.Role, k))
                        break
            rule = A.MatchRule.new(
                state_set or A.StateSet.new([]),
                A.CollectionMatchType.ALL if states else A.CollectionMatchType.EMPTY,
                {}, A.CollectionMatchType.NONE,
                roles, A.CollectionMatchType.ANY if roles else A.CollectionMatchType.EMPTY,
                ["org.a11y.atspi.Action"], A.CollectionMatchType.ANY,
                False)
            hits = coll.get_matches(rule, A.CollectionSortOrder.CANONICAL,
                                    limit * 2, False)
            out = []
            for h in hits or []:
                ax = describe(h)
                if name and name.lower() not in ax.name.lower():
                    continue
                out.append(ax)
                if len(out) >= limit:
                    break
            return out
        except Exception:
            pass
    # DFS fallback (also used when only `name` is given)
    out = []
    for ax in walk(root, interesting_only=False):
        if role and ax.role != role:
            continue
        if name and name.lower() not in ax.name.lower():
            continue
        if states and not set(states) <= set(ax.states):
            continue
        out.append(ax)
        if len(out) >= limit:
            break
    return out


# ---------- actions ----------

def _do_named_action(node, verb: str) -> tuple[bool, str]:
    """Try semantic verb mapping; returns (done, action_name_used)."""
    ai = node.get_action_iface()
    if ai is None:
        return False, ""
    want = [_norm(v) for v in VERBS.get(verb, [verb])]
    names = []
    for k in range(ai.get_n_actions()):
        try:
            names.append(ai.get_action_name(k) or "")
        except Exception:
            names.append("")
    for w in want:
        for k, nm in enumerate(names):
            if _norm(nm) == w:
                if ai.do_action(k):
                    return True, nm
    return False, ""


def _bfs_descendant_action(node, verb: str, depth: int = 3) -> tuple[bool, str]:
    """GTK4 MenuButton pattern: outer push button has 0 actions, the real
    click lives on a descendant toggle button."""
    frontier = [node]
    for _ in range(depth):
        nxt = []
        for n in frontier:
            try:
                for i in range(n.get_child_count()):
                    c = n.get_child_at_index(i)
                    if c is None:
                        continue
                    done, used = _do_named_action(c, verb)
                    if done:
                        return True, f"descendant:{used}"
                    nxt.append(c)
            except Exception:
                continue
        frontier = nxt
    return False, ""


def act(node, verb: str = "press") -> dict:
    """Semantic action. Order: verb verbs → index-0 default (press only) →
    descendant BFS → grab_focus (focus verb)."""
    if node is None or not is_alive(node):
        raise StaleRef("element is gone", hint="re-snapshot")
    ai = None
    try:
        ai = node.get_action_iface()
    except Exception:
        ai = None
    done, used = _do_named_action(node, verb) if ai else (False, "")
    method = "action"
    if not done and verb == "press" and ai is not None:
        try:
            if ai.get_n_actions() > 0 and ai.do_action(0):
                done, used = True, "default(index0)"
        except Exception:
            pass
    if not done:
        done, used = _bfs_descendant_action(node, verb)
        if done:
            method = "descendant-action"
    if not done and verb == "focus":
        try:
            done = bool(node.grab_focus())
            used, method = "grab_focus", "component"
        except Exception:
            pass
    if not done:
        raise UnsupportedPlatform(
            f"no semantic '{verb}' action available",
            hint="element has no matching AT-SPI action; use coordinate click")
    return {"verb": verb, "method": method, "action": used}


def get_text(node, start: int = 0, end: int = -1) -> str:
    ti = node.get_text_iface()
    if ti is None:
        return ""
    try:
        return ti.get_text(start, end) or ""
    except Exception:
        return ""


def set_text(node, text: str) -> dict:
    """EditableText set with readback verify; caller falls back to typing."""
    st = _states(node)
    eti = None
    try:
        eti = node.get_editable_text_iface()
    except Exception:
        eti = None
    if eti is None or "editable" not in st:
        raise UnsupportedPlatform("element is not editable",
                                  hint="use type_text with focus instead")
    eti.set_text_contents(text)
    time.sleep(0.05)
    got = get_text(node)
    return {"used": "editabletext", "verified": got == text,
            "length": len(got)}


def set_value(node, value: float) -> dict:
    vi = node.get_value_iface()
    if vi is None:
        raise UnsupportedPlatform("no Value interface",
                                  hint="use keyboard increment/decrement")
    vi.set_current_value(float(value))
    time.sleep(0.05)
    try:
        cur = vi.get_current_value()
    except Exception:
        cur = None
    return {"used": "value", "value": cur,
            "verified": cur == float(value) if cur is not None else None}


def select_child(container_node, child_index: int) -> dict:
    si = container_node.get_selection_iface()
    if si is None:
        raise UnsupportedPlatform("no Selection interface")
    ok = si.select_child(child_index)
    return {"used": "selection", "ok": bool(ok)}


def scroll_to(node) -> bool:
    A = ats()
    try:
        return bool(node.scroll_to(A.ScrollType.ANYWHERE))
    except Exception:
        return False


def grab_focus(node) -> bool:
    try:
        return bool(node.grab_focus())
    except Exception:
        return False


def hit_test(root, x: int, y: int, max_depth: int = 24):
    """Deepest accessible at screen point."""
    A = ats()
    node = root
    for _ in range(max_depth):
        try:
            child = node.get_accessible_at_point(x, y, A.CoordType.SCREEN)
        except Exception:
            break
        if child is None:
            break
        node = child
    return node


# ---------- events (wait_for) ----------

_EVENT_THREAD = None
_EVENT_QUEUE: "queue.Queue | None" = None
_LISTENER = None


def _ensure_event_thread():
    global _EVENT_THREAD, _EVENT_QUEUE, _LISTENER
    A = ats()
    if _EVENT_THREAD is not None:
        return
    _EVENT_QUEUE = queue.Queue()
    _LISTENER = A.EventListener.new(lambda e: _EVENT_QUEUE.put(e))
    _EVENT_THREAD = threading.Thread(target=_run_event_loop, daemon=True)
    _EVENT_THREAD.start()


def _run_event_loop():
    A = ats()
    try:
        A.event_main()          # blocks holding GIL — own daemon thread
    except Exception:
        pass


_EVENT_TOPICS = (
    "object:state-changed:focused", "object:state-changed:showing",
    "object:state-changed:checked", "object:state-changed:expanded",
    "object:children-changed", "object:property-change:accessible-name",
    "object:text-changed", "object:selection-changed",
    "object:active-descendant-changed", "object:bounds-changed",
    "window:activate", "window:create", "window:destroy",
)


def wait_for(predicate, timeout: float = 10.0,
             topics: tuple = _EVENT_TOPICS) -> dict:
    """Block until predicate(event)->True or timeout. predicate receives a
    dict {type, source_role, source_name, detail1, detail2, data}."""
    init()
    _ensure_event_thread()
    assert _LISTENER is not None and _EVENT_QUEUE is not None
    for t in topics:
        try:
            _LISTENER.register(t)
        except Exception:
            pass
    deadline = time.monotonic() + timeout
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise Timeout(f"wait_for timed out after {timeout}s",
                              hint="broaden topics or check app state")
            try:
                e = _EVENT_QUEUE.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            ev = _event_to_dict(e)
            try:
                if predicate(ev):
                    return {"matched": ev}
            except Exception:
                continue
    finally:
        for t in topics:
            try:
                _LISTENER.deregister(t)
            except Exception:
                pass


def _event_to_dict(e) -> dict:
    src = getattr(e, "source", None)
    return {
        "type": getattr(e, "type", ""),
        "source_role": _safe(src, "get_role_name"),
        "source_name": _safe(src, "get_name"),
        "detail1": getattr(e, "detail1", None),
        "detail2": getattr(e, "detail2", None),
        "data": str(getattr(e, "any_data", "") or ""),
    }


def _safe(obj, meth):
    try:
        return getattr(obj, meth)() if obj is not None else ""
    except Exception:
        return ""


# ---------- synthetic input via AT-SPI (X11 only — XTEST underneath) ------

def gen_key_string(text: str) -> bool:
    A = ats()
    try:
        return bool(A.generate_keyboard_event(0, text, A.KeySynthType.STRING))
    except Exception:
        return False


def gen_key_press(keyval: int, keystring: str = "") -> bool:
    A = ats()
    try:
        return bool(A.generate_keyboard_event(
            keyval, keystring, A.KeySynthType.PRESSRELEASE))
    except Exception:
        return False


def gen_mouse_click(x: int, y: int, button: int = 1) -> bool:
    A = ats()
    try:
        A.generate_mouse_event(x, y, "abs")
        return bool(A.generate_mouse_event(x, y, f"b{button}c"))
    except Exception:
        return False
