"""Ref registry: issues @eN refs, resolves them back to live UIA controls.

Resolution ladder (cheapest first):
  1. live probe on the stored uia.Control (one property read)
  2. re-walk the recorded index_path inside the owning window + RuntimeId match
  3. AutomationId (+ControlType) FindFirst inside the owning window
  4. bounded window subtree scan comparing RuntimeIds
  5. give up -> RefError(STALE_REF)

Refs are never reused. Old refs keep working while their element stays alive,
so an agent can act on an element several times without re-snapshotting.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

import windows_mcp.uia as uia
from windows_mcp.refs.locator import ElementLocator

logger = logging.getLogger(__name__)

# How many RuntimeId comparisons a window subtree scan may perform before
# giving up. Bounded so a huge window can't stall a ref resolution.
_SCAN_LIMIT = 3000


class RefError(Exception):
    """Structured ref failure.

    code is one of: INVALID_REF, UNKNOWN_REF, STALE_REF, AMBIGUOUS_REF,
    NO_TREE, ACCESS_DENIED.
    """

    def __init__(self, code: str, message: str, hint: str = "", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:
        text = f"{self.code}: {self.message}"
        if self.hint:
            text += f" | hint: {self.hint}"
        return text


def _probe_alive(control: Any) -> bool:
    """Return True if the element behind `control` is still usable.

    Checks two independent liveness signals because UIA proxies can "ghost"
    for ~1s after the provider dies — a stale COM call may still succeed.
    BoundingRectangle proves the element responds; the owning process check
    catches ghosts that answer from a dying channel.
    """
    if control is None:
        return False
    try:
        _ = control.BoundingRectangle
    except Exception:
        return False
    try:
        pid = control.ProcessId
    except Exception:
        return False
    if pid:
        try:
            import psutil

            if not psutil.pid_exists(pid):
                return False
        except ImportError:
            pass
    return True


def _runtime_id_of(control: Any) -> tuple[int, ...] | None:
    try:
        return tuple(int(v) for v in (control.GetRuntimeId() or ()))
    except Exception:
        return None


def _descend_index_path(window: Any, index_path: Iterable[int]) -> Any | None:
    """Walk child indices from the window root. Returns the control or None."""
    node = window
    for index in index_path:
        try:
            children = node.GetChildren()
        except Exception:
            return None
        if index < 0 or index >= len(children):
            return None
        node = children[index]
    return node


def _control_type_int(name: str) -> int | None:
    """Map programmatic control type name ('ButtonControl') to its UIA int."""
    if not name:
        return None
    value = getattr(uia.ControlType, name, None)
    return int(value) if isinstance(value, int) else None


class RefStore:
    """Registry of element locators issued so far.

    `latest` maps the flat label index of the most recent snapshot
    (interactive nodes first, then scrollable nodes — the same numbering the
    legacy `label` argument uses) to its locator, so `label` and `@eN` resolve
    through the same identity path.
    """

    def __init__(self, capacity: int = 5000):
        self._next_ref = 1
        self._locators: dict[int, ElementLocator] = {}
        self.latest: dict[int, ElementLocator] = {}
        self.capacity = capacity
        self.generation = 0

    # -- issuance ---------------------------------------------------------

    def rebuild(self, locators: list[ElementLocator]) -> None:
        """Assign refs to a fresh snapshot's locators and refresh `latest`.

        `locators` must already be in flat label order (interactive first,
        then scrollable). Old locators stay registered — their elements may
        still be alive.
        """
        self.generation += 1
        self.latest = {}
        for flat_index, locator in enumerate(locators):
            if locator.ref == 0:
                locator.ref = self._next_ref
                self._next_ref += 1
                self._locators[locator.ref] = locator
            self.latest[flat_index] = locator
        self._evict()

    def _evict(self) -> None:
        if len(self._locators) <= self.capacity:
            return
        overflow = len(self._locators) - self.capacity
        for ref in sorted(self._locators)[:overflow]:
            del self._locators[ref]

    # -- parsing ----------------------------------------------------------

    @staticmethod
    def parse_ref(value: str | int) -> int:
        """Normalize 'e5', '@e5', '#e5', '5' to the ref int 5."""
        if isinstance(value, bool):
            raise RefError("INVALID_REF", f"invalid ref {value!r}")
        if isinstance(value, int):
            if value > 0:
                return value
            raise RefError("INVALID_REF", f"ref must be positive, got {value}")
        text = str(value).strip()
        for prefix in ("@e", "#e", "e", "@", "#"):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
                break
        if not text.isdigit() or int(text) <= 0:
            raise RefError("INVALID_REF", f"invalid ref {value!r}")
        return int(text)

    # -- resolution -------------------------------------------------------

    def get(self, ref: int) -> ElementLocator:
        locator = self._locators.get(ref)
        if locator is None:
            raise RefError(
                "UNKNOWN_REF",
                f"ref @e{ref} is not registered (evicted or never issued)",
                hint="call Snapshot to list current elements",
            )
        return locator

    def resolve(self, ref: int) -> ElementLocator:
        """Resolve a ref to a live element. Raises RefError on failure."""
        locator = self.get(ref)
        if locator.synthetic:
            # No UIA backing — resolution is just its stored rectangle.
            return locator
        if _probe_alive(locator.control):
            self._refresh_box(locator)
            return locator
        control = self._reresolve(locator)
        locator.control = control
        self._refresh_box(locator)
        return locator

    def resolve_index(self, flat_index: int) -> ElementLocator:
        """Resolve a legacy numeric label to its locator (current snapshot)."""
        locator = self.latest.get(flat_index)
        if locator is None:
            raise RefError(
                "ELEMENT_NOT_FOUND",
                f"label {flat_index} out of range for the latest snapshot",
                hint="call Snapshot to refresh the element list",
            )
        return self.resolve(locator.ref)

    # -- internals --------------------------------------------------------

    def _refresh_box(self, locator: ElementLocator) -> None:
        try:
            rect = locator.control.BoundingRectangle
            box = locator.bounding_box
            if box is not None and rect is not None:
                box.left, box.top = rect.left, rect.top
                box.right, box.bottom = rect.right, rect.bottom
                box.width, box.height = rect.width(), rect.height()
        except Exception:
            pass

    def _window_control(self, locator: ElementLocator) -> Any | None:
        handle = locator.window_handle
        if not handle:
            return None
        try:
            win = uia.ControlFromHandle(handle)
            if win is not None and _probe_alive(win):
                return win
        except Exception:
            pass
        # The window handle may have changed (app restart). Fall back to the
        # owning process and pick the window that contains the element name.
        if locator.process_id:
            try:
                win = uia.WindowControl(ProcessId=locator.process_id, searchDepth=1)
                if win.Exists(maxSearchSeconds=1):
                    # Exists() can race process exit / pid reuse — verify.
                    if getattr(win, "ProcessId", None) == locator.process_id:
                        return win
            except Exception:
                pass
        return None

    def _reresolve(self, locator: ElementLocator) -> Any:
        window = self._window_control(locator)
        if window is not None:
            # 1) index_path + runtime_id verification
            if locator.index_path:
                candidate = _descend_index_path(window, locator.index_path)
                if candidate is not None and _probe_alive(candidate):
                    if (
                        locator.runtime_id is None
                        or _runtime_id_of(candidate) == locator.runtime_id
                    ):
                        return candidate
            # 2) AutomationId (+ControlType) subtree search
            if locator.automation_id:
                candidate = self._find_by_automation_id(window, locator)
                if candidate is not None:
                    return candidate
            # 3) bounded runtime-id scan
            if locator.runtime_id:
                candidate = self._scan_runtime_id(window, locator.runtime_id)
                if candidate is not None:
                    return candidate
        # Window gone or element truly absent.
        raise RefError(
            "STALE_REF",
            f"element for @e{locator.ref} no longer exists "
            f"({locator.control_type} {locator.name!r})",
            hint="the UI changed; call Snapshot and use a fresh ref",
            retryable=False,
        )

    def _find_by_automation_id(self, window: Any, locator: ElementLocator) -> Any | None:
        conditions = [
            uia.CreatePropertyCondition(
                uia.PropertyId.AutomationIdProperty, locator.automation_id
            )
        ]
        ct = _control_type_int(locator.control_type)
        if ct is not None:
            conditions.append(
                uia.CreatePropertyCondition(uia.PropertyId.ControlTypeProperty, ct)
            )
        condition = conditions[0]
        for extra in conditions[1:]:
            condition = uia.CreateAndCondition(condition, extra)
        try:
            # FindFirst already returns a wrapped Control subclass.
            candidate = window.FindFirst(uia.TreeScope.TreeScope_Descendants, condition)
        except Exception:
            return None
        if candidate is not None and _probe_alive(candidate):
            return candidate
        return None

    def _scan_runtime_id(self, window: Any, runtime_id: tuple[int, ...]) -> Any | None:
        try:
            elements = window.FindAll(
                uia.TreeScope.TreeScope_Descendants, uia.CreateTrueCondition()
            )
        except Exception:
            return None
        for candidate in elements[:_SCAN_LIMIT]:
            if _runtime_id_of(candidate) == runtime_id:
                if _probe_alive(candidate):
                    return candidate
                return None
        return None
