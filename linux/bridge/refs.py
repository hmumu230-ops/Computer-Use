"""Ref store: @wN window refs and @eN element refs with generation scoping.

Element locators: (bus_name, index_path) + durable fingerprint (role, name, nth).
AT-SPI Accessible proxies are not serializable and `==` is unreliable across
proxies, so identity = index path within the owning app + fingerprint check.

Synthetic refs (OCR hits) carry a bbox instead of a node locator.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field

from errors import StaleRef, AmbiguousRef


@dataclass
class WindowRef:
    ref: str
    handle: object          # backend-specific: int XID, str internalId/uuid/address
    backend: str            # x11 | kde | sway | hyprland | gnome | foreign | niri | wayfire
    title: str = ""
    pid: int = 0
    geometry: dict | None = None      # {x,y,w,h} logical px, may be None on wlroots
    focused: bool = False
    generation: int = 0


@dataclass
class ElementRef:
    ref: str
    generation: int
    kind: str = "atspi"               # atspi | synthetic (OCR)
    # atspi locator
    bus_name: str = ""
    pid: int = 0
    index_path: tuple = ()            # child indices from app root
    role: str = ""
    name: str = ""
    nth: int = 0                      # nth sibling matching (role,name)
    bbox: dict | None = None          # last-known {x,y,w,h} logical px
    states: frozenset = frozenset()
    actions: frozenset = frozenset()  # normalized verb set
    interfaces: frozenset = frozenset()
    # live handle (not serialized)
    node: object = None
    # synthetic
    synthetic: bool = False
    source: str = ""                  # "ocr" | "find_text"


class RefStore:
    """Generation-scoped ref tables. A new snapshot bumps the generation;
    refs from older generations resolve only after successful re-resolution."""

    def __init__(self):
        self._lock = threading.Lock()
        self.generation = 0
        self.windows: dict[str, WindowRef] = {}
        self.elements: dict[str, ElementRef] = {}
        self._wseq = itertools.count(1)
        self._eseq = itertools.count(1)

    def new_generation(self) -> int:
        with self._lock:
            self.generation += 1
            self.windows.clear()
            self.elements.clear()
            self._wseq = itertools.count(1)
            self._eseq = itertools.count(1)
            return self.generation

    def add_window(self, **kw) -> WindowRef:
        with self._lock:
            ref = f"@w{next(self._wseq)}"
            w = WindowRef(ref=ref, generation=self.generation, **kw)
            self.windows[ref] = w
            return w

    def add_element(self, **kw) -> ElementRef:
        with self._lock:
            ref = f"@e{next(self._eseq)}"
            el = ElementRef(ref=ref, generation=self.generation, **kw)
            self.elements[ref] = el
            return el

    def add_synthetic(self, bbox: dict, name: str, role: str = "label",
                      source: str = "ocr") -> ElementRef:
        return self.add_element(kind="synthetic", synthetic=True,
                                bbox=bbox, name=name, role=role, source=source)

    def get(self, ref: str) -> WindowRef | ElementRef:
        if ref.startswith("@w"):
            obj = self.windows.get(ref)
        elif ref.startswith("@e"):
            obj = self.elements.get(ref)
        else:
            obj = None
        if obj is None:
            raise StaleRef(f"unknown ref {ref}",
                           hint="take a fresh snapshot; refs are generation-scoped")
        if obj.generation != self.generation:
            raise StaleRef(
                f"ref {ref} belongs to snapshot generation {obj.generation} "
                f"(current {self.generation})",
                hint="take a fresh snapshot to obtain current refs")
        return obj

    def try_get(self, ref: str) -> WindowRef | ElementRef | None:
        try:
            return self.get(ref)
        except StaleRef:
            return None

    # -- element re-resolution -----------------------------------------------

    def resolve_element(self, ref: str, resolver) -> ElementRef:
        """Return a live element; on generation mismatch or dead node,
        re-resolve via `resolver(locator) -> node|None` then re-register."""
        el = self.elements.get(ref)
        if el is None:
            raise StaleRef(f"unknown element ref {ref}")
        if el.synthetic:
            return el
        if el.generation == self.generation and el.node is not None:
            if _alive(el.node):
                return el
        # re-resolve via locator
        node = resolver(el)
        if node is None:
            raise StaleRef(
                f"element {ref} ({el.role} '{el.name}') is gone",
                hint="re-snapshot to get fresh refs")
        el.node = node
        el.generation = self.generation
        return el


def _alive(node) -> bool:
    """DEFUNCT state or raised D-Bus error = dead."""
    try:
        states = node.get_state_set().get_states()
        for s in states:
            if getattr(s, "value_nick", "") == "defunct":
                return False
        return True
    except Exception:
        return False


def fingerprint_match(node, role: str, name: str) -> bool:
    try:
        if node.get_role_name() != role:
            return False
        return (node.get_name() or "") == name
    except Exception:
        return False
