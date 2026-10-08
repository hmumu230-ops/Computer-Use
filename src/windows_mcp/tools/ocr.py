"""FindText tool — OCR-based text location for UIA-invisible UI.

OCR results are registered as synthetic @eN refs, so a hit is immediately
clickable via Click(ref=...) / Type(ref=...) without copying coordinates.
"""

import json

from mcp.types import ToolAnnotations
from windows_mcp.infrastructure import with_analytics
from windows_mcp.ocr import find, ocr_image
from windows_mcp.refs.locator import ElementLocator
from windows_mcp.tree.views import BoundingBox
from fastmcp import Context

_MAX_MATCHES = 20


def _as_region(value: list | str | None) -> list | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise ValueError("region must be a [left, top, right, bottom] list")
    return list(value)


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="FindText",
        description=(
            "Locates on-screen text via OCR — the fallback for UIA-invisible UI "
            "(custom-drawn controls, canvases, games, remote desktop content). "
            "Returns matches as @eN refs that Click/Type accept directly in ref=. "
            "text: the string to find (substring match by default; exact=True for "
            "whole-line equality). region=[left,top,right,bottom] limits the scan "
            "area for speed and accuracy. all=False returns only the best match."
        ),
        annotations=ToolAnnotations(
            title="FindText",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "FindText-Tool")
    def find_text_tool(
        text: str,
        region: list[int] | str | None = None,
        exact: bool | str = False,
        all: bool | str = True,
        ctx: Context = None,
    ) -> str:
        if not text:
            raise ValueError("text must be a non-empty string")
        desktop = get_desktop()
        region = _as_region(region)
        exact = exact is True or (isinstance(exact, str) and exact.lower() == "true")
        all_matches = all is True or (isinstance(all, str) and all.lower() == "true")

        capture_rect = None
        if region is not None:
            if len(region) != 4:
                raise ValueError("region must be [left, top, right, bottom]")
            capture_rect = desktop.parse_region_selection(region)
            offset = (capture_rect.left, capture_rect.top)
        else:
            # Full-capture backends grab the whole *virtual* screen whose
            # origin (SM_XVIRTUALSCREEN/SM_YVIRTUALSCREEN) is negative when a
            # monitor sits left/above the primary — without this offset every
            # @eN ref and reported coordinate is off by one monitor's width.
            from windows_mcp import uia

            offset = uia.GetVirtualScreenRect()[:2]

        image = desktop.get_screenshot(capture_rect)
        words = ocr_image(image, offset=offset)

        matches = find(words, text, exact=exact)
        if not matches:
            sample = ", ".join(sorted({w.text for w in words})[:15])
            return (
                f"No match for {text!r} "
                f"({len(words)} text regions OCR'd). "
                + (f"Detected text includes: {sample}" if sample else "No text detected.")
            )

        if not all_matches:
            matches = matches[:1]
        matches = matches[:_MAX_MATCHES]

        lines = []
        for w in matches:
            box = BoundingBox(
                left=w.left,
                top=w.top,
                right=w.right,
                bottom=w.bottom,
                width=w.width,
                height=w.height,
            )
            locator = ElementLocator.synthetic_locator(bounding_box=box)
            ref = desktop.ref_store.register(locator)
            cx, cy = w.center
            lines.append(f"  @e{ref} {w.text!r} at ({cx},{cy}) conf={w.score:.2f}")

        header = f"Found {len(matches)} match(es) for {text!r}"
        if not all_matches:
            header += " (best only)"
        return header + ":\n" + "\n".join(lines)
