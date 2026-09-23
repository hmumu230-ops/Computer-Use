"""OCR engine wrapper — RapidOCR (ONNX Runtime) with clean degradation.

The engine is optional: when ``rapidocr`` (3.x, preferred) or the legacy
``rapidocr-onnxruntime`` package is not installed every entry point raises
``OcrError(code="ENGINE_UNAVAILABLE")`` with an install hint instead of
ImportError noise. OCR'd words carry *screen* coordinates — ``offset``
re-bases region captures into desktop pixel space.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_ENGINE: Any = None
_ENGINE_TRIED = False


class OcrError(Exception):
    """Structured OCR failure: code/message/hint, mirroring RefError."""

    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        text = f"{self.code}: {self.message}"
        if self.hint:
            text += f" | hint: {self.hint}"
        return text


@dataclass
class OcrWord:
    """One detected text run with screen-space bounds."""

    text: str
    left: int
    top: int
    right: int
    bottom: int
    score: float

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


def engine_available() -> bool:
    """True when the RapidOCR backend can be imported."""
    global _ENGINE_TRIED
    try:
        _engine()
        return True
    except OcrError:
        return False
    finally:
        _ENGINE_TRIED = True


def _engine() -> Any:
    global _ENGINE, _ENGINE_TRIED
    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_TRIED:
        raise OcrError(
            "ENGINE_UNAVAILABLE",
            "OCR engine failed to initialize earlier",
            hint="install rapidocr or check the server log",
        )
    _ENGINE_TRIED = True
    try:
        from rapidocr import RapidOCR  # 3.x (current)
    except ImportError:
        try:
            from rapidocr_onnxruntime import RapidOCR  # legacy 1.x
        except ImportError:
            raise OcrError(
                "ENGINE_UNAVAILABLE",
                "OCR engine is not installed",
                hint="pip install 'rapidocr>=3.0' "
                '(or run with "uvx --from windows-mcp windows-mcp --with rapidocr")',
            )
    try:
        _ENGINE = RapidOCR()
    except Exception as e:
        raise OcrError(
            "ENGINE_UNAVAILABLE",
            f"OCR engine failed to initialize: {e}",
            hint="onnxruntime may be missing or models failed to load",
        )
    return _ENGINE


def ocr_image(image: Any, offset: tuple[int, int] = (0, 0)) -> list[OcrWord]:
    """Run OCR on a PIL image. Returns words in screen coordinates.

    `offset` is the image's (left, top) in desktop pixels — pass the region
    origin so results land in click coordinates directly.
    """
    engine = _engine()
    try:
        import numpy as np

        arr = np.asarray(image.convert("RGB"))
    except Exception as e:
        raise OcrError("ENGINE_UNAVAILABLE", f"failed to convert image for OCR: {e}")
    try:
        out = engine(arr)
    except Exception as e:
        raise OcrError("ENGINE_UNAVAILABLE", f"OCR inference failed: {e}")

    # rapidocr 3.x returns RapidOCROutput (.boxes/.txts/.scores);
    # legacy rapidocr-onnxruntime returns (result, elapse).
    if hasattr(out, "txts"):
        boxes = list(out.boxes) if out.boxes is not None else []
        items = zip(boxes, out.txts or [], out.scores or [])
    else:
        result, _elapse = out
        items = result or []

    ox, oy = offset
    words: list[OcrWord] = []
    for box, text, score in items:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append(
            OcrWord(
                text=text,
                left=int(min(xs)) + ox,
                top=int(min(ys)) + oy,
                right=int(max(xs)) + ox,
                bottom=int(max(ys)) + oy,
                score=float(score),
            )
        )
    return words


def find(
    words: list[OcrWord],
    query: str,
    *,
    exact: bool = False,
    case_sensitive: bool = False,
) -> list[OcrWord]:
    """Match OCR'd words against `query`. Substring match by default.

    Matching collapses whitespace so "Save File" still hits a word OCR'd as
    "Save  File". Returns words sorted by score (best first).
    """
    if not case_sensitive:
        query = query.casefold()

    def norm(t: str) -> str:
        t = " ".join(t.split())
        return t if case_sensitive else t.casefold()

    matches = [w for w in words if (norm(w.text) == query if exact else query in norm(w.text))]
    return sorted(matches, key=lambda w: w.score, reverse=True)
