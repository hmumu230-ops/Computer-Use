"""Clipboard: xclip/xsel (X11), wl-clipboard (Wayland).

Owner-serves model: the process that sets the clipboard must stay alive to
serve paste requests. xclip daemonizes itself when given input; wl-copy
forks with --paste-on-newline off by default for text (it backgrounds). For
multi-target needs (file lists) we use xclip -t with text/uri-list.
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
import uuid

import detect
from errors import CuError, ToolNotFound
from util import run, run_out, which

_TARGET_FILELIST = "text/uri-list"


def _tool() -> tuple[str, str]:
    """Return ('x11'|'wl', binary_prefix) or raise."""
    env = detect.detect_env()
    if env.session_type == "x11":
        if which("xclip"):
            return "x11", "xclip"
        if which("xsel"):
            return "x11", "xsel"
        raise ToolNotFound("xclip/xsel", hint="apt install xclip")
    if which("wl-copy"):
        return "wl", "wl-copy"
    raise ToolNotFound("wl-clipboard", hint="apt install wl-clipboard")


def targets() -> list[str]:
    mode, _ = _tool()
    if mode == "x11" and which("xclip"):
        out = run_out(["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                      timeout=5)
        return [l.strip() for l in out.splitlines() if l.strip()]
    if mode == "wl":
        out = run_out(["wl-paste", "--list-types"], timeout=5)
        return [l.strip() for l in out.splitlines() if l.strip()]
    if mode == "x11":  # xsel — no TARGETS query
        return []
    return []


def get_text() -> str:
    mode, _ = _tool()
    if mode == "x11":
        if which("xclip"):
            return run_out(["xclip", "-selection", "clipboard", "-o"], timeout=5)
        return run_out(["xsel", "-b", "-o"], timeout=5)
    return run_out(["wl-paste", "--no-newline"], timeout=5)


def set_text(text: str) -> dict:
    mode, _ = _tool()
    if mode == "x11":
        if which("xclip"):
            p = subprocess.Popen(["xclip", "-selection", "clipboard"],
                                 stdin=subprocess.PIPE, text=True)
            p.communicate(text, timeout=5)
        else:
            p = subprocess.Popen(["xsel", "-b", "-i"],
                                 stdin=subprocess.PIPE, text=True)
            p.communicate(text, timeout=5)
        return {"set": "text", "chars": len(text)}
    p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
    p.communicate(text, timeout=5)
    return {"set": "text", "chars": len(text)}


def get_image() -> dict:
    """Return {pngBase64} or raise."""
    ts = targets()
    mode, _ = _tool()
    img_t = next((t for t in ts if t in ("image/png", "image/jpeg",
                                         "image/bmp")), None)
    if not img_t:
        raise CuError("no image target on clipboard")
    if mode == "x11":
        r = run(["xclip", "-selection", "clipboard", "-o", "-t", img_t],
                timeout=5, binary=True)
        data = r.stdout if isinstance(r.stdout, bytes) else r.stdout.encode()
    else:
        r = run(["wl-paste", "-t", img_t], timeout=5, binary=True)
        data = r.stdout if isinstance(r.stdout, bytes) else r.stdout.encode()
    return {"format": img_t, "pngBase64": base64.b64encode(data).decode()}


def set_image(png_b64: str) -> dict:
    data = base64.b64decode(png_b64)
    mode, _ = _tool()
    if mode == "x11":
        p = subprocess.Popen(
            ["xclip", "-selection", "clipboard", "-t", "image/png"],
            stdin=subprocess.PIPE)
        p.communicate(data, timeout=10)
        return {"set": "image/png", "bytes": len(data)}
    p = subprocess.Popen(["wl-copy", "-t", "image/png"], stdin=subprocess.PIPE)
    p.communicate(data, timeout=10)
    return {"set": "image/png", "bytes": len(data)}


def set_files(paths: list[str]) -> dict:
    uris = []
    for p in paths:
        ap = os.path.abspath(os.path.expanduser(p))
        uris.append("file://" + ap)
    payload = "\r\n".join(uris) + "\r\n"
    mode, _ = _tool()
    if mode == "x11" and which("xclip"):
        p = subprocess.Popen(
            ["xclip", "-selection", "clipboard", "-t", _TARGET_FILELIST],
            stdin=subprocess.PIPE, text=True)
        p.communicate(payload, timeout=5)
        return {"set": "files", "count": len(uris)}
    if mode == "wl":
        p = subprocess.Popen(["wl-copy", "-t", _TARGET_FILELIST],
                             stdin=subprocess.PIPE, text=True)
        p.communicate(payload, timeout=5)
        return {"set": "files", "count": len(uris)}
    raise CuError("xsel cannot set file lists", hint="install xclip")


def get_files() -> list[str]:
    mode, _ = _tool()
    if _TARGET_FILELIST not in targets():
        return []
    if mode == "x11":
        out = run_out(["xclip", "-selection", "clipboard", "-o",
                       "-t", _TARGET_FILELIST], timeout=5)
    else:
        out = run_out(["wl-paste", "-t", _TARGET_FILELIST], timeout=5)
    files = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("file://"):
            import urllib.parse
            files.append(urllib.parse.unquote(
                urllib.parse.urlparse(line).path))
    return files


def clear() -> None:
    mode, _ = _tool()
    if mode == "x11" and which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard", "/dev/null"],
                       timeout=5)
    elif mode == "wl":
        subprocess.Popen(["wl-copy", "--clear"])
    else:
        subprocess.run(["xsel", "-b", "-c"], timeout=5)
