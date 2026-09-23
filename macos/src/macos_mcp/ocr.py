"""OCR via the native Vision framework (VNRecognizeTextRequest).

No external engine to install — Vision ships with macOS 10.15+ and is
reached through pyobjc-framework-Vision. All PyObjC imports are lazy so
this module imports cleanly off-macOS.

Coordinates: Vision reports normalized bounding boxes with a bottom-left
origin; ``recognize`` re-bases them into pixel space with a top-left
origin, matching every other coordinate in this package. When a PIL
image that covers the whole screen is passed, add ``offset`` of the
capture region to land in screen space.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Tuple

from .errors import EngineUnavailable, CuError


@dataclass
class OcrWord:
    text: str
    bbox: dict          # {x, y, w, h} in pixels, top-left origin
    confidence: float


def _vision():
    try:
        import Vision  # pyobjc-framework-Vision
    except Exception as exc:  # pragma: no cover - macOS only
        raise EngineUnavailable(
            "Vision framework unavailable",
            hint="pip install pyobjc-framework-Vision (macOS 10.15+); "
                 f"import failed: {exc}")
    return Vision


def _cgimage_from_png(png: bytes):
    """PNG bytes -> CGImage via CGImageSource (no PIL dependency)."""
    try:
        from Quartz import (
            CGImageSourceCreateWithData,
            CGImageSourceCreateImageAtIndex,
        )
        from Foundation import NSData
    except Exception as exc:  # pragma: no cover
        raise EngineUnavailable("Quartz unavailable", hint=str(exc))
    data = NSData.dataWithBytes_length_(png, len(png))
    src = CGImageSourceCreateWithData(data, None)
    if src is None:
        raise CuError("could not decode image for OCR")
    img = CGImageSourceCreateImageAtIndex(src, 0, None)
    if img is None:
        raise CuError("CGImageSource produced no image")
    return img


def _cgimage_from_pil(image) -> "object":
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return _cgimage_from_png(buf.getvalue()), image.size


def recognize(image, languages: List[str] | None = None,
              offset: Tuple[int, int] = (0, 0)) -> List[OcrWord]:
    """Run Vision text recognition on a PIL Image.

    Returns OcrWord list with pixel-space top-left-origin boxes, already
    offset by ``offset`` (the image's top-left point in screen space).
    """
    Vision = _vision()
    cgimg, (w, h) = _cgimage_from_pil(image)

    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(
        Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(True)
    if languages:
        req.setRecognitionLanguages_(list(languages))

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cgimg, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise CuError("Vision request failed",
                      hint=str(err)[:200] if err else "unknown")

    ox, oy = offset
    out: List[OcrWord] = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        box = obs.boundingBox()          # normalized, bottom-left origin
        out.append(OcrWord(
            text=str(cand[0].string()),
            confidence=float(cand[0].confidence()),
            bbox={
                "x": int(box.origin.x * w) + ox,
                "y": int((1.0 - box.origin.y - box.size.height) * h) + oy,
                "w": int(box.size.width * w),
                "h": int(box.size.height * h),
            },
        ))
    return out


def find_text(image, needle: str, languages: List[str] | None = None,
              offset: Tuple[int, int] = (0, 0),
              case_sensitive: bool = False) -> List[OcrWord]:
    """OCR ``image`` and return words whose text contains ``needle``."""
    words = recognize(image, languages=languages, offset=offset)
    if not case_sensitive:
        needle = needle.casefold()
        return [wd for wd in words if needle in wd.text.casefold()]
    return [wd for wd in words if needle in wd.text]
