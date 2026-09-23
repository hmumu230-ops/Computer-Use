"""Clipboard payloads: text, image, and file lists.

Text goes through pbcopy/pbpaste so it works even without PyObjC;
images and file lists need NSPasteboard (AppKit) and are imported
lazily so this module stays importable off-macOS.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from .errors import CuError, PermissionRequired


def _run(cmd: list[str], data: bytes | None = None, timeout: float = 10) -> bytes:
    proc = subprocess.run(
        cmd, input=data, capture_output=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise CuError(
            f"clipboard command failed: {' '.join(cmd)}",
            hint=proc.stderr.decode(errors="replace").strip()[:200],
        )
    return proc.stdout


# ---------------- text ----------------


def get_text() -> str:
    return _run(["pbpaste"]).decode("utf-8", errors="replace")


def set_text(text: str) -> str:
    _run(["pbcopy"], data=text.encode("utf-8"))
    return f"copied {len(text)} chars"


# ---------------- image ----------------


def _pasteboard():
    try:
        from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeFileURL  # noqa
    except Exception as exc:  # pragma: no cover - macOS only
        raise CuError("AppKit/NSPasteboard unavailable", hint=str(exc))
    return NSPasteboard


def get_image() -> Optional[bytes]:
    """PNG bytes of the clipboard image, or None if none is present."""
    try:
        from AppKit import NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeTIFF
        from Quartz import (
            CGImageDestinationCreateWithData,
            CGImageDestinationAddImage,
            CGImageDestinationFinalize,
            CGImageSourceCreateWithData,
            CGImageSourceCreateImageAtIndex,
        )
        from Foundation import NSMutableData, NSData
    except Exception as exc:  # pragma: no cover
        raise CuError("image clipboard requires PyObjC", hint=str(exc))

    pb = NSPasteboard.generalPasteboard()
    data = pb.dataForType_(NSPasteboardTypePNG)
    if data is not None:
        return bytes(data)
    tiff = pb.dataForType_(NSPasteboardTypeTIFF)
    if tiff is None:
        return None
    # Convert TIFF -> PNG via CGImageDestination
    src = CGImageSourceCreateWithData(tiff, None)
    if src is None:
        return None
    img = CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        return None
    out = NSMutableData.alloc().init()
    dest = CGImageDestinationCreateWithData(out, "public.png", 1, None)
    CGImageDestinationAddImage(dest, img, None)
    if not CGImageDestinationFinalize(dest):
        return None
    return bytes(out)


def set_image(png: bytes) -> str:
    try:
        from AppKit import NSPasteboard, NSPasteboardTypePNG
        from Foundation import NSData
    except Exception as exc:  # pragma: no cover
        raise CuError("image clipboard requires PyObjC", hint=str(exc))
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    ok = pb.setData_forType_(
        NSData.dataWithData_(png), NSPasteboardTypePNG
    )
    if not ok:
        raise CuError("failed to write PNG to clipboard")
    return f"copied image ({len(png)} bytes)"


# ---------------- files ----------------


def get_files() -> List[str]:
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeFileURL
    except Exception as exc:  # pragma: no cover
        raise CuError("file clipboard requires PyObjC", hint=str(exc))
    pb = NSPasteboard.generalPasteboard()
    urls = pb.propertyListForType_(NSPasteboardTypeFileURL)
    if not urls:
        # modern API: read NSURL objects
        from Foundation import NSURL

        objs = pb.readObjectsForClasses_options_([NSURL], None) or []
        return [u.path() for u in objs if getattr(u, "isFileURL", lambda: True)()]
    if isinstance(urls, str):
        urls = [urls]
    from Foundation import NSURL

    out = []
    for u in urls:
        url = NSURL.URLWithString_(u) if isinstance(u, str) else u
        path = url.path() if hasattr(url, "path") else str(u)
        out.append(path)
    return out


def set_files(paths: List[str]) -> str:
    try:
        from AppKit import NSPasteboard
        from Foundation import NSURL, NSArray
    except Exception as exc:  # pragma: no cover
        raise CuError("file clipboard requires PyObjC", hint=str(exc))
    urls = [NSURL.fileURLWithPath_(p) for p in paths]
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    ok = pb.writeObjects_(NSArray.arrayWithArray_(urls))
    if not ok:
        raise CuError("failed to write file URLs to clipboard")
    return f"copied {len(paths)} file(s)"


def clipboard(what: str = "text", text: str = "",
              image_png: bytes | None = None,
              files: List[str] | None = None,
              get: bool = False) -> dict:
    """Unified entry: what in {text,image,files}; get=True reads."""
    if get:
        if what == "text":
            return {"text": get_text()}
        if what == "image":
            data = get_image()
            return {"image_png": data}
        if what == "files":
            return {"files": get_files()}
        raise CuError(f"unknown clipboard payload '{what}'")
    if what == "text":
        return {"result": set_text(text)}
    if what == "image":
        if image_png is None:
            raise CuError("image payload requires image_png bytes")
        return {"result": set_image(image_png)}
    if what == "files":
        return {"result": set_files(files or [])}
    raise CuError(f"unknown clipboard payload '{what}'")
