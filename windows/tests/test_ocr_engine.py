"""OCR engine output-normalization tests.

Covers both supported return shapes without loading a real engine:
- rapidocr 3.x: RapidOCROutput object (.boxes/.txts/.scores)
- legacy rapidocr-onnxruntime: (result, elapse) tuple
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from windows_mcp.ocr import engine


class _OutV3:
    """Mimics rapidocr 3.x RapidOCROutput."""

    def __init__(self, boxes, txts, scores):
        self.boxes = boxes
        self.txts = txts
        self.scores = scores


class _EngineV3:
    def __call__(self, arr):
        return _OutV3(
            np.array([[[0, 0], [10, 0], [10, 5], [0, 5]]]),
            ["hello"],
            [0.9],
        )


class _EngineV3Empty:
    def __call__(self, arr):
        return _OutV3(None, None, None)


class _EngineV1:
    def __call__(self, arr):
        # legacy shape: (list_of_[box, text, score], elapse_ms)
        return ([[[[0, 0], [8, 0], [8, 4], [0, 4]], "world", 0.8]], 12.0)


@pytest.fixture(autouse=True)
def fake_engine(monkeypatch):
    yield lambda eng: monkeypatch.setattr(engine, "_ENGINE", eng)
    monkeypatch.setattr(engine, "_ENGINE", None)
    monkeypatch.setattr(engine, "_ENGINE_TRIED", False)


def _img() -> Image.Image:
    return Image.new("RGB", (20, 10))


def test_v3_output_shape(fake_engine):
    fake_engine(_EngineV3())
    words = engine.ocr_image(_img(), offset=(100, 50))
    assert len(words) == 1
    w = words[0]
    assert w.text == "hello"
    assert (w.left, w.top, w.right, w.bottom) == (100, 50, 110, 55)
    assert w.score == pytest.approx(0.9)


def test_v3_empty_result(fake_engine):
    fake_engine(_EngineV3Empty())
    assert engine.ocr_image(_img()) == []


def test_v1_tuple_shape(fake_engine):
    fake_engine(_EngineV1())
    words = engine.ocr_image(_img())
    assert len(words) == 1
    assert words[0].text == "world"
    assert (words[0].right, words[0].bottom) == (8, 4)


def test_find_substring_and_case(fake_engine):
    fake_engine(_EngineV3())
    words = engine.ocr_image(_img())
    assert engine.find(words, "HELL")
    assert not engine.find(words, "HELL", case_sensitive=True)
    assert engine.find(words, "hell", exact=True) == []
    assert engine.find(words, "hello", exact=True)
