# Acceptance — enhanced MacOS-MCP fork

Status legend: ✅ verified live on macOS · 🧪 unit-tested (pure-Python lane) · ⬜ pending

macOS-only tool — there is no compositor matrix; the variable axes are
**macOS version**, **TCC grants**, **toolkit coverage** (AppKit / Electron /
Java / web), and **Retina scale**.

## A. Permissions & environment

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| A1 | `doctor` reports Python, framework modules (ApplicationServices/Cocoa/Quartz/Vision/objc), CLI tools, TCC grants | 🧪 | doctor command |
| A2 | Missing Accessibility → startup fails with the *which-process* guidance (grant belongs to the interpreter, not the MCP host); `MACOS_MCP_SKIP_PERMISSION_CHECK=1` downgrades to warning | ⬜ | permissions.py |
| A3 | `AXIsProcessTrustedWithOptions` prompt path used so the running process self-registers in the consent dialog | ⬜ | |
| A4 | Screen Recording checked via System Events probe; screenshot failure reported honestly in Snapshot output (not silent omission) | ⬜ | |
| A5 | SSH/headless session → GUI domains degrade to structured errors, not hangs | ⬜ | |

## B. Ref model (@wN windows, @eN elements)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| B1 | Snapshot emits `@eN` per interactive/scrollable element, `@wN` per window — visible in metadata / window list | 🧪 | refs.py + emit points |
| B2 | Element locator = `(pid, role, name, nth)` + live element handle; nth = ordinal among same-(role,name) | 🧪 | |
| B3 | Resolution ladder: live probe (`AXUIElementGetPid`) → runtime re-search inside owning app → `STALE_REF` | 🧪 | resolve ladder unit-tested |
| B4 | Refs scoped to capture generation: `Desktop.get_state` mints generation BEFORE window capture, so `@wN` stays valid through the tree pass | 🧪 | |
| B5 | Action on wrong-generation or unknown ref → `STALE_REF` with "take a fresh Snapshot" hint | 🧪 | |
| B6 | Ref registration serial (post-pool), no races with window-scan threads | 🧪 | design |
| B7 | Word-level nodes and OCR hits mint *synthetic* refs (bbox-only) resolvable to coordinates | 🧪 | |

## C. Semantic actions (pattern-first)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| C1 | `Act(ref, action)` — ref-only, no coordinate args (poka-yoke); error lists the element's advertised actions | 🧪 | act() |
| C2 | `Click ref` prefers `AXPress` (left single) / `AXShowMenu` (right), falls back to coordinates | ⬜ | live path needs macOS |
| C3 | `Type ref` sets `AXFocused` then `AXValue` when settable; else focus-click + synthetic typing | ⬜ | |
| C4 | `set_value_ref` checks `AXValue` settability before writing | ⬜ | |
| C5 | AX action names queried lazily at action time — never in the per-node traversal batch (IPC cost) | 🧪 | design constraint |
| C6 | Synthetic fallback path unchanged: MoveTo/Click/RightClick/MiddleClick/DoubleClick, HotKey, TypeText, KeyPress, Wheel, DragTo | ⬜ | upstream behavior |

## D. Find & wait

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| D1 | `FindElements(role?, name~, pid?)` — live AX search, hits mint fresh `@eN` refs | 🧪 | signature/logic |
| D2 | `WaitFor(ref | role+name, timeout)` — polls resolution until deadline, returns resolved ref | 🧪 | |
| D3 | Unregistered ref → fast `STALE_REF` (not a spurious element match); dead-but-registered ref keeps polling | 🧪 | fixed in review |
| D4 | Timeout → structured error with remediation hint | 🧪 | |
| D5 | WatchDog focus events keep tree fresh (upstream behavior preserved) | ⬜ | live only |

## E. Capture

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| E1 | Screenshot: ImageGrab → `screencapture` fallback; transient failure (display sleep/Space switch) reported, not a partial-success lie | ⬜ | upstream + note in Snapshot |
| E2 | Annotated screenshot maps logical→pixel per display (per-display scale, accumulated pixel origins) | ⬜ | upstream |
| E3 | `use_vision` Snapshot attaches PNG ≤1080p token bound | ⬜ | |
| E4 | Retina: OCR boxes divided by capture scale → refs land in logical screen space | 🧪 | find_text |

## F. Window management

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| F1 | `get_windows` lists Regular apps + any app's floating dialog (accessory apps included only while a dialog is up) | ⬜ | upstream |
| F2 | `@wN` re-resolution: pid + title match inside app's window list → `STALE_REF` when renamed/closed | 🧪 | resolve_window |
| F3 | App launch/switch/resize/move modes preserved | ⬜ | upstream |
| F4 | Mission Control Space creation verified by space count delta | ⬜ | upstream |

## G. Clipboard & notification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| G1 | `Clipboard get/set text` via pbcopy/pbpaste — no PyObjC needed | 🧪 | text path |
| G2 | `get image` returns PNG (TIFF converted via CGImageDestination); `set image` writes NSPasteboardTypePNG | ⬜ | live only |
| G3 | `get/set files` via NSURL file payloads — paste works in Finder | ⬜ | live only |
| G4 | `Notification` banner via osascript, title/subtitle/sound | ⬜ | upstream |

## H. OCR (Vision)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| H1 | `FindText(text)` — native `VNRecognizeTextRequest` (accurate, language correction), zero external engine | ⬜ | live only |
| H2 | Normalized bottom-left boxes re-based to pixel top-left | 🧪 | recognize() |
| H3 | Missing `pyobjc-framework-Vision` → `ENGINE_UNAVAILABLE` with install hint | 🧪 | lazy import |
| H4 | Every hit → synthetic `@eN` (Click/Move compatible) | 🧪 | |
| H5 | `case_sensitive` flag honored | 🧪 | |

## I. System toolkit

| Tool | Actions | Status |
|------|---------|--------|
| System:probe | sw_vers/arch/SIP/session/tool matrix | 🧪 |
| System:identity | user/groups/hostname/uptime | 🧪 |
| Process | list (name filter, cpu/mem) / kill (TERM/KILL/HUP/INT) — kill gated | 🧪 |
| Service | launchctl list (filter) / kickstart/enable/disable/bootout in gui domain — mutations gated | 🧪 |
| System:audio_get/audio_set/audio_mute | osascript volume settings | 🧪 |
| System:network | hardware ports, airport network, proxy, IP; wifi on/off gated | 🧪 |
| System:display | SPDisplaysDataType -json (name/resolution/main) | 🧪 |
| System:device | SPHardware/USB/Bluetooth/Storage -json | 🧪 |
| System:power_status/power | pmset batt+assertions; sleep/caffeinate — gated | 🧪 |
| System:env_list/env_set | launchctl print/getenv/setenv (GUI session scope) | 🧪 |
| System:log | `log show --last --predicate` bounded output | 🧪 |

## J. Safety gate

| # | Criterion | Status |
|---|-----------|--------|
| J1 | Dangerous ops (kill/bootout/sleep/wifi-off/env_set) → `CONFIRM_REQUIRED` + single-use token | 🧪 |
| J2 | Token bound to action+params digest, 120s TTL; wrong action does not burn it | 🧪 |
| J3 | `MACOS_MCP_REQUIRE_CONFIRM`: `1`/all or comma-prefix list; unset → only `dangerous` ops gated | 🧪 |

## K. Interfaces

| # | Criterion | Status |
|---|-----------|--------|
| K1 | MCP stdio/SSE/streamable-HTTP transports preserved | ⬜ |
| K2 | `macos-mcp tools` lists registered tools | 🧪 |
| K3 | `macos-mcp call <Tool> --arg k=v` direct invocation; image payloads saved to disk | 🧪 |
| K4 | `macos-mcp doctor` standalone runnable | 🧪 |
| K5 | `install`/`uninstall` launchd agent lifecycle preserved | ⬜ |
| K6 | Tool annotations: `readOnlyHint`, `destructiveHint` | 🧪 |

## L. Error model

| # | Criterion | Status |
|---|-----------|--------|
| L1 | All errors structured `{code, message, hint, retryable}` | 🧪 |
| L2 | Codes: `STALE_REF`, `CONFIRM_REQUIRED`, `PERMISSION_REQUIRED`, `UNSUPPORTED`, `ENGINE_UNAVAILABLE`, `INVALID_ARGS`, `TOOL_NOT_FOUND` | 🧪 |
| L3 | Missing capability → structured error + remediation hint, never silent empty/false success | 🧪 |

## Regression

| Suite | Result |
|-------|--------|
| `pytest` (pure-Python lane: refs/errors/safety/system/views/config) | 🧪 94 passed |
| `pytest` (full suite incl. PyObjC lanes — macOS only) | ⬜ |
| `py_compile` all touched modules | 🧪 |

## Known limitations (by design — must surface as structured errors or hints)

- TCC grants belong to the *running interpreter*; uv-managed binaries can't be
  added by hand in System Settings — consent dialog path is the fix (A2/A3).
- `WaitFor` is poll-based; AXObserver event-driven waits are a future upgrade.
- Accessibility coverage gaps: Electron needs `--force-accessibility-flag`
  parity apps may need `AXEnhancedUserInterface`; canvas/self-drawn UI has no
  tree → `FindText` (Vision OCR) is the fallback.
- `get/set image` and `get/set files` require AppKit — unavailable in
  pure-console contexts → `CuError` with hint.
- OCR on multi-display captures: boxes are divided by the *global* scale —
  mixed-DPI display sets can misplace refs by sub-100px (edge case).
- `Service control` targets the `gui` domain by default; `system` domain needs
  root and is not attempted automatically.
