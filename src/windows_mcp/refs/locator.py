"""Element identity captured at snapshot time for later ref resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ElementLocator:
    """Everything needed to re-find a UI element.

    `control` is the live `windows_mcp.uia.Control` proxy captured during tree
    traversal. It is the fastest resolution path: one cheap property probe
    tells us the element is still alive. When it dies (window closed, element
    rebuilt), the remaining identity fields drive re-resolution.
    """

    control: Any = None  # live uia.Control; None for synthetic (OCR/word) nodes
    runtime_id: tuple[int, ...] | None = None
    automation_id: str = ""
    name: str = ""
    control_type: str = ""  # programmatic name, e.g. "ButtonControl"
    window_handle: int = 0  # top-level window hwnd owning the element
    process_id: int = 0
    index_path: tuple[int, ...] = field(default_factory=tuple)
    bounding_box: Any = None  # last known BoundingBox (tree.views.BoundingBox)
    synthetic: bool = False  # True for elements without a UIA backing element
    ref: int = 0  # assigned by RefStore; 0 = unassigned

    @classmethod
    def from_control(
        cls,
        control: Any,
        *,
        name: str = "",
        control_type: str = "",
        window_handle: int = 0,
        index_path: tuple[int, ...] = (),
        bounding_box: Any = None,
    ) -> "ElementLocator":
        """Capture identity fields from a live UIA control."""
        try:
            runtime_id = tuple(int(v) for v in (control.GetRuntimeId() or ()))
        except Exception:
            runtime_id = None
        try:
            automation_id = control.CachedAutomationId or ""
        except Exception:
            try:
                automation_id = control.AutomationId or ""
            except Exception:
                automation_id = ""
        try:
            process_id = int(control.CachedProcessId)
        except Exception:
            try:
                process_id = int(control.ProcessId)
            except Exception:
                process_id = 0
        return cls(
            control=control,
            runtime_id=runtime_id,
            automation_id=automation_id,
            name=name,
            control_type=control_type,
            window_handle=window_handle,
            process_id=process_id,
            index_path=index_path,
            bounding_box=bounding_box,
        )

    @classmethod
    def synthetic_locator(cls, *, bounding_box: Any, window_handle: int = 0) -> "ElementLocator":
        """Locator for elements with no UIA backing (e.g. OCR word nodes)."""
        return cls(
            control=None,
            bounding_box=bounding_box,
            window_handle=window_handle,
            synthetic=True,
        )
