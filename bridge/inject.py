"""Input-injection router.

X11     → xdotool (status quo)
Wayland → ydotool/dotool (uinput daemons) → python-evdev uinput →
          wtype (wlroots text) → portal RemoteDesktop (GNOME consent) →
          honest UNSUPPORTED when nothing is available.

Note: AT-SPI generate_*_event uses XTEST internally — X11 only, kept as a
last-resort X11 path in a11y.py.
"""
from __future__ import annotations

import time

import detect
from errors import CuError, UnsupportedCompositor, ToolNotFound
from util import run, run_out, which

_UINPUT_DELAY = 0.7   # uinput devices need settle time after creation


def _mode() -> str:
    env = detect.detect_env()
    if env.session_type == "x11":
        return "x11"
    if which("ydotool"):
        return "ydotool"
    if which("dotool"):
        return "dotool"
    try:
        import evdev  # noqa: F401
        return "evdev"
    except Exception:
        pass
    if env.compositor in ("sway", "hyprland", "labwc", "river") and which("wtype"):
        return "wtype"      # wlroots virtual-keyboard: text only
    return "none"


def backend_name() -> str:
    return _mode()


# ---------- mouse ----------

def mouse_move(x: int, y: int) -> None:
    m = _mode()
    if m == "x11":
        run(["xdotool", "mousemove", str(int(x)), str(int(y))])
    elif m == "ydotool":
        # ydotool moves are absolute via mousemove --absolute
        run(["ydotool", "mousemove", "--absolute", "--",
             str(int(x)), str(int(y))], timeout=5)
    elif m == "dotool":
        _dotool(f"mousemove {int(x)} {int(y)}\n")
    elif m == "evdev":
        _evdev_abs(int(x), int(y))
    else:
        raise _no_input("pointer move")


def mouse_click(x: int | None, y: int | None, button: str = "left",
                count: int = 1) -> None:
    m = _mode()
    btn = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
    if x is not None and y is not None:
        mouse_move(int(x), int(y))
    if m == "x11":
        cmd = ["xdotool"]
        for _ in range(max(1, int(count))):
            cmd += ["click", btn]
        run(cmd)
    elif m == "ydotool":
        codes = {"1": "0x110", "2": "0x112", "3": "0x111"}
        c = codes[btn]
        for _ in range(max(1, int(count))):
            run(["ydotool", "click", c], timeout=5)
    elif m == "dotool":
        b = {"1": "left", "2": "middle", "3": "right"}[btn]
        _dotool(f"click {b}\n" * max(1, int(count)))
    elif m == "evdev":
        _evdev_click(btn, count)
    else:
        raise _no_input("mouse click")


def scroll(x: int | None, y: int | None, dx: int, dy: int) -> None:
    m = _mode()
    if x is not None and y is not None:
        mouse_move(int(x), int(y))
    ticks_y = max(1, abs(dy) // 40) if dy else 0
    ticks_x = max(1, abs(dx) // 40) if dx else 0
    if m == "x11":
        by, bx = ("5" if dy > 0 else "4"), ("7" if dx > 0 else "6")
        for _ in range(ticks_y):
            run(["xdotool", "click", by])
        for _ in range(ticks_x):
            run(["xdotool", "click", bx])
    elif m == "ydotool":
        for _ in range(ticks_y):
            run(["ydotool", "click", "0x11" if dy < 0 else "0x12"], timeout=5)
        for _ in range(ticks_x):
            run(["ydotool", "click", "0x13" if dx < 0 else "0x14"], timeout=5)
    elif m == "dotool":
        acts = ("wheeldown" if dy > 0 else "wheelup")
        _dotool(f"{acts}\n" * ticks_y)
    elif m == "evdev":
        _evdev_scroll(dx, dy)
    else:
        raise _no_input("scroll")


def drag(x1: int, y1: int, x2: int, y2: int, button: str = "left") -> None:
    """Drag = press, small-step move (sub-stepping defeats synthetic-event
    heuristics in toolkits), release."""
    m = _mode()
    steps = 12
    if m == "x11":
        run(["xdotool", "mousemove", str(x1), str(y1), "mousedown", "1"])
        for i in range(1, steps + 1):
            xi = x1 + (x2 - x1) * i // steps
            yi = y1 + (y2 - y1) * i // steps
            run(["xdotool", "mousemove", str(xi), str(yi)])
            time.sleep(0.02)
        run(["xdotool", "mouseup", "1"])
    elif m in ("ydotool", "dotool", "evdev"):
        mouse_move(x1, y1)
        _press(button, down=True)
        for i in range(1, steps + 1):
            mouse_move(x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
            time.sleep(0.02)
        _press(button, down=False)
    else:
        raise UnsupportedCompositor(
            "synthetic drag unavailable", compositor=detect.detect_env().compositor,
            hint="Wayland forbids synthetic DnD; use clipboard+Ctrl+V as fallback")


def _press(button: str, down: bool) -> None:
    m = _mode()
    if m == "ydotool":
        codes = {"left": "0x110", "middle": "0x112", "right": "0x111"}
        flag = "1" if down else "0"
        run(["ydotool", "click", "-D", "0", "--next-delay", "0",
             codes.get(button, "0x110")], timeout=5)
    elif m == "dotool":
        b = {"left": "left", "middle": "middle", "right": "right"}[button]
        _dotool(f"mousedown {b}\n" if down else f"mouseup {b}\n")
    elif m == "evdev":
        _evdev_btn(button, down)


# ---------- keyboard ----------

_XDO_KEY = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "tab": "Tab", "space": "space", "backspace": "BackSpace", "delete": "Delete",
    "del": "Delete", "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    "ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
    "meta": "super", "super": "super", "cmd": "super", "command": "super",
}
_MODS = {"ctrl", "control", "shift", "alt", "meta", "super", "cmd", "command"}


def _xdo_key(token: str) -> str:
    parts = token.replace(" ", "").split("+")
    return "+".join(_XDO_KEY.get(p.lower(), p if len(p) > 1 else p.lower())
                    for p in parts)


def keypress(keys: list[str]) -> None:
    if not keys:
        raise CuError("keypress needs keys")
    m = _mode()
    if m == "x11":
        if len(keys) > 1 and all(k.lower() in _MODS for k in keys[:-1]):
            chord = "+".join(_XDO_KEY.get(k.lower(), k.lower())
                             for k in keys[:-1])
            last = keys[-1]
            chord += "+" + _XDO_KEY.get(last.lower(),
                                        last if len(last) > 1 else last.lower())
            run(["xdotool", "key", chord])
        else:
            for k in keys:
                run(["xdotool", "key", _xdo_key(k)])
    elif m == "ydotool":
        for k in keys:
            for spec in _ydo_keyspec(k):
                run(["ydotool", "key", *spec], timeout=5)
    elif m == "dotool":
        for k in keys:
            _dotool(f"key {_dotool_keyname(k)}\n")
    elif m == "evdev":
        for k in keys:
            _evdev_key(k)
    else:
        raise _no_input("keypress")


def type_text(text: str, delay_ms: int = 8) -> None:
    m = _mode()
    if m == "x11":
        run(["xdotool", "type", "--delay", str(delay_ms), "--", text],
            timeout=max(10, len(text) * delay_ms / 1000 + 10))
    elif m == "ydotool":
        run(["ydotool", "type", "--next-delay", str(delay_ms), "--", text],
            timeout=max(10, len(text) * delay_ms / 1000 + 10))
    elif m == "dotool":
        _dotool(f"type {text}\n")
    elif m == "wtype":
        run(["wtype", "--", text],
            timeout=max(10, len(text) * delay_ms / 1000 + 10))
    elif m == "evdev":
        _evdev_type(text, delay_ms)
    else:
        raise _no_input("type")


# ---------- ydotool/dotool key specs ----------

_YDO_KEYS = {
    "enter": ["28:1", "28:0"], "return": ["28:1", "28:0"],
    "esc": ["1:1", "1:0"], "escape": ["1:1", "1:0"],
    "tab": ["15:1", "15:0"], "space": ["57:1", "57:0"],
    "backspace": ["14:1", "14:0"], "delete": ["111:1", "111:0"],
    "up": ["103:1", "103:0"], "down": ["108:1", "108:0"],
    "left": ["105:1", "105:0"], "right": ["106:1", "106:0"],
    "home": ["102:1", "102:0"], "end": ["107:1", "107:0"],
    "pageup": ["104:1", "104:0"], "pagedown": ["109:1", "109:0"],
}
_YDO_MODS = {"ctrl": 29, "control": 29, "shift": 42, "alt": 56,
             "super": 125, "meta": 125, "cmd": 125}


def _ydo_keyspec(token: str) -> list[list[str]]:
    """'ctrl+a' → [[29:1, 30:1, 30:0, 29:0]]. Multi-chord lists → one spec each."""
    parts = token.replace(" ", "").split("+")
    if len(parts) > 1 and all(p.lower() in _MODS for p in parts[:-1]):
        seq = []
        for p in parts[:-1]:
            seq.append(f"{_YDO_MODS[p.lower()]}:1")
        last = parts[-1].lower()
        key = _ydo_keycode(last)
        seq += [f"{key}:1", f"{key}:0"]
        for p in reversed(parts[:-1]):
            seq.append(f"{_YDO_MODS[p.lower()]}:0")
        return [seq]
    specs = []
    for p in parts:
        lp = p.lower()
        if lp in _YDO_KEYS:
            specs.append(_YDO_KEYS[lp])
        elif lp in _YDO_MODS:
            c = _YDO_MODS[lp]
            specs.append([f"{c}:1", f"{c}:0"])
        elif len(p) == 1:
            c = _char_keycode(p)
            specs.append([f"{c}:1", f"{c}:0"])
    return specs or []


def _ydo_keycode(name: str) -> int:
    if name in _YDO_KEYS:
        return int(_YDO_KEYS[name][0].split(":")[0])
    return _char_keycode(name)


def _char_keycode(ch: str) -> int:
    # evdev keycodes for US layout (KEY_*); enough for common typing fallback
    _MAP = {"a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34,
            "h": 35, "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49,
            "o": 24, "p": 25, "q": 16, "r": 19, "s": 31, "t": 20, "u": 22,
            "v": 47, "w": 17, "x": 45, "y": 21, "z": 44,
            "0": 11, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7,
            "7": 8, "8": 9, "9": 10, "-": 12, "=": 13, "[": 26, "]": 27,
            ";": 39, "'": 40, "`": 41, "\\": 43, ",": 51, ".": 52, "/": 53,
            " ": 57}
    return _MAP.get(ch.lower(), 30)


def _dotool_keyname(token: str) -> str:
    return token.lower().replace("ctrl", "ctrl").replace("return", "enter")


def _dotool(text: str) -> None:
    run(["dotool"], input_text=text, timeout=15)


# ---------- evdev uinput fallback ----------

def _evdev_dev():
    import evdev
    caps = {
        evdev.ecodes.EV_KEY: list(range(1, 248)) +
        [evdev.ecodes.BTN_LEFT, evdev.ecodes.BTN_RIGHT, evdev.ecodes.BTN_MIDDLE],
        evdev.ecodes.EV_REL: [evdev.ecodes.REL_X, evdev.ecodes.REL_Y,
                              evdev.ecodes.REL_WHEEL, evdev.ecodes.REL_HWHEEL],
        evdev.ecodes.EV_ABS: [evdev.ecodes.ABS_X, evdev.ecodes.ABS_Y],
    }
    ui = evdev.UInput(caps, name="lcu-uinput")
    time.sleep(_UINPUT_DELAY)   # let compositor pick the device up
    return ui


def _evdev_abs(x: int, y: int) -> None:
    import evdev
    ui = _evdev_dev()
    try:
        ui.write(evdev.ecodes.EV_ABS, evdev.ecodes.ABS_X, x)
        ui.write(evdev.ecodes.EV_ABS, evdev.ecodes.ABS_Y, y)
        ui.syn()
    finally:
        ui.close()


def _evdev_click(btn: str, count: int) -> None:
    import evdev
    code = {"1": evdev.ecodes.BTN_LEFT, "2": evdev.ecodes.BTN_MIDDLE,
            "3": evdev.ecodes.BTN_RIGHT}[btn]
    ui = _evdev_dev()
    try:
        for _ in range(max(1, int(count))):
            ui.write(evdev.ecodes.EV_KEY, code, 1)
            ui.write(evdev.ecodes.EV_KEY, code, 0)
            ui.syn()
            time.sleep(0.02)
    finally:
        ui.close()


def _evdev_btn(button: str, down: bool) -> None:
    import evdev
    code = {"left": evdev.ecodes.BTN_LEFT, "middle": evdev.ecodes.BTN_MIDDLE,
            "right": evdev.ecodes.BTN_RIGHT}[button]
    ui = _evdev_dev()
    try:
        ui.write(evdev.ecodes.EV_KEY, code, 1 if down else 0)
        ui.syn()
    finally:
        ui.close()


def _evdev_scroll(dx: int, dy: int) -> None:
    import evdev
    ui = _evdev_dev()
    try:
        if dy:
            ui.write(evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL,
                     -1 if dy > 0 else 1)
        if dx:
            ui.write(evdev.ecodes.EV_REL, evdev.ecodes.REL_HWHEEL,
                     -1 if dx > 0 else 1)
        ui.syn()
    finally:
        ui.close()


def _evdev_key(token: str) -> None:
    import evdev
    ui = _evdev_dev()
    try:
        parts = token.replace(" ", "").split("+")
        codes = []
        for p in parts:
            lp = p.lower()
            if lp in _YDO_MODS:
                codes.append(_YDO_MODS[lp])
            elif lp in _YDO_KEYS:
                codes.append(int(_YDO_KEYS[lp][0].split(":")[0]))
            elif len(p) == 1:
                codes.append(_char_keycode(p))
        for c in codes:
            ui.write(evdev.ecodes.EV_KEY, c, 1)
        ui.syn()
        time.sleep(0.02)
        for c in reversed(codes):
            ui.write(evdev.ecodes.EV_KEY, c, 0)
        ui.syn()
    finally:
        ui.close()


def _evdev_type(text: str, delay_ms: int) -> None:
    import evdev
    ui = _evdev_dev()
    try:
        for ch in text:
            if ch == "\n":
                code = 28
            else:
                code = _char_keycode(ch)
            shift = ch.isupper() or ch in "!@#$%^&*()_+{}|:\"<>?~"
            if shift:
                ui.write(evdev.ecodes.EV_KEY, 42, 1)
            ui.write(evdev.ecodes.EV_KEY, code, 1)
            ui.write(evdev.ecodes.EV_KEY, code, 0)
            if shift:
                ui.write(evdev.ecodes.EV_KEY, 42, 0)
            ui.syn()
            time.sleep(delay_ms / 1000)
    finally:
        ui.close()


def _no_input(op: str) -> CuError:
    env = detect.detect_env()
    return UnsupportedCompositor(
        f"no input-injection backend for {op} on {env.session_type}/{env.compositor}",
        compositor=env.compositor,
        hint="install ydotool (uinput daemon) or run on X11; GNOME can use "
             "the RemoteDesktop portal after consent")
