"""OCR engine wrapper — RapidOCR (ONNX Runtime) with clean degradation.

The engine is optional: when ``rapidocr`` (3.x, preferred) or the legacy
``rapidocr-onnxruntime`` package is not installed every entry point raises
``OcrError(code="ENGINE_UNAVAILABLE")`` with an install hint instead of
ImportError noise. OCR'd words carry *screen* coordinates — ``offset``
re-bases region captures into desktop pixel space.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_ENGINE: Any = None
_ENGINE_TRIED = False
_ENGINE_LEGACY = False
_ENGINE_ERROR: Exception | None = None
_ENGINE_LOCK = threading.Lock()

# Downscale captures above this pixel count before inference — a 3x4K
# virtual desktop (~11520x2160) would otherwise eat ~150MB across the
# convert/copy cycle and push detection latency past client timeouts.
def _max_pixels() -> int:
    try:
        return int(os.environ.get("WINDOWS_MCP_OCR_MAX_PIXELS", "16000000"))
    except ValueError:
        return 16_000_000


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
    """True when the RapidOCR backend can be initialized.

    Note this is *not* a cheap import probe — it constructs the engine
    (paying the full model-load cost on first call). Use it as a warm-up
    or readiness gate, not a guard in hot paths.
    """
    try:
        _engine()
        return True
    except OcrError:
        return False


def _engine() -> Any:
    global _ENGINE, _ENGINE_TRIED, _ENGINE_LEGACY, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        _ENGINE_TRIED = True
        legacy = False
        try:
            from rapidocr import RapidOCR  # 3.x (current)
        except Exception as first_err:
            try:
                from rapidocr_onnxruntime import RapidOCR  # legacy 1.x
                legacy = True
            except Exception as second_err:
                _ENGINE_ERROR = second_err
                raise OcrError(
                    "ENGINE_UNAVAILABLE",
                    "OCR engine is not installed "
                    f"(rapidocr: {first_err}; rapidocr_onnxruntime: {second_err})",
                    hint="pip install 'rapidocr>=3.0' "
                    '(or run with "uvx --from windows-mcp windows-mcp --with rapidocr")',
                )
        try:
            _ENGINE = RapidOCR()
            _ENGINE_LEGACY = legacy
            _ENGINE_ERROR = None
        except Exception as e:
            _ENGINE_ERROR = e
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

    # Cap input size — otherwise a multi-monitor full-virtual-screen capture
    # multiplies into several full-frame copies and unbounded inference time.
    scale = 1.0
    try:
        from PIL import Image as _PILImage

        w, h = image.size
        max_px = _max_pixels()
        if w * h > max_px > 0:
            scale = math.sqrt(max_px / float(w * h))
            resample = getattr(getattr(_PILImage, "Resampling", _PILImage), "LANCZOS")
            image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), resample)
    except AttributeError:
        scale = 1.0  # unexpected image type — let the engine deal with it

    try:
        if _ENGINE_LEGACY:
            # Legacy LoadImage only normalizes str/Path/bytes/PIL — an ndarray
            # is passed through untouched and treated as OpenCV BGR, so feed
            # an explicit BGR array (RGB->BGR channel flip).
            import numpy as np

            arg = np.ascontiguousarray(np.asarray(image.convert("RGB"))[..., ::-1])
        else:
            # rapidocr 3.x LoadImage accepts PIL directly and does its own
            # RGB->BGR conversion — saves a full-frame convert+copy.
            arg = image
    except Exception as e:
        raise OcrError("IMAGE_CONVERSION_FAILED", f"failed to convert image for OCR: {e}")
    try:
        out = engine(arg)
    except Exception as e:
        raise OcrError("INFERENCE_FAILED", f"OCR inference failed: {e}")

    # rapidocr 3.x returns RapidOCROutput (.boxes/.txts/.scores);
    # legacy rapidocr-onnxruntime returns (result, elapse).
    if out is None:
        items = []
    elif hasattr(out, "txts"):
        # NB: out.boxes may be an ndarray — truthiness is ambiguous, check None
        boxes_attr = getattr(out, "boxes", None)
        boxes = list(boxes_attr) if boxes_attr is not None else []
        txts = list(out.txts or [])
        scores = list(out.scores or [])
        txts += [""] * (len(boxes) - len(txts))
        scores += [0.0] * (len(boxes) - len(scores))
        items = zip(boxes, txts, scores)
    else:
        try:
            result, _elapse = out
            items = result or []
        except Exception as e:
            raise OcrError("INFERENCE_FAILED", f"unexpected engine output shape: {e}")

    ox, oy = offset
    inv = 1.0 / scale if scale else 1.0
    words: list[OcrWord] = []
    for box, text, score in items:
        if box is None or len(box) == 0:
            continue
        xs = [p[0] * inv for p in box]
        ys = [p[1] * inv for p in box]
        words.append(
            OcrWord(
                text=text,
                left=math.floor(min(xs)) + ox,
                top=math.floor(min(ys)) + oy,
                right=math.floor(max(xs)) + ox,
                bottom=math.floor(max(ys)) + oy,
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
    # Collapse whitespace on the query side too — norm() already folds the
    # OCR'd word, so an unnormalized query ("save  file") would never match.
    query = " ".join(query.split())
    if not case_sensitive:
        query = query.casefold()

    def norm(t: str) -> str:
        t = " ".join(t.split())
        return t if case_sensitive else t.casefold()

    matches = [w for w in words if (norm(w.text) == query if exact else query in norm(w.text))]
    return sorted(matches, key=lambda w: w.score, reverse=True)
