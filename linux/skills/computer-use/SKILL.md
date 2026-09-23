---
name: computer-use
description: Linux desktop control — inspect, click, type into windows via AT-SPI (X11 + Wayland), plus clipboard, notifications, OCR fallback, and system administration. Returns @eN/@wN refs from the accessibility tree.
---

# computer-use (Linux)

## Quick Start

```
capabilities                            # what's supported on THIS session first
list_windows                            # → @wN list (title, pid, geometry)
snapshot {window:"@w2"}                 # screenshot + @eN element refs + generation
click {ref:"@e3"}                       # semantic action first, coords fallback
type_text {text:"hello"}                # type at cursor
keypress {keys:["Return"]}              # submit
```

## Tools

| name | use |
|---|---|
| capabilities | support matrix: window/input/screenshot/clipboard/atspi/ocr + hints |
| doctor | deep probe: init, compositor, groups, polkit, sudo |
| list_windows | @wN refs + geometry (null geometry on bare wlroots) |
| snapshot | PNG + @eN element refs + @wN windows + generation |
| screenshot | PNG only, no tree walk |
| find_elements | server-side search by role/name/states → fresh refs |
| find_text | AT-SPI text → tesseract → rapidocr; hits become synthetic @eN |
| wait_for | event-driven wait on AT-SPI signals |
| wait_for_text | wait until text appears |
| act | semantic verb on @eN: press/toggle/expand/collapse/select/showmenu/focus — ref only |
| click | @eN/@wN or x,y; `method=auto\|action\|synthetic` |
| type_text / keypress / scroll / move_mouse / drag | input |
| set_text | EditableText replace + readback verify; keyboard fallback |
| set_value | slider/spin via Value iface (write+verify) |
| select | list/menu item by index via Selection iface |
| computer_actions | batch ≤20, per-action results, `failFast` option |
| window_focus / window_close / window_move / window_state | WM ops (close is gated) |
| desktops / switch_desktop / window_to_desktop | virtual desktops |
| cursor_pos | pointer position (X11/KDE/Hyprland only) |
| clipboard_get / clipboard_set | text/image/files (text/uri-list) |
| notify / dnd | desktop notification + DND probe |
| launch_app | .desktop id, path, URI, or command |
| identity | user/groups/sudo/session |
| service | list/get/start/stop/restart/enable/disable (systemd; user scope) |
| task | list/add_timer/add_cron/remove_cron |
| power | uptime/inhibitors/lock/suspend/hibernate/poweroff/reboot (gated) |
| journal / dmesg | journalctl JSON / kernel ring |
| process | list/kill (kill is gated) |
| env | list/get/set/delete (session or persist=user) |
| audio | get/set/devices (wpctl→pactl→amixer) |
| network | adapters/status/wifi_list/wifi_connect/radio/proxy |
| display | brightness/set_brightness/list/night_light |
| device | block/usb/pci/printers |

## Conventions

- **Check `capabilities` first** — Wayland compositors differ wildly; every
  unsupported domain returns a hint.
- **Refs are generation-scoped.** Every `snapshot`/`list_windows` mints a new
  generation; stale refs error `STALE_REF` — re-snapshot, don't retry.
- **Semantic before synthetic.** `click {ref}` and `act` use AT-SPI actions
  (no pointer steal, works on unfocused windows); `method=synthetic` forces
  coordinate input.
- **Gated ops return `CONFIRM_REQUIRED` + confirmToken** — re-call with the
  token to execute. Tokens are single-use, action-bound, 60s TTL.
- All errors are structured `{code,message,hint,retryable}` — branch on `code`.

## Pitfalls

- **Wayland is not one platform.** GNOME bare has NO window API (install
  `window-calls` extension or enable unsafe_mode); wlroots variants lack
  geometry via foreign-toplevel; input needs ydotool/uinput or portals.
- Enable AT-SPI for GTK: `gsettings set org.gnome.desktop.interface
  toolkit-accessibility true`. The bridge sets `IsEnabled` at runtime, which
  covers most apps retroactively.
- Chromium/Electron need `--force-renderer-accessibility`; Qt may need
  `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`; Java needs java-atk-wrapper.
- Synthetic clicks move the real pointer; `act`/`set_text`/`set_value` don't.
- Tiling WMs: minimize/maximize are approximations (sway scratchpad/fullscreen).
- Cursor position is only readable on X11, KDE, and Hyprland.
- OCR: `tesseract-ocr` package recommended; `rapidocr` optional extra.
- polkit `auth_admin` prompts surface as `PERMISSION_REQUIRED` — the bridge
  never hangs waiting for a dialog.
