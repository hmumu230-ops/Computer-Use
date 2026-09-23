"""Window management — minimize/maximize/restore/topmost/move/resize/close."""

from __future__ import annotations

import ctypes
from typing import Any

import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32


def _enum_windows() -> list[dict[str, Any]]:
    out = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)
            show = placement[1]
            state = {1: "normal", 2: "minimized", 3: "maximized"}.get(show, str(show))
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            out.append(
                {
                    "hwnd": hwnd,
                    "title": title,
                    "pid": pid,
                    "rect": list(rect),
                    "state": state,
                    "topmost": bool(ex & win32con.WS_EX_TOPMOST),
                }
            )
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def list_windows(title_filter: str | None = None) -> dict[str, Any]:
    windows = _enum_windows()
    if title_filter:
        t = title_filter.casefold()
        windows = [w for w in windows if t in w["title"].casefold()]
    return {"windows": windows, "count": len(windows)}


def _resolve_window(window: str | int | None, hwnd: int | None) -> int:
    if hwnd is not None:
        if not win32gui.IsWindow(hwnd):
            raise ValueError(f"hwnd {hwnd} is not a valid window")
        return hwnd
    if window is None:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            raise ValueError("no foreground window")
        return hwnd
    t = str(window).casefold()
    matches = [w for w in _enum_windows() if t in w["title"].casefold()]
    if not matches:
        raise ValueError(f"no window matching {window!r}")
    if len(matches) > 1:
        raise ValueError(
            f"window {window!r} is ambiguous — matches: "
            + ", ".join(f"{m['title']!r}(hwnd={m['hwnd']})" for m in matches[:8])
        )
    return matches[0]["hwnd"]


def window_info(window: str | int | None = None, hwnd: int | None = None) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    _, pid = win32process.GetWindowThreadProcessId(target)
    rect = win32gui.GetWindowRect(target)
    placement = win32gui.GetWindowPlacement(target)
    ex = win32gui.GetWindowLong(target, win32con.GWL_EXSTYLE)
    return {
        "hwnd": target,
        "title": win32gui.GetWindowText(target),
        "pid": pid,
        "rect": list(rect),
        "state": {1: "normal", 2: "minimized", 3: "maximized"}.get(placement[1]),
        "topmost": bool(ex & win32con.WS_EX_TOPMOST),
        "foreground": win32gui.GetForegroundWindow() == target,
    }


def set_state(
    window: str | int | None = None, state: str = "normal", hwnd: int | None = None
) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    flags = {
        "minimize": win32con.SW_MINIMIZE,
        "maximize": win32con.SW_MAXIMIZE,
        "restore": win32con.SW_RESTORE,
        "normal": win32con.SW_RESTORE,
        "show": win32con.SW_SHOW,
        "hide": win32con.SW_HIDE,
    }
    if state not in flags:
        raise ValueError(f"state must be one of: {', '.join(flags)}")
    win32gui.ShowWindow(target, flags[state])
    return window_info(hwnd=target)


def set_topmost(
    window: str | int | None = None, topmost: bool = True, hwnd: int | None = None
) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    win32gui.SetWindowPos(
        target,
        win32con.HWND_TOPMOST if topmost else win32con.HWND_NOTOPMOST,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
    )
    return window_info(hwnd=target)


def move_resize(
    window: str | int | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
    hwnd: int | None = None,
) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    left, top, right, bottom = win32gui.GetWindowRect(target)
    nx = left if x is None else x
    ny = top if y is None else y
    nw = (right - left) if width is None else width
    nh = (bottom - top) if height is None else height
    win32gui.SetWindowPos(target, 0, nx, ny, nw, nh, win32con.SWP_NOZORDER)
    return window_info(hwnd=target)


def close_window(window: str | int | None = None, hwnd: int | None = None) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    title = win32gui.GetWindowText(target)
    win32gui.PostMessage(target, win32con.WM_CLOSE, 0, 0)
    return {"closed": title, "hwnd": target}


def bring_to_front(window: str | int | None = None, hwnd: int | None = None) -> dict[str, Any]:
    target = _resolve_window(window, hwnd)
    # SetForegroundWindow can be refused for background processes; the
    # AttachThreadInput trick attaches to the foreground thread's input queue
    # first so Windows treats us as part of the active input flow.
    fg = win32gui.GetForegroundWindow()
    if fg != target:
        try:
            cur = win32process.GetCurrentThreadId()
            fg_tid = win32process.GetWindowThreadProcessId(fg)[0]
            tg_tid = win32process.GetWindowThreadProcessId(target)[0]
            user32.AttachThreadInput(cur, fg_tid, True)
            user32.AttachThreadInput(cur, tg_tid, True)
            win32gui.ShowWindow(target, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(target)
            win32gui.BringWindowToTop(target)
            user32.AttachThreadInput(cur, fg_tid, False)
            user32.AttachThreadInput(cur, tg_tid, False)
        except Exception:
            win32gui.SetForegroundWindow(target)
    return window_info(hwnd=target)


def snap(
    window: str | int | None = None, side: str = "left", hwnd: int | None = None
) -> dict[str, Any]:
    """Snap a window to a screen half via Win+Arrow — simplest reliable tiling."""
    target = _resolve_window(window, hwnd)
    bring_to_front(hwnd=target)
    keys = {"left": 0x25, "right": 0x27, "up": 0x26, "down": 0x28}
    if side not in keys:
        raise ValueError(f"side must be one of: {', '.join(keys)}")
    user32.keybd_event(0x5B, 0, 0, 0)  # WIN down
    user32.keybd_event(keys[side], 0, 0, 0)
    user32.keybd_event(keys[side], 0, 2, 0)  # key up
    user32.keybd_event(0x5B, 0, 2, 0)  # WIN up
    return window_info(hwnd=target)
