# Testing — enhanced MacOS-MCP fork

## Test lanes

| Lane | Where | What runs | Command |
|------|-------|-----------|---------|
| **pure** | any OS (incl. Windows/Linux dev boxes) | refs, errors, safety, system parsers, views, config | `pytest` |
| **pyobjc** | macOS only | ax layer, tree traversal, desktop service, __main__ tools, permissions, spaces | `pytest` (same command — files unskip automatically) |
| **live** | macOS + granted TCC | real AX tree, Vision OCR, clipboard round-trips, launchd | manual checklist below |

`tests/conftest.py` probes `Quartz`/`ApplicationServices`/`Cocoa`; when they
are absent (non-macOS host), PyObjC-dependent test files are skipped at
collection via `collect_ignore`. **Pure-lane files are whitelisted** — a new
test file that only touches pure modules must be added to
`_PURE_PYTHON_TESTS` in conftest.py, or it will be silently skipped off-Mac.

Rules:

- Skips are environment-driven, not hidden: on a Mac every file collects.
- Pure modules (`errors`, `refs`, `safety`, `clipboard` text path, `ocr`
  imports, `system`) must never import PyObjC at module level — keep imports
  lazy inside functions so the pure lane stays green everywhere.
- Mock at the `_run`/`subprocess` boundary for system-domain tests; inject
  `probe`/`search` callables for ref-resolution tests (see `test_refs.py`,
  `test_system.py`).

## Live checklist (macOS host)

Run after `uv sync` on a real machine with a GUI session:

1. `macos-mcp doctor` — all PASS (frameworks, tools, both TCC grants).
2. `macos-mcp tools` — 18 tools listed.
3. `macos-mcp call Snapshot` — output shows `@wN` on window rows and
   `{"ref": "@eN"}` in element metadata.
4. `macos-mcp call Act --arg 'ref="@e1"' --arg 'action="AXPress"'` — semantic
   press without pointer movement (watch the cursor).
5. `macos-mcp call Click --arg 'ref="@e2"'` — AXPress path; a disabled element
   falls back to coordinates and reports which path it took.
6. `macos-mcp call FindText --arg 'text="File"'` — synthetic refs returned;
   `call Click --arg 'ref=<one of them>'` hits the text.
7. Clipboard round-trip: `call Clipboard --arg 'mode="set"' --arg 'text="hi"'`
   then `call Clipboard` returns `hi`; image/files round-trip in Finder.
8. `call Process --arg 'mode="kill"' --arg 'pid=<test pid>'` — first call
   returns `CONFIRM_REQUIRED` + token; replay with `confirmToken` succeeds;
   replaying the token a second time fails.
9. Stale-ref behavior: Snapshot → note an `@eN` → Snapshot again → acting on
   the old ref raises `STALE_REF`.
10. `System` domains: probe/identity/power_status/display/device/network/
    audio_get/env_list/log — each returns structured JSON.
11. Retina display: `FindText` boxes visually align with on-screen text
    (scale correction working).

## What is NOT covered

- Wayland/X11 concerns — macOS only.
- AXObserver-driven waits (future).
- Multi-user / concurrent GUI sessions.
- Mixed-DPI multi-display OCR box placement (documented edge case).
