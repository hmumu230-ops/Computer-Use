"""Clipboard service — text/image/file clipboard operations."""

from .service import (
    ClipboardContent,
    get_content,
    set_files,
    set_image,
    set_text,
)

__all__ = [
    "ClipboardContent",
    "get_content",
    "set_files",
    "set_image",
    "set_text",
]
