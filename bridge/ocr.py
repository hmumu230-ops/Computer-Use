"""Tiered OCR / text-find fallback.

Tier0 — AT-SPI tree text search (zero deps): match name/Text iface content,
      `get_range_extents` gives exact sub-string rects.
Tier1 — `tesseract <img> stdout tsv` (system package).
Tier2 — `rapidocr` optional Python engine.

Hits become synthetic @eN refs registered in the RefStore — same shape as
a11y refs, so click/act work uniformly.
"""
from __future__ import annotations

import csv
import io
import os
import re
import tempfile

import a11y
from errors import CuError, EngineUnavailable, ToolNotFound
from util import run, which


# ---------- tier 0: AT-SPI text search ----------

def find_text_in_tree(root, needle: str, limit: int = 20) -> list[dict]:
    hits = []
    if root is None:
        return hits
    for ax in a11y.walk(root, interesting_only=False, max_elements=600):
        node = ax.node
        # match name first
        hay = ax.name or ""
        idx = hay.lower().find(needle.lower())
        bbox = ax.bbox
        if idx < 0:
            ti = None
            try:
                ti = node.get_text_iface()
            except Exception:
                ti = None
            if ti is not None:
                try:
                    txt = ti.get_text(0, -1) or ""
                    idx = txt.lower().find(needle.lower())
                    if idx >= 0:
                        # precise sub-string rect when the iface supports it
                        try:
                            A = a11y.ats()
                            r = ti.get_range_extents(
                                idx, idx + len(needle), A.CoordType.SCREEN)
                            bbox = {"x": r.x, "y": r.y,
                                    "w": r.width, "h": r.height}
                        except Exception:
                            pass
                except Exception:
                    pass
        if idx >= 0 and bbox:
            hits.append({"role": ax.role, "name": ax.name,
                         "bbox": bbox, "node": node, "via": "atspi"})
            if len(hits) >= limit:
                break
    return hits


# ---------- tier 1: tesseract ----------

def _tesseract(img_path: str, needle: str) -> list[dict]:
    if which("tesseract") is None:
        raise ToolNotFound("tesseract", hint="apt install tesseract-ocr")
    r = run(["tesseract", img_path, "stdout", "tsv"], timeout=30)
    rows = list(csv.DictReader(io.StringIO(r.stdout), delimiter="\t"))
    # group consecutive words into lines and match needle on line text
    hits = []
    lines: dict[tuple, list[dict]] = {}
    for row in rows:
        try:
            conf = float(row.get("conf", -1))
            text = row.get("text", "") or ""
            if conf < 0 or not text.strip():
                continue
            key = (row["block_num"], row["par_num"], row["line_num"])
            lines.setdefault(key, []).append(row)
        except Exception:
            continue
    for words in lines.values():
        line_text = " ".join(w["text"] for w in words)
        if needle.lower() in line_text.lower():
            x = min(int(w["left"]) for w in words)
            y = min(int(w["top"]) for w in words)
            x2 = max(int(w["left"]) + int(w["width"]) for w in words)
            y2 = max(int(w["top"]) + int(w["height"]) for w in words)
            hits.append({"bbox": {"x": x, "y": y, "w": x2 - x, "h": y2 - y},
                         "text": line_text, "via": "tesseract"})
    return hits


# ---------- tier 2: rapidocr (optional) ----------

def _rapidocr(img_path: str, needle: str) -> list[dict]:
    try:
        from rapidocr import RapidOCR
    except ImportError:
        raise EngineUnavailable(
            "rapidocr not installed",
            hint="pip install rapidocr (or rely on tesseract/AT-SPI tiers)")
    engine = RapidOCR()
    out = engine(img_path)
    hits = []
    # rapidocr 3.x → RapidOCROutput {boxes, txts, scores}; older → list
    boxes = getattr(out, "boxes", None)
    txts = getattr(out, "txts", None)
    if boxes is None and isinstance(out, (list, tuple)) and len(out) >= 1:
        legacy = out[0] if isinstance(out[0], (list, tuple)) else out
        boxes = [b for b, *_ in legacy] if legacy else []
        txts = [t for _, t, *_ in legacy] if legacy else []
    for box, txt in zip(boxes or [], txts or []):
        if needle.lower() in str(txt).lower():
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            hits.append({"bbox": {"x": int(min(xs)), "y": int(min(ys)),
                                  "w": int(max(xs) - min(xs)),
                                  "h": int(max(ys) - min(ys))},
                         "text": str(txt), "via": "rapidocr"})
    return hits


# ---------- public ----------

def find_text(needle: str, image_path: str | None = None,
              atspi_root=None, region: dict | None = None,
              limit: int = 10) -> list[dict]:
    """Unified text find. AT-SPI tier runs when atspi_root given; OCR tiers
    run when image_path given."""
    hits: list[dict] = []
    if atspi_root is not None:
        try:
            hits += find_text_in_tree(atspi_root, needle, limit=limit)
        except Exception:
            pass
    if image_path:
        crop_path = image_path
        tmp = None
        if region:
            try:
                from PIL import Image
                img = Image.open(image_path)
                tmp = tempfile.mktemp(suffix=".png")
                img.crop((region["x"], region["y"],
                          region["x"] + region["w"],
                          region["y"] + region["h"])).save(tmp)
                crop_path = tmp
            except Exception:
                pass
        try:
            hits += _tesseract(crop_path, needle)
        except ToolNotFound:
            pass
        if not hits:
            try:
                hits += _rapidocr(crop_path, needle)
            except (EngineUnavailable, Exception):
                pass
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if region:
            for h in hits:
                if h.get("via") != "atspi":
                    h["bbox"]["x"] += region["x"]
                    h["bbox"]["y"] += region["y"]
    if not hits:
        raise CuError(f"text not found: {needle!r}",
                      hint="try a shorter needle, a larger region, or check "
                           "the app exposes AT-SPI text")
    return hits[:limit]
