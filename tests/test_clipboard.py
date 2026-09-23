"""Tests for the clipboard service — text/image/files payloads."""

import pytest

import windows_mcp.clipboard.service as clip


@pytest.fixture
def fake_clipboard(monkeypatch):
    """In-memory win32clipboard shim."""
    import win32clipboard as wc

    state = {"formats": {}, "open": False}

    monkeypatch.setattr(wc, "OpenClipboard", lambda *a: state.__setitem__("open", True))
    monkeypatch.setattr(wc, "CloseClipboard", lambda: state.__setitem__("open", False))
    monkeypatch.setattr(wc, "EmptyClipboard", lambda: state["formats"].clear())
    monkeypatch.setattr(
        wc,
        "IsClipboardFormatAvailable",
        lambda fmt: fmt in state["formats"],
    )
    monkeypatch.setattr(wc, "GetClipboardData", lambda fmt: state["formats"].get(fmt))
    monkeypatch.setattr(
        wc,
        "SetClipboardData",
        lambda fmt, data: state["formats"].__setitem__(fmt, data),
    )
    monkeypatch.setattr(
        wc,
        "SetClipboardText",
        lambda text, fmt: state["formats"].__setitem__(fmt, text),
    )
    monkeypatch.setattr(
        wc,
        "EnumClipboardFormats",
        lambda fmt=0: next(iter(state["formats"].keys()), 0) if fmt == 0 else 0,
    )
    monkeypatch.setattr(wc, "GetClipboardFormatName", lambda fmt: f"FMT_{fmt}")
    return state


def test_get_text(fake_clipboard):
    import win32con

    fake_clipboard["formats"][win32con.CF_UNICODETEXT] = "hello"
    content = clip.get_content()
    assert content.kind == "text"
    assert content.text == "hello"
    assert "CF_UNICODETEXT" in content.formats


def test_get_empty(fake_clipboard):
    content = clip.get_content()
    assert content.kind == "empty"


def test_get_files(fake_clipboard):
    import win32con

    fake_clipboard["formats"][win32con.CF_HDROP] = (r"C:\a.txt", r"D:\b.png")
    content = clip.get_content()
    assert content.kind == "files"
    assert content.files == [r"C:\a.txt", r"D:\b.png"]


def test_set_text(fake_clipboard):
    import win32con

    clip.set_text("payload")
    assert fake_clipboard["formats"][win32con.CF_UNICODETEXT] == "payload"


def test_set_image_writes_dib(fake_clipboard, tmp_path):
    import win32con
    from PIL import Image

    img = Image.new("RGB", (10, 10), (0, 255, 0))
    img_path = tmp_path / "i.png"
    img.save(img_path)

    result = clip.set_image(str(img_path))
    assert result["kind"] == "image"
    dib = fake_clipboard["formats"][win32con.CF_DIB]
    # DIB data must not start with the 'BM' file magic (header stripped).
    assert dib[:2] != b"BM"
    assert len(dib) > 14


def test_set_files_builds_hdrop(fake_clipboard, tmp_path):
    import win32con

    f = tmp_path / "doc.txt"
    f.write_text("x")
    result = clip.set_files([str(f)])
    assert result["files"] == [str(f)]
    blob = fake_clipboard["formats"][win32con.CF_HDROP]
    # DROPFILES header is 20 bytes; file list is UTF-16LE double-NUL terminated.
    assert blob[:4] == (20).to_bytes(4, "little")
    body = blob[20:].decode("utf-16-le")
    assert str(f) in body
    assert body.endswith("\0\0")


def test_set_files_missing_raises(fake_clipboard, tmp_path):
    with pytest.raises(FileNotFoundError):
        clip.set_files([str(tmp_path / "nope.txt")])
