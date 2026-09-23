# Acceptance — enhanced linux-computer-use fork

Status legend: ✅ verified live · 🖥️ verified in CI (Xvfb/headless compositor) · 🧪 unit-tested · ⬜ pending

Platform legend: `[X11]` X11/EWMH · `[WL]` Wayland (any compositor) · `[GNOME]`/`[KDE]`/`[wlroots]` compositor-specific · `[all]` session-independent

## A. Bridge protocol

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| A1 | NDJSON stdio protocol, one JSON object per line | ⬜ | inherited from base |
| A2 | Handshake: `hello` → `{version, capabilities, session}` | ⬜ | |
| A3 | Per-command schema validation → `INVALID_ARGS` | ⬜ | |
| A4 | Unknown command → `UNKNOWN_COMMAND` | ⬜ | |
| A5 | Bridge crash/exit → MCP tool returns structured error, not hang | ⬜ | |
| A6 | Bridge spawned on system python (`/usr/bin/python3`) so `gi`/AT-SPI works | ⬜ | |

## B. Environment detection & introspection

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| B1 | `doctor` reports init, session_type, DE/compositor, audio server, display backend, groups, polkit preflight | ⬜ | |
| B2 | `capabilities` tool → per-domain support matrix with `supported/unsupported/degraded` + `hint` | ⬜ | |
| B3 | Missing `DISPLAY`/`WAYLAND_DISPLAY`/`DBUS_SESSION_BUS_ADDRESS`/`XDG_RUNTIME_DIR` recovered from `systemctl --user show-environment` | ⬜ | |
| B4 | Compositor detection order: env sockets (SWAYSOCK/HYPRLAND/NIRI/WAYFIRE) → XDG_CURRENT_DESKTOP → D-Bus names → process scan | ⬜ | |
| B5 | GNOME-Wayland bare (no window-calls ext, no unsafe_mode) → honest degradation, not silent empty results | ⬜ | |
| B6 | `NO_AT_BRIDGE=1` / missing at-spi2-registryd → detected with remediation hint | ⬜ | |
| B7 | Runtime `IsEnabled=true` on `org.a11y.Status` at bridge init (never `ScreenReaderEnabled`) | ⬜ | |

## C. Ref model (@wN windows, @eN elements)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| C1 | Snapshot emits `@eN` per interactive element, `@wN` per window | ⬜ | base has this |
| C2 | Element locator = `(bus_name\|pid, index_path)` + durable fingerprint `(role, name, nth)` | ⬜ | |
| C3 | Re-resolution: live probe → index path → fingerprint match → `STALE_REF` | ⬜ | |
| C4 | `DEFUNCT` state or `UnknownObject` D-Bus error → ref marked stale | ⬜ | |
| C5 | Refs scoped to snapshot generation; action on wrong-generation ref → `STALE_REF` | ⬜ | base resets blindly — must become explicit error |
| C6 | GTK4 ListView virtualization: re-resolution validates role/name after scroll (index drift) | ⬜ | |
| C7 | MANAGES_DESCENDANTS nodes not enumerated blindly | ⬜ | |

## D. Semantic actions (pattern-first)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| D1 | `act_on_element(ref, verb)` — ref-only, no coordinate args (poka-yoke) | ⬜ | |
| D2 | Verb→action-name normalization across toolkits: GTK `click/press`, Qt `Press/Toggle/Show Menu`, Chromium `doDefault`, Firefox `jump/press` — matched case/underscore-insensitive | ⬜ | |
| D3 | `press` fallback order: semantic verb → index-0 default action → `scroll_to(ANYWHERE)`+`grab_focus` → coordinate click | ⬜ | |
| D4 | GTK MenuButton (NActions=0 on push button) → BFS ≤3 into descendants for `click` | ⬜ | |
| D5 | `set_text`: `STATE_EDITABLE` check → `set_text_contents` → readback verify → focus+select-all fallback | ⬜ | base has set_text |
| D6 | `set_value` via Value iface (write→re-read verify) | ⬜ | |
| D7 | `select`/`expand`/`collapse`/`showmenu`/`focus` verbs | ⬜ | |
| D8 | Action returns structured receipt: `{verb, method, observed_diff}` — not always a screenshot | ⬜ | |
| D9 | `do_action` returns False (insensitive widget) → reported, not swallowed | ⬜ | |

## E. Find & wait

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| E1 | `find_elements(role?, name~, state?)` via Collection `get_matches` (server-side, single D-Bus roundtrip) | ⬜ | |
| E2 | `wait_for_element` via EventListener + queue (object:state-changed/children-changed/window:*) — event-driven, not tree polling | ⬜ | |
| E3 | `wait_for_text` | ⬜ | |
| E4 | Timeout → structured `TIMEOUT` with last-observed state | ⬜ | |

## F. Input injection

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| F1 | [X11] xdotool: click/move/type/key/scroll — existing path preserved | ⬜ | base has this |
| F2 | [X11] `keypress` accepts named keys + keycodes; AT-SPI `generate_keyboard_event` as in-process alternative | ⬜ | |
| F3 | [WL] Input router: GNOME→portal RemoteDesktop (persist_mode=2 + restore_token) · KDE→KWin EIS (detect Debian/Ubuntu no-EIS builds, degrade) · wlroots→virtual-keyboard/virtual-pointer · any→uinput(evdev) | ⬜ | |
| F4 | uinput path: device settle wait (~0.7s) after UINPUT_DEV_CREATE; keysym→keycode layout translation | ⬜ | |
| F5 | Wayland-native windows receive synthetic input (xdotool only reaches XWayland — must not silently no-op) | ⬜ | |
| F6 | Drag-and-drop: X11 small-step gesture; Wayland → real-input gesture or clipboard+Ctrl+V fallback, documented as degraded | ⬜ | |

## G. Screenshots

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| G1 | [X11] scrot/mss — existing path preserved | ⬜ | base has scrot |
| G2 | [WL] portal `Screenshot(interactive:false)`; first-run Access dialog persists grant; `PermissionStore.SetPermission` preseed documented in `setup` | ⬜ | |
| G3 | [wlroots] grim primary (`-g` region, `-o` output) | ⬜ | |
| G4 | [KDE] `spectacle -b -n -o` fallback; ScreenShot2 only behind helper-binary/env opt-in | ⬜ | |
| G5 | Window screenshot = fullscreen + crop by geometry (AT-SPI extents → compositor IPC → XWayland wmctrl) | ⬜ | |
| G6 | HiDPI: physical-px image vs logical coords — scale detected (DisplayConfig/kscreen/hyprctl or image/logical ratio) and applied before crop | ⬜ | |
| G7 | Region/format/max-dimension controls for token efficiency | ⬜ | |
| G8 | GNOME `org.gnome.Shell.Screenshot` never used (locked since GNOME 41) | ⬜ | design constraint |

## H. Window management

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| H1 | [X11] wmctrl/xdotool: list(+geometry+pid), focus, move/resize, min/max/restore, close, above, desktop switch/move | ⬜ | base has list+focus only |
| H2 | [KDE] kdotool or KWin-script injection backend | ⬜ | |
| H3 | [sway] swaymsg get_tree + criteria commands | ⬜ | |
| H4 | [Hyprland] hyprctl clients -j + dispatch | ⬜ | |
| H5 | [GNOME+ext] window-calls D-Bus backend (List/Activate/Move/Resize/Min/Max/Close) | ⬜ | |
| H6 | [generic wlroots] wlr-foreign-toplevel via lswt/wlrctl: list/focus/min/max/fullscreen/close — `geometry: null` reported honestly | ⬜ | |
| H7 | `@wN` maps to per-backend native handle (KWin internalId string, GNOME u32, sway con_id, Hyprland address) — never exposed raw | ⬜ | |
| H8 | Tiling-WM semantics documented: sway scratchpad= minimize, niri maximize-column ≈ maximize | ⬜ | |
| H9 | Cursor position: [X11]/[KDE]/[Hyprland] readable; elsewhere field present with `unsupported` | ⬜ | |

## I. Clipboard & notification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| I1 | [X11] xclip: text/image/file list; owner-serves constraint handled (bridge stays alive or xclip forks) | ⬜ | |
| I2 | [WL] wl-copy/wl-paste equivalents; GNOME focus-flash workaround documented | ⬜ | |
| I3 | `clipboard_get` reports available targets/formats | ⬜ | |
| I4 | `clipboard_set_image` (png target) → Ctrl+V-able in GTK/Qt apps | ⬜ | |
| I5 | `clipboard_set_files` → file-manager paste (text/uri-list; KDE cut-copy dual target) | ⬜ | |
| I6 | `notification` via notify-send → D-Bus `org.freedesktop.Notifications`; DND detection per DE | ⬜ | |

## J. OCR layer

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| J1 | Tier0: AT-SPI tree text search with `get_range_extents` sub-string rects — zero deps | ⬜ | |
| J2 | Tier1: `tesseract tsv` CLI (system package, not pip) | ⬜ | |
| J3 | Tier2: `rapidocr` optional import — absence → `ENGINE_UNAVAILABLE` | ⬜ | |
| J4 | OCR hit → synthetic `@eN` ref, actionable via act_on_element/click | ⬜ | |
| J5 | `find_text` honors `region=` | ⬜ | |

## K. System toolkit

| Tool | Actions | Status |
|------|---------|--------|
| Identity | user/groups/sudo -n/pkcheck matrix/session | ⬜ |
| System | uptime/virt detection/lock/inhibit | ⬜ |
| Service | list/get/start/stop/restart/enable (systemctl; user units; non-systemd fallback: sysvinit/openrc/runit) | ⬜ |
| Task | systemd-run transient timers, crontab list/add (with `\%` escaping), at | ⬜ |
| Audio | wpctl→pactl→amixer chain; default sink/source, per-app streams | ⬜ |
| Network | nmcli terse-parse (`\:` escaping), ip -j, rfkill, resolvectl | ⬜ |
| Display | brightnessctl, ddcutil, xrandr/kscreen-doctor/gdctl/wlr-randr/hyprctl per compositor, night-light (gsettings/kwinrc+reconfigure) | ⬜ |
| Power | loginctl suspend/poweroff/etc via systemctl, CanSuspend preflight, inhibit | ⬜ |
| EventLog | journalctl -o json NDJSON (MESSAGE may be byte-array), -u/-p/-b/--since, permission-aware | ⬜ |
| Device | lsblk/findmnt/lscpu/lsusb/lspci/udevadm, CUPS lpstat/lpadmin | ⬜ |
| Process | psutil/ps, kill, pgrep | ⬜ |
| Env | environment.d, ~/.profile, gsettings proxy, `systemctl --user set-environment` | ⬜ |

Each write action declares `required: none|uaccess|group:X|polkit:action|cap|root` and preflights via `pkcheck`/`sudo -n` — never hangs on an interactive auth dialog.

## L. Safety gate

| # | Criterion | Status |
|---|-----------|--------|
| L1 | Dangerous ops (poweroff/service stop/kill/crontab -r/…) → `CONFIRM_REQUIRED` + single-use token | ⬜ |
| L2 | Token bound to exact action+args, 60s TTL | ⬜ |
| L3 | Policy env `LINUX_MCP_REQUIRE_CONFIRM` = dangerous/all/off | ⬜ |
| L4 | Audit log JSONL | ⬜ |
| L5 | polkit `auth_admin` prompts surfaced as `PERMISSION_REQUIRED`, never block | ⬜ |

## M. Interfaces

| # | Criterion | Status |
|---|-----------|--------|
| M1 | MCP stdio via FastMCP wrapper | ⬜ |
| M2 | `linux-computer-use-mcp call <tool> <json>` CLI — same envelope as MCP | ⬜ |
| M3 | `tools` lists registered tools | ⬜ |
| M4 | `doctor` standalone runnable | ⬜ |
| M5 | `setup` prints distro-correct package list (apt/dnf/pacman/zypper), udev rule, group adds | ⬜ |
| M6 | SKILL.md updated for agents | ⬜ |
| M7 | Tool annotations: `readOnlyHint`, `destructiveHint` | ⬜ |

## N. Error model

| # | Criterion | Status |
|---|-----------|--------|
| N1 | All errors structured: `{code, message, hint, retryable, permission?}` | ⬜ |
| N2 | Codes: `STALE_REF`, `AMBIGUOUS_REF`, `TIMEOUT`, `UNSUPPORTED_PLATFORM`, `UNSUPPORTED_COMPOSITOR`, `PERMISSION_REQUIRED`, `CONFIRM_REQUIRED`, `ENGINE_UNAVAILABLE`, `INVALID_ARGS`, `UNKNOWN_COMMAND`, `BRIDGE_DEAD` | ⬜ |
| N3 | Unsupported capability returns `UNSUPPORTED_*`+hint — never silent empty/false success | ⬜ |

## Regression

| Suite | Result |
|-------|--------|
| `pytest` unit | ⬜ |
| `pytest -m xvfb` (Xvfb+openbox+AT-SPI) | ⬜ |
| `pytest -m wayland` (mutter/kwin headless, optional) | ⬜ |
| `ruff check` | ⬜ |

## Known limitations (by design, must surface as structured errors)

- GNOME Wayland bare: no window list/move/focus (requires window-calls ext or unsafe_mode)
- Wayland has no global coordinate namespace; cursor position compositor-dependent
- Wayland synthetic drag-and-drop not possible at protocol level
- AT-SPI coverage gaps: Chromium/Electron need IsEnabled/`--force-renderer-accessibility`, Qt needs toolkit a11y on, Java needs java-atk-wrapper, Wine/canvas apps have no tree → OCR fallback
- Tiling WMs: minimize/maximize are approximations
- headless/SSH: all GUI domains degrade to `unsupported`
- Old systemd (<250): no `systemctl -o json` — text-parse path required
