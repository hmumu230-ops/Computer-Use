"""Clipboard service — read/write text, images, and file-drop lists.

Reading prefers structured formats in order: files (CF_HDROP) → image
(CF_DIB/CF_DIBV5/registered "PNG") → text (CF_UNICODETEXT). The returned
``formats`` list always reports every clipboard format name so callers can
see e.g. HTML or CSV payloads even when they aren't decoded.
"""

from __future__ import annotations

import io
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pywintypes
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


# One lock for every clipboard transaction in this process — the uia
# SetClipboardText path, the win32clipboard paths here, and _paste_text's
# read-modify-write-restore sequence all share it, so concurrent tools
# can't interleave mid-open.
CLIPBOARD_LOCK = threading.RLock()

_FORMAT_NAMES = {
    win32con.CF_TEXT: "CF_TEXT",
    win32con.CF_BITMAP: "CF_BITMAP",
    win32con.CF_DIB: "CF_DIB",
    win32con.CF_DIBV5: "CF_DIBV5",
    win32con.CF_HDROP: "CF_HDROP",
    win32con.CF_UNICODETEXT: "CF_UNICODETEXT",
    win32con.CF_LOCALE: "CF_LOCALE",
    win32con.CF_OEMTEXT: "CF_OEMTEXT",
    win32con.CF_ENHMETAFILE: "CF_ENHMETAFILE",
    win32con.CF_METAFILEPICT: "CF_METAFILEPICT",
    win32con.CF_TIFF: "CF_TIFF",
    win32con.CF_PALETTE: "CF_PALETTE",
}

_ERROR_ACCESS_DENIED = 5
_OPEN_TIMEOUT = 1.0
_OPEN_INTERVAL = 0.02


def _open_clipboard(timeout: float = _OPEN_TIMEOUT) -> None:
    """OpenClipboard with retry — it fails with 'Access is denied' whenever
    any other process (clipboard managers, rdpclip, Office listeners, or our
    own concurrent tool threads) holds it briefly."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            win32clipboard.OpenClipboard()
            return
        except pywintypes.error as e:
            if getattr(e, "winerror", None) != _ERROR_ACCESS_DENIED:
                raise
            if time.monotonic() >= deadline:
                raise
            time.sleep(_OPEN_INTERVAL)


def _close_clipboard() -> None:
    """CloseClipboard must never mask the primary error — when the clipboard
    was never opened or already released it raises error 1418, which would
    otherwise replace the real failure propagating out of the try block."""
    try:
        win32clipboard.CloseClipboard()
    except Exception:
        pass


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


def _png_clipboard_format() -> int:
    return win32clipboard.RegisterClipboardFormat("PNG")


def _dib_to_png(dib: bytes) -> bytes | None:
    """Decode raw CF_DIB bytes (no BITMAPFILEHEADER) into PNG bytes."""
    from PIL import BmpImagePlugin

    try:
        image = BmpImagePlugin.DibImageFile(io.BytesIO(dib))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def get_content() -> ClipboardContent:
    """Read the clipboard, decoding files/image/text payloads.

    Everything is sampled inside a single OpenClipboard session — opening
    twice (once for formats/text, again for the image) races other apps and
    can return a payload mix from two different clipboard generations.
    """
    dib_bytes: bytes | None = None
    png_bytes: bytes | None = None
    with CLIPBOARD_LOCK:
        _open_clipboard()
        try:
            formats = _enum_formats()

            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                try:
                    data = win32clipboard.GetClipboardData(win32con.CF_HDROP)
                    files = list(data) if data else []
                except Exception:
                    files = []
                if files and isinstance(files[0], int):
                    files = []  # malformed HDROP (bytes, not paths)
                if files:
                    return ClipboardContent(kind="files", files=files, formats=formats)

            # Prefer a registered "PNG" payload (exact bytes, keeps alpha);
            # fall back to DIB/DIBV5 which need header reconstruction.
            if win32clipboard.IsClipboardFormatAvailable(_png_clipboard_format()):
                try:
                    data = win32clipboard.GetClipboardData(_png_clipboard_format())
                    if isinstance(data, (bytes, bytearray)) and data[:8] == b"\x89PNG\r\n\x1a\n":
                        png_bytes = bytes(data)
                except Exception:
                    pass
            if png_bytes is None:
                for fmt in (win32con.CF_DIBV5, win32con.CF_DIB):
                    if win32clipboard.IsClipboardFormatAvailable(fmt):
                        try:
                            data = win32clipboard.GetClipboardData(fmt)
                            if isinstance(data, (bytes, bytearray)):
                                dib_bytes = bytes(data)
                                break
                        except Exception:
                            pass

            has_text = win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
            try:
                text = (
                    win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    if has_text
                    else None
                )
            except Exception:
                text = None
        finally:
            _close_clipboard()

    if png_bytes is not None:
        return ClipboardContent(
            kind="image", image_png=png_bytes, text=text, formats=formats
        )
    if dib_bytes is not None:
        image_png = _dib_to_png(dib_bytes)
        if image_png is not None:
            return ClipboardContent(
                kind="image", image_png=image_png, text=text, formats=formats
            )

    if text is not None:
        return ClipboardContent(kind="text", text=text, formats=formats)

    return ClipboardContent(kind="empty", formats=formats)


def set_text(text: str) -> dict[str, Any]:
    """Set clipboard text (CF_UNICODETEXT)."""
    with CLIPBOARD_LOCK:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            _close_clipboard()
    return {"kind": "text", "chars": len(text)}


def set_image_bytes(png: bytes, dib_fallback: bytes | None = None) -> dict[str, Any]:
    """Put PNG bytes on the clipboard as registered "PNG" + CF_DIB.

    Writing the PNG format preserves alpha — Chrome/Slack/Office prefer it;
    CF_DIB is kept as the universal fallback (alpha is lost there).
    """
    from PIL import Image

    if dib_fallback is None:
        with Image.open(io.BytesIO(png)) as src:
            buf = io.BytesIO()
            src.convert("RGB").save(buf, format="BMP")
        dib_fallback = buf.getvalue()[14:]  # strip BITMAPFILEHEADER
    with CLIPBOARD_LOCK:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(_png_clipboard_format(), png)
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib_fallback)
        finally:
            _close_clipboard()
    return {"kind": "image"}


def set_image(path: str) -> dict[str, Any]:
    """Put an image file on the clipboard (paste-able everywhere)."""
    from PIL import Image

    path = str(Path(path).expanduser().resolve())
    if not Path(path).exists():
        raise FileNotFoundError(f"image file does not exist: {path}")

    raw = Path(path).read_bytes()
    is_png = raw[:8] == b"\x89PNG\r\n\x1a\n"

    # DIB fallback needs a BMP render; PNG sources keep their exact bytes.
    buf = io.BytesIO()
    with Image.open(path) as image:
        size = image.size
        image.convert("RGB").save(buf, format="BMP")
    dib = buf.getvalue()[14:]

    if is_png:
        set_image_bytes(raw, dib_fallback=dib)
    else:
        # Non-PNG source: re-encode as PNG for the registered format.
        png_buf = io.BytesIO()
        with Image.open(path) as image:
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(
                png_buf, format="PNG"
            )
        set_image_bytes(png_buf.getvalue(), dib_fallback=dib)
    return {"kind": "image", "path": path, "size": size}


_DROPEFFECT_COPY = 1
_DROPEFFECT_MOVE = 2


def set_files(paths: list[str], cut: bool = False) -> dict[str, Any]:
    """Put a file-drop list on the clipboard (CF_HDROP) so Ctrl+V pastes files."""
    resolved = [str(Path(p).expanduser().resolve()) for p in paths]
    for p in resolved:
        if not Path(p).exists():
            raise FileNotFoundError(f"clipboard file does not exist: {p}")
    # DROPFILES struct: DWORD pFiles, POINT pt, BOOL fNC, BOOL fWide,
    # then a double-NUL-terminated wide-char file list.
    file_list = "".join(p + "\0" for p in resolved) + "\0"
    blob = struct.pack("<IiiII", 20, 0, 0, 0, 1) + file_list.encode("utf-16-le")
    drop_effect = win32clipboard.RegisterClipboardFormat("Preferred DropEffect")
    with CLIPBOARD_LOCK:
        _open_clipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, blob)
            # Explorer defaults a bare HDROP to copy; the effect DWORD lets
            # callers express a real cut.
            win32clipboard.SetClipboardData(
                drop_effect, struct.pack("<I", _DROPEFFECT_MOVE if cut else _DROPEFFECT_COPY)
            )
        finally:
            _close_clipboard()
    return {"kind": "files", "files": resolved, "effect": "cut" if cut else "copy"}
