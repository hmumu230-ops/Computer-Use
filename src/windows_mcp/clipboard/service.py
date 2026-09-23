"""Clipboard service — read/write text, images, and file-drop lists.

Reading prefers structured formats in order: files (CF_HDROP) → image
(CF_DIB via PIL) → text (CF_UNICODETEXT). The returned ``formats`` list
always reports every clipboard format name so callers can see e.g. HTML
or CSV payloads even when they aren't decoded.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import win32clipboard
import win32con


@dataclass
class ClipboardContent:
    """Decoded clipboard payload."""

    kind: str  # "text" | "image" | "files" | "empty"
    text: str | None = None
    files: list[str] | None = None
    image_png: bytes | None = None
    formats: list[str] = field(default_factory=list)


_FORMAT_NAMES = {
    win32con.CF_TEXT: "CF_TEXT",
    win32con.CF_BITMAP: "CF_BITMAP",
    win32con.CF_DIB: "CF_DIB",
    win32con.CF_DIBV5: "CF_DIBV5",
    win32con.CF_HDROP: "CF_HDROP",
    win32con.CF_UNICODETEXT: "CF_UNICODETEXT",
    win32con.CF_LOCALE: "CF_LOCALE",
    win32con.CF_OEMTEXT: "CF_OEMTEXT",
}


def _enum_formats() -> list[str]:
    names = []
    fmt = 0
    while True:
        fmt = win32clipboard.EnumClipboardFormats(fmt)
        if fmt == 0:
            break
        if fmt in _FORMAT_NAMES:
            names.append(_FORMAT_NAMES[fmt])
        else:
            try:
                names.append(win32clipboard.GetClipboardFormatName(fmt))
            except Exception:
                names.append(f"CF_{fmt}")
    return names


def get_content() -> ClipboardContent:
    """Read the clipboard, decoding files/image/text payloads."""
    win32clipboard.OpenClipboard()
    try:
        formats = _enum_formats()

        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            files = list(win32clipboard.GetClipboardData(win32con.CF_HDROP))
            return ClipboardContent(kind="files", files=files, formats=formats)

        has_dib = win32clipboard.IsClipboardFormatAvailable(
            win32con.CF_DIB
        ) or win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIBV5)
        has_text = win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
        text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT) if has_text else None
    finally:
        win32clipboard.CloseClipboard()

    if has_dib:
        # ImageGrab handles the DIB→BMP header reconstruction internally.
        from PIL import ImageGrab

        image = ImageGrab.grabclipboard()
        if image is not None and not isinstance(image, list):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            return ClipboardContent(
                kind="image",
                image_png=buf.getvalue(),
                text=text,
                formats=formats,
            )

    if text is not None:
        return ClipboardContent(kind="text", text=text, formats=formats)

    return ClipboardContent(kind="empty", formats=formats)


def set_text(text: str) -> dict[str, Any]:
    """Set clipboard text (CF_UNICODETEXT)."""
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()
    return {"kind": "text", "chars": len(text)}


def set_image(path: str) -> dict[str, Any]:
    """Put an image file on the clipboard as CF_DIB (paste-able everywhere)."""
    from PIL import Image

    image = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="BMP")
    # CF_DIB = BMP pixel data without the 14-byte BITMAPFILEHEADER.
    dib = buf.getvalue()[14:]
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()
    return {"kind": "image", "path": str(Path(path).resolve()), "size": image.size}


def set_files(paths: list[str]) -> dict[str, Any]:
    """Put a file-drop list on the clipboard (CF_HDROP) so Ctrl+V pastes files."""
    resolved = [str(Path(p).resolve()) for p in paths]
    for p in resolved:
        if not Path(p).exists():
            raise FileNotFoundError(f"clipboard file does not exist: {p}")
    # DROPFILES struct: DWORD pFiles, POINT pt, BOOL fNC, BOOL fWide,
    # then a double-NUL-terminated wide-char file list.
    file_list = "".join(p + "\0" for p in resolved) + "\0"
    blob = struct.pack("<IiiII", 20, 0, 0, 0, 1) + file_list.encode("utf-16-le")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_HDROP, blob)
    finally:
        win32clipboard.CloseClipboard()
    return {"kind": "files", "files": resolved}
