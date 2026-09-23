"""OCR layer — screen text detection via RapidOCR (optional dependency)."""

from windows_mcp.ocr.engine import OcrError, OcrWord, engine_available, find, ocr_image

__all__ = ["OcrError", "OcrWord", "engine_available", "find", "ocr_image"]
