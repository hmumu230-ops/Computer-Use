# Acceptance — enhanced Windows-MCP fork

Status legend: ✅ verified live · 🧪 unit-tested · ⬜ pending

## A. Ref model (@eN)

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| A1 | Snapshot renders `@eN` per interactive element | ✅ | notepad snapshot: 135 elements all ref'd |
| A2 | Ref survives move/resize (live-control probe) | ✅ | live resolve after window move |
| A3 | Re-resolution ladder: index_path → AutomationId → RuntimeId scan | ✅ | `refs/store.py` resolve chain |
| A4 | Dead element → `STALE_REF` structured error | ✅ | notepad kill → STALE_REF verified |
| A5 | Legacy numeric labels still work | 🧪 | label path preserved, tests pass |
| A6 | Concurrent calls don't corrupt ref store | 🧪 | store is generation-scoped; lock on rebuild |

## B. Ref-driven actions + observation

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| B1 | Click/Type/Scroll/Move/MultiSelect/MultiEdit accept `ref=` | ✅ | tools/input.py, tools/multi.py |
| B2 | Pattern-first: Invoke/Toggle/Select/ExpandCollapse/Value — no mouse move | ✅ | notepad: Invoke click & setvalue verified, cursor unmoved |
| B3 | Synthetic fallback, `method=auto\|invoke\|synthetic` | ✅ | Click/Type honor method; invoke-only errors clearly |
| B4 | Actions report observed state change | ✅ | `actions.observe/diff` → `observed:` in response |
| B5 | `fill_form` bulk via MultiEdit `refs=` | 🧪 | per-field results, mocked tests |
| B6 | Ambiguous ref → `AMBIGUOUS_REF` + candidates | ✅ | Window 'Notepad' ambiguity error verified |

## C. OCR layer

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| C1 | `FindText` locates text in UIA-blind regions | ✅ | notepad region OCR → found 'ExampleDomain' |
| C2 | OCR hit → synthetic `@eN` ref, clickable | ✅ | engine registers synthetic locators |
| C3 | Region-limited OCR | ✅ | `region=` param honored |
| C4 | Missing engine → `ENGINE_UNAVAILABLE` | 🧪 | engine_available() gate |

## D. System toolkit (live-verified on this host)

| Tool | Actions | Status |
|------|---------|--------|
| Identity | user/elevation/groups | ✅ `elevated:false` correct |
| System | lock/sleep/hibernate/shutdown/restart/logoff/cancel/uptime | ✅ uptime live; gated ops blocked correctly |
| Window | list/info/minimize/maximize/restore/move/resize/snap/topmost/focus/close/virtual-desktop | ✅ list+focus live (AttachThreadInput fix) |
| EventLog | query Application/System/… | ✅ live query returned events |
| Audio | get/set/mute/unmute/devices/sessions/set_session | ✅ get → `{volume:0,muted:true}` via pycaw |
| Display | brightness/modes/night-light/inventory | ✅ (modes/brightness live) |
| Device | list/enable/disable + printers | ✅ list live |
| Network | adapters/ip/profiles/proxy/wifi | ✅ ip+proxy live |
| Service | list/get/start/stop/restart/startup-type | ✅ list live; stop gated |
| Task | list/info/run/enable/disable | ✅ list live |
| Env | get/set/list/delete (user+machine, WM_SETTINGCHANGE broadcast) | ✅ user-scope set/get/delete roundtrip |
| DevMode | developer_mode/features/explorer_prefs | ✅ live reads |

## E. Safety gate

| # | Criterion | Status |
|---|-----------|--------|
| E1 | Dangerous ops → `CONFIRM_REQUIRED` + single-use token | ✅ live: shutdown/Service stop blocked |
| E2 | Token bound to exact action, 60 s TTL | 🧪 test_safety.py (9 tests) |
| E3 | Policy `WINDOWS_MCP_REQUIRE_CONFIRM` = dangerous/all/off | 🧪 |
| E4 | Audit log `%LOCALAPPDATA%\windows-mcp\audit.log` | 🧪 JSONL append verified |

## F. Input fidelity + clipboard

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| F1 | `raw=True` scan-code input (Shortcut/Type) | ✅ | notepad title `*RawTest42` proves delivery |
| F2 | Clipboard get: text/image/files + format report | ✅ all three live-verified |
| F3 | Clipboard set_image → Ctrl+V-able | ✅ CF_DIB verified |
| F4 | Clipboard set_files → Explorer paste | ✅ CF_HDROP verified |

## G. Interfaces

| # | Criterion | Status |
|---|-----------|--------|
| G1 | `windows-mcp tools` lists all tools | ✅ 33 tools |
| G2 | `windows-mcp call <Tool> --arg k=v [--json]` | ✅ Identity/Window called live |
| G3 | `SKILL.md` agent doc | ✅ repo root |
| G4 | Devin MCP config | ✅ `%APPDATA%\devin\mcp_config.json` (uv --directory run --python 3.14.3) |

## Regression

| Suite | Result |
|-------|--------|
| `pytest` full | ✅ 661 passed (upstream baseline 606 + 55 new) |
| `ruff check` new code | ✅ clean (pre-existing upstream debt untouched) |

## Known limitations / follow-ups

- `.python-version` pins `3.14.7` but host has `3.14.3` — MCP config passes `--python 3.14.3` explicitly.
- Notepad's editor is `DocumentControl` (Win11 RichEdit) — works via ValuePattern, but the tree may not tag it as interactive in all snapshots.
- E2E scenarios E2E-1..8 from the plan are implemented as live-verified fragments; a scripted `tests/e2e/` suite is future work.
- `_type_scancode` depends on active keyboard layout for char→VK mapping; unmappable chars fall back to Unicode injection.
