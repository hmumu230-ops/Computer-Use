# Fork & upstream-sync strategy

This repo is a fork of `CursorTouch/Windows-MCP` (MIT). Enhancements live on
branch `enhanced`; `main` tracks upstream.

## Layout discipline

New capability lands in **new files/packages** wherever possible so upstream
merges stay clean:

- `src/windows_mcp/refs/` — `@eN` locator model (new package)
- `src/windows_mcp/ocr/` — RapidOCR engine (new package)
- `src/windows_mcp/clipboard/` — image/file clipboard payloads (new package)
- `src/windows_mcp/system/` — admin domain modules (new package)
- `src/windows_mcp/safety.py` — confirm-token gate (new file)
- `src/windows_mcp/tools/{system,hardware,admin,ocr}.py` — tool registrations

Touched upstream files (merge surface — keep diffs small & local):

- `tree/views.py`, `tree/service.py` — `locator` field + `[@eN]` rendering
- `desktop/service.py` — ref store init, `raw` input paths, clipboard paste
- `tools/input.py`, `tools/multi.py`, `tools/clipboard.py` — ref/raw params
- `tools/__init__.py` — module list
- `uia/core.py` — public `VKtoSC`/`SendScanCode` wrappers
- `__main__.py` — `call`/`tools` subcommands (appended at file end)
- `tests/test_stdio_handshake.py` — EXPECTED_TOOLS set
- `pyproject.toml` — `pycaw` dependency

## Sync procedure

`origin` currently points directly at `CursorTouch/Windows-MCP` (read-only for
us — no personal fork remote exists yet). If a push-capable fork is added later,
rename: `git remote rename origin upstream && git remote add origin <fork>`.

```powershell
git fetch origin              # upstream = CursorTouch/Windows-MCP
git checkout enhanced
git merge origin/main         # conflicts should stay confined to the
                              # touched-files list above
uv run pytest -x -q           # upstream suite must stay green
uv run pytest tests/test_stdio_handshake.py -q   # tool set may legitimately change
```

When upstream adds a tool, add it to `EXPECTED_TOOLS` in the handshake test.
When upstream changes tool signatures, keep `ref=`/`method=`/`raw=` kwargs
additive — never remove an upstream parameter.

## Divergence policy

- Keep the `windows-mcp` package name and tool names stable (drop-in
  replacement for upstream installs).
- New behavior is opt-in via parameters (`ref`, `method`, `raw`) or new tools —
  default behavior matches upstream.
- If a fix belongs upstream (e.g. the `bring_to_front` detach-in-finally
  hardening), it can be offered back as a standalone PR from `main`+cherry-pick.
