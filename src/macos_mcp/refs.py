"""Persistent @eN element refs and @wN window refs.

A ref is a locator, not a live handle: AXUIElementRef objects are process
tokens that die when the UI mutates, so each ref stores a durable key
``(pid, role, name, nth)`` plus the live element captured at emission time.

Resolution ladder on ``resolve()``:
  1. live probe — the held element still answers ``AXRole``/pid queries
  2. runtime re-search — walk the owning app for the nth (role, name) match
  3. ``StaleRef`` — nothing resolves; caller takes a fresh Snapshot

Generation scoping mirrors the Linux bridge: every Snapshot mints a new
generation and all refs from older generations go stale immediately — a
model can never act on coordinates from a screen that no longer exists.

This module is deliberately pyobjc-free so it is unit-testable off macOS;
probe/search are injected callables supplied by the desktop service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import CuError, StaleRef


@dataclass
class ElementRef:
    ref: str
    pid: int
    role: str
    name: str
    nth: int = 0                    # ordinal among same-(role,name) matches
    bbox: dict | None = None
    element: Any = None             # live AXUIElementRef (opaque)
    synthetic: bool = False         # OCR/visual hit — coords only, no element
    generation: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class WindowRef:
    ref: str
    pid: int
    title: str
    element: Any = None
    geometry: dict | None = None
    generation: int = 0


# Probe contract: probe(element) -> truthy when the element is alive.
ProbeFn = Callable[[Any], bool]
# Search contract: search(pid, role, name, nth) -> element | None.
SearchFn = Callable[[int, str, str, int], Any]


class RefStore:
    """Generation-scoped registry for element and window refs."""

    def __init__(self) -> None:
        self.generation = 0
        self.elements: dict[str, ElementRef] = {}
        self.windows: dict[str, WindowRef] = {}
        self._e_seq = 0
        self._w_seq = 0
        self._ordinals: dict[tuple, int] = {}
        self.created_at = time.time()

    # ---------- generation ----------

    def new_generation(self) -> int:
        """Mint a fresh generation; every prior ref goes stale."""
        self.generation += 1
        self.elements.clear()
        self.windows.clear()
        self._ordinals.clear()
        self.created_at = time.time()
        return self.generation

    # ---------- registration ----------

    def add_element(
        self,
        element: Any,
        pid: int,
        role: str,
        name: str,
        bbox: dict | None = None,
        metadata: dict | None = None,
    ) -> ElementRef:
        key = (pid, role, name)
        nth = self._ordinals.get(key, 0)
        self._ordinals[key] = nth + 1
        self._e_seq += 1
        er = ElementRef(
            ref=f"@e{self._e_seq}",
            pid=int(pid),
            role=role or "",
            name=name or "",
            nth=nth,
            bbox=bbox,
            element=element,
            generation=self.generation,
            metadata=metadata or {},
        )
        self.elements[er.ref] = er
        return er

    def add_synthetic(self, bbox: dict, name: str,
                      metadata: dict | None = None) -> ElementRef:
        """OCR/visual hit — resolvable to coordinates only."""
        self._e_seq += 1
        er = ElementRef(
            ref=f"@e{self._e_seq}",
            pid=0,
            role="synthetic",
            name=name or "",
            bbox=bbox,
            element=None,
            synthetic=True,
            generation=self.generation,
            metadata=metadata or {},
        )
        self.elements[er.ref] = er
        return er

    def add_window(self, element: Any, pid: int, title: str,
                   geometry: dict | None = None) -> WindowRef:
        self._w_seq += 1
        wr = WindowRef(
            ref=f"@w{self._w_seq}",
            pid=int(pid),
            title=title or "",
            element=element,
            geometry=geometry,
            generation=self.generation,
        )
        self.windows[wr.ref] = wr
        return wr

    # ---------- lookup ----------

    def get(self, ref: str) -> ElementRef | WindowRef:
        obj = self.elements.get(ref) or self.windows.get(ref)
        if obj is None:
            raise StaleRef(f"unknown ref {ref}",
                           hint="refs mint from Snapshot/list_windows")
        if obj.generation != self.generation:
            raise StaleRef(
                f"{ref} is from generation {obj.generation} "
                f"(current {self.generation})",
                hint="take a fresh Snapshot")
        return obj

    def try_get(self, ref: str) -> ElementRef | WindowRef | None:
        try:
            return self.get(ref)
        except CuError:
            return None

    def is_ref(self, s: Any) -> bool:
        return isinstance(s, str) and len(s) > 2 and s[0] == "@" and s[1] in "ew"

    # ---------- resolution ----------

    def resolve_element(
        self,
        ref: str,
        probe: ProbeFn | None = None,
        search: SearchFn | None = None,
    ) -> ElementRef:
        """Resolve @eN to a live element (or a synthetic bbox-only ref).

        Args:
            probe: liveness check for the held element handle.
            search: re-search fallback (pid, role, name, nth) -> element.

        Returns:
            The ElementRef; ``element`` refreshed when re-search succeeds.

        Raises:
            StaleRef: when nothing resolves.
        """
        er = self.get(ref)
        if not isinstance(er, ElementRef):
            raise StaleRef(f"{ref} is a window ref, not an element ref")
        if er.synthetic:
            return er                       # coords only — nothing to probe
        # 1. live probe
        if er.element is not None and probe is not None:
            try:
                if probe(er.element):
                    return er
            except Exception:
                pass
        # 2. runtime re-search
        if search is not None:
            try:
                el = search(er.pid, er.role, er.name, er.nth)
            except Exception:
                el = None
            if el is not None:
                er.element = el
                return er
        raise StaleRef(
            f"{ref} ({er.role} '{er.name}') no longer resolves",
            hint="element died or UI changed; take a fresh Snapshot")


# Module-level singleton used by tree/desktop layers.
STORE = RefStore()
