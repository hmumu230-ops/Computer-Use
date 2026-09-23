"""Screenshot router.

Dispatch by session/compositor:
  X11      → scrot (or mss via python if present)
  wlroots  → grim
  KDE      → spectacle (ScreenShot2 needs a whitelisted binary — not used)
  generic  → portal Screenshot (interactive:false)
Window capture everywhere = fullscreen + crop to window geometry.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import detect
from errors import CuError, UnsupportedCompositor, ToolNotFound
from util import run, run_out, which


def _tmp_png() -> str:
    return os.path.join(tempfile.gettempdir(), f"lcu-{uuid.uuid4().hex[:10]}.png")


def _png_size(path: str) -> tuple[int, int]:
    try:
        with open(path, "rb") as f:
            data = f.read(32)
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                return (int.from_bytes(data[16:20], "big"),
                        int.from_bytes(data[20:24], "big"))
    except Exception:
        pass
    return 0, 0


def _crop(path: str, rect: dict, scale: float = 1.0) -> None:
    """Crop PNG in place. rect is logical coords; scale converts to pixels."""
    try:
        from PIL import Image
        img = Image.open(path)
        x, y = int(rect["x"] * scale), int(rect["y"] * scale)
        w, h = int(rect["w"] * scale), int(rect["h"] * scale)
        img.crop((x, y, x + w, y + h)).save(path)
    except ImportError:
        # ImageMagick fallback
        x, y = int(rect["x"] * scale), int(rect["y"] * scale)
        w, h = int(rect["w"] * scale), int(rect["h"] * scale)
        run(["convert", path, "-crop", f"{w}x{h}+{x}+{y}", "+repage", path],
            timeout=10)


def _logical_screen_size() -> tuple[int, int]:
    env = detect.detect_env()
    if env.session_type == "x11":
        out = run_out(["xdpyinfo"], timeout=4) or run_out(["xrandr"], timeout=4)
        for line in out.splitlines():
            if "dimensions:" in line:
                d = line.split("dimensions:")[1].split("pixels")[0].strip()
                w, h = d.split("x")
                return int(w), int(h)
    for tool in (["wlr-randr", "--json"], ["hyprctl", "monitors", "-j"],
                 ["kscreen-doctor", "-j"]):
        if which(tool[0]):
            try:
                import json
                arr = json.loads(run_out(tool, timeout=5))
                outs = arr if isinstance(arr, list) else arr.get("outputs", [])
                tw = sum(o.get("width", o.get("size", {}).get("width", 0))
                         for o in outs if isinstance(o, dict))
                th = max((o.get("height", o.get("size", {}).get("height", 0))
                          for o in outs if isinstance(o, dict)), default=0)
                if tw and th:
                    return tw, th
            except Exception:
                continue
    return 0, 0


def capture(region: dict | None = None,
            window_rect: dict | None = None) -> dict:
    """Return {path, width, height, scale, backend} for a PNG file.
    Caller reads + deletes the file. region/window_rect in logical coords."""
    env = detect.detect_env()
    path = _tmp_png()
    backend_used = ""

    if env.session_type == "x11":
        if which("scrot") is None:
            raise ToolNotFound("scrot")
        if region or window_rect:
            r = region or window_rect
            run(["scrot", "-o", "-a",
                 f"{r['x']},{r['y']},{r['w']},{r['h']}", path], timeout=8)
        else:
            run(["scrot", "-o", path], timeout=8)
        backend_used = "scrot"
        scale = 1.0
    else:
        comp = env.compositor
        if comp in ("sway", "hyprland", "labwc", "river", "wayfire",
                    "generic-wlroots") and which("grim"):
            run(["grim", path], timeout=8)
            backend_used = "grim"
        elif comp == "kde" and which("spectacle"):
            run(["spectacle", "-b", "-n", "-o", path], timeout=10)
            backend_used = "spectacle"
        else:
            import portal
            if not portal.portal_available():
                raise UnsupportedCompositor(
                    "no Wayland screenshot backend",
                    compositor=comp,
                    hint="install grim (wlroots) or xdg-desktop-portal")
            src = portal.screenshot_path()
            import shutil
            shutil.copyfile(src, path)
            backend_used = "portal"
        # Wayland captures are physical px; compute scale for logical crop
        lw, _lh = _logical_screen_size()
        iw, _ih = _png_size(path)
        scale = (iw / lw) if (lw and iw) else 1.0
        if region or window_rect:
            _crop(path, region or window_rect, scale=scale)

    w, h = _png_size(path)
    if w == 0:
        raise CuError("screenshot produced no image",
                      hint=f"backend={backend_used}")
    return {"path": path, "width": w, "height": h,
            "scale": scale, "backend": backend_used}
