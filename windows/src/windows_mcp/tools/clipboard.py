"""Clipboard tool — copy/paste clipboard operations (text, image, files)."""

from typing import Literal

from mcp.types import ToolAnnotations
from windows_mcp.infrastructure import with_analytics
from windows_mcp import clipboard as clip
from fastmcp import Context
from fastmcp.utilities.types import Image


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="Clipboard",
        description=(
            "Clipboard operations for text, images, and files. mode='get' reads the "
            "clipboard — returns text, an image (PNG), or a list of dropped files "
            "depending on content, plus all available format names. mode='set' writes "
            "text. mode='set_image' puts an image file (path=) on the clipboard so "
            "Ctrl+V pastes it into apps. mode='set_files' puts files (paths=[...]) on "
            "the clipboard so Ctrl+V pastes the files themselves (e.g. into Explorer)."
        ),
        annotations=ToolAnnotations(
            title="Clipboard",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Clipboard-Tool")
    def clipboard_tool(
        mode: Literal["get", "set", "set_image", "set_files"],
        text: str | None = None,
        path: str | None = None,
        paths: list[str] | None = None,
        save_path: str | None = None,
        ctx: Context = None,
    ):
        if mode == "get":
            content = clip.get_content()
            header = f"Clipboard formats: {', '.join(content.formats) or 'none'}"
            if content.kind == "text":
                return f"{header}\nClipboard content:\n{content.text}"
            if content.kind == "files":
                listing = "\n".join(content.files)
                return f"{header}\nClipboard contains {len(content.files)} file(s):\n{listing}"
            if content.kind == "image":
                if save_path:
                    with open(save_path, "wb") as f:
                        f.write(content.image_png)
                    note = f"\nSaved to {save_path}."
                else:
                    note = ""
                text_part = f"{header}\nClipboard contains an image.{note}"
                if content.text:
                    text_part += f"\nAlso has text: {content.text[:500]}"
                return [text_part, Image(data=content.image_png, format="png")]
            return f"{header}\nClipboard is empty or holds an undecoded format."
        if mode == "set":
            if text is None:
                return "Error: text parameter required for set mode."
            result = clip.set_text(text)
            preview = text[:100] + ("..." if len(text) > 100 else "")
            return f"Clipboard set to {result['chars']} chars: {preview}"
        if mode == "set_image":
            if path is None:
                return "Error: path parameter required for set_image mode."
            result = clip.set_image(path)
            return (
                f"Clipboard set to image {result['path']} "
                f"({result['size'][0]}x{result['size'][1]}). Paste with Ctrl+V."
            )
        if mode == "set_files":
            if not paths:
                return "Error: paths parameter required for set_files mode."
            result = clip.set_files(paths)
            return (
                f"Clipboard set to {len(result['files'])} file(s). "
                "Paste with Ctrl+V in Explorer or a file dialog."
            )
        return 'Error: mode must be "get", "set", "set_image", or "set_files".'
