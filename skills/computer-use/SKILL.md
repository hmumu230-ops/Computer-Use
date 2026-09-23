---
name: computer-use
description: macOS desktop control — inspect, click, type via the Accessibility API with @eN/@wN refs, Vision OCR fallback, clipboard payloads, notifications, and system administration (launchd/pmset/networksetup/log).
---

# computer-use (macOS)

## Quick Start

```
Snapshot                                # windows (@wN) + elements (@eN) + generation
Click {ref:"@e3"}                       # semantic AXPress first, coords fallback
Type {ref:"@e7", text:"hello"}          # AXValue when settable, else focus+type
Act {ref:"@e4", action:"AXShowMenu"}    # ref-only semantic action
FindText {text:"Save"}                  # Vision OCR → clickable synthetic refs
```

## Tools

| name | use |
|---|---|
| Snapshot | focused window, app list (@wN), interactive+scrollable elements (@eN), optional annotated screenshot |
| Click | `ref` (semantic first) or `loc=[x,y]`; button left/right/middle; clicks 0/1/2 |
| Type | `ref` (AXFocused+AXValue) or `loc`; clear/caret_position/press_enter |
| Act | ref-only AX action (AXPress/AXShowMenu/AXIncrement/AXConfirm); error lists advertised actions |
| FindElements | live AX search by role/name substring/pid → fresh @eN refs |
| WaitFor | poll until ref re-resolves or role+name match appears |
| Scroll | at `ref` centre / `loc` / cursor; vertical/horizontal; wheel_times |
| Move | cursor to `ref` centre or `loc`; `drag=true` for drag-and-drop |
| Shortcut | key chords: `command+c`, `control+tab`, … |
| Wait | fixed sleep |
| FindText | Vision OCR over the screen → synthetic @eN refs (Retina-corrected) |
| Clipboard | get/set `text` | `image` (base64 PNG) | `files` |
| App | launch/switch/resize/move applications |
| Shell | bash/zsh or osascript (confirm-gated under MACOS_MCP_REQUIRE_CONFIRM) |
| System | domains: probe, identity, power_status, display, device, network, audio_get, env_list, log — writes: audio_set/mute, env_set, power, wifi (gated) |
| Process | list (name filter, cpu/mem) / kill by pid+signal (gated) |
| Service | launchctl list / kickstart|enable|disable|bootout in gui domain (gated) |
| Desktop | Mission Control Space creation (verified) |
| Notification | banner with title/subtitle/sound |
| Scrape | webpage → Markdown |

## Conventions

- **Snapshot first.** Every capture mints `@eN`/`@wN` refs in a new
  generation; acting on a previous generation's ref → `STALE_REF`.
  Re-snapshot, don't retry.
- **Semantic before synthetic.** `ref` inputs try AX verbs/attributes
  (no pointer steal, works on unfocused elements); `loc` inputs drive
  the real cursor.
- **`Act` is ref-only** — no coordinates accepted. If the element
  doesn't advertise the action, the error lists what it does advertise.
- **Gated ops return `CONFIRM_REQUIRED` + token.** Re-call with
  `confirmToken` to execute. Single-use, action-bound, 120 s TTL.
- All errors are structured `{code, message, hint, retryable}` — branch
  on `code`.
- Direct CLI: `macos-mcp tools`, `macos-mcp call <Tool> --arg k=v`,
  `macos-mcp doctor`.

## Pitfalls

- **Permissions belong to the interpreter** (the python running this
  server), not the MCP host. Grant via the native consent dialog or
  System Settings > Privacy & Security > Accessibility + Screen
  Recording. `macos-mcp doctor` reports both.
- Accessibility coverage gaps: some Electron/Java/self-drawn UIs expose
  little or nothing — use `FindText` (Vision OCR) as fallback; hits are
  coordinate refs.
- `@wN` re-resolution matches by pid+window title — a renamed window
  goes stale until the next Snapshot.
- OCR coordinates are logical points (Retina-corrected); on mixed-DPI
  multi-display setups boxes can be slightly off — verify visually.
- `Service control` only reaches the `gui/<uid>` domain; system-domain
  services need root and aren't attempted.
- `Clipboard image/files` paths need AppKit — they raise a structured
  error in headless contexts.
- Menu-bar extras and dialogs are scanned deliberately; a modal dialog
  suppresses the blocked window's nodes (they'd be unclickable anyway).
