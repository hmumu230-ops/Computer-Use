"""OCR engine output-normalization tests.

Covers both supported return shapes without loading a real engine:
- rapidocr 3.x: RapidOCROutput object (.boxes/.txts/.scores)
- legacy rapidocr-onnxruntime: (result, elapse) tuple
"""

from __future__ import annotations

import sys
import types

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
    def __call__(self, img):
        # 3.x engines receive the PIL image directly (LoadImage does RGB->BGR)
        assert isinstance(img, Image.Image)
        return _OutV3(
            np.array([[[0, 0], [10, 0], [10, 5], [0, 5]]]),
            ["hello"],
            [0.9],
        )


class _EngineV3Empty:
    def __call__(self, img):
        return _OutV3(None, None, None)


class _EngineV1:
    def __call__(self, arr):
        # legacy engines receive an ndarray already flipped to BGR
        assert isinstance(arr, np.ndarray)
        return ([[[[0, 0], [8, 0], [8, 4], [0, 4]], "world", 0.8]], 12.0)


@pytest.fixture(autouse=True)
def fake_engine(monkeypatch):
    def setter(eng, legacy=False):
        monkeypatch.setattr(engine, "_ENGINE", eng)
        monkeypatch.setattr(engine, "_ENGINE_LEGACY", legacy)

    yield setter
    # plain assignment — monkeypatch.setattr here would *restore* whatever a
    # test left behind (e.g. a real _engine() result), leaking it onward.
    engine._ENGINE = None
    engine._ENGINE_TRIED = False
    engine._ENGINE_LEGACY = False
    engine._ENGINE_ERROR = None


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


def test_v3_none_output(fake_engine):
    class _NoneEngine:
        def __call__(self, img):
            return None

    fake_engine(_NoneEngine())
    assert engine.ocr_image(_img()) == []


def test_v3_scores_none_pads_zeros(fake_engine):
    class _Partial:
        def __call__(self, img):
            return _OutV3(np.array([[[0, 0], [5, 0], [5, 5], [0, 5]]]), ["x"], None)

    fake_engine(_Partial())
    words = engine.ocr_image(_img())
    assert len(words) == 1 and words[0].score == 0.0


def test_v1_tuple_shape(fake_engine):
    fake_engine(_EngineV1(), legacy=True)
    words = engine.ocr_image(_img())
    assert len(words) == 1
    assert words[0].text == "world"
    assert (words[0].right, words[0].bottom) == (8, 4)


def test_negative_virtual_screen_offset(fake_engine):
    """Multi-monitor: virtual screen origin is negative when a monitor sits
    left/above the primary — offsets must land the word on the right pixel."""
    fake_engine(_EngineV3())
    words = engine.ocr_image(_img(), offset=(-1920, 0))
    assert words[0].left == -1920 and words[0].right == -1910


def test_find_substring_and_case(fake_engine):
    fake_engine(_EngineV3())
    words = engine.ocr_image(_img())
    assert engine.find(words, "HELL")
    assert not engine.find(words, "HELL", case_sensitive=True)
    assert engine.find(words, "hell", exact=True) == []
    assert engine.find(words, "hello", exact=True)


def test_find_collapses_query_whitespace(fake_engine):
    fake_engine(_EngineV3())
    words = engine.ocr_image(_img())
    # query with stray whitespace still matches a normalized word
    assert engine.find(words, "  hello  ")
    assert engine.find(words, "  hello  ", exact=True)


def test_engine_init_failure_retries_and_keeps_error(monkeypatch):
    """A failed first init must not latch forever — transient failures
    (model download interrupted, AV lock) should recover on the next call,
    and the original error text must reach the caller."""
    attempts = []

    class _FlakyRapidOCR:
        def __init__(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("model download interrupted")

    fake_mod = types.ModuleType("rapidocr")
    fake_mod.RapidOCR = _FlakyRapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr", fake_mod)

    with pytest.raises(engine.OcrError) as first:
        engine._engine()
    assert "model download interrupted" in first.value.message

    # second call retries the init and succeeds
    eng = engine._engine()
    assert isinstance(eng, _FlakyRapidOCR)
    assert len(attempts) == 2


def test_engine_missing_reports_both_errors(monkeypatch):
    monkeypatch.delitem(sys.modules, "rapidocr", raising=False)

    real_import = __import__

    def blocked(name, *args, **kwargs):
        if name.startswith("rapidocr"):
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked)
    with pytest.raises(engine.OcrError) as exc:
        engine._engine()
    assert exc.value.code == "ENGINE_UNAVAILABLE"
    assert "rapidocr" in exc.value.message
