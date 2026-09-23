---
name: windows-mcp
description: Control a Windows desktop — UI automation via element refs (@eN), mouse/keyboard, screenshots, OCR text search, clipboard, apps, processes, registry, filesystem, PowerShell, and system administration (audio, display, services, tasks, env vars, devices, network, event logs, windows, developer mode). Use when the task involves operating Windows applications, the desktop, or system settings.
---

# Windows-MCP — desktop & system control

Two interfaces over the same engine:

1. **MCP tools** — when this server is configured in the client (see Setup).
2. **CLI** — `windows-mcp call <Tool> --arg 'k=v'` runs any tool without an MCP
   client; `windows-mcp tools` lists names. `--json` for machine-readable output.

## Core workflow: snapshot → ref → act

```
Snapshot                      → returns UI tree; every interactive element has an @eN ref
Click    --arg 'ref="@e5"'    → acts at action-time; ref survives window moves
Type     --arg 'ref="@e7"' --arg 'text="hi"' --arg 'clear=true'
Shortcut --arg 'shortcut="ctrl+s"'
```

- Refs (`@eN`) persist across snapshots; a stale ref returns `STALE_REF` — take a
  fresh Snapshot and retry.
- Prefer refs over coordinates: pattern-first execution (UIA Invoke/SetValue/
  Toggle) doesn't move the mouse or steal focus. `method='invoke'` forces
  pattern-only; `method='synthetic'` forces real input.
- `raw=True` on Type/Shortcut sends hardware scan codes (KEYEVENTF_SCANCODE) —
  use for apps that ignore virtual-key input.
- `FindText --arg 'text="保存"'` — OCR fallback for UIA-invisible UI
  (custom-drawn controls, canvases). Returns a synthetic `@eN` ref you can click.
- `WaitFor --arg 'condition="element_exists"' --arg 'text="Done"'` — poll inside
  the tool instead of repeated Snapshots.

## Tool map (33 tools)

| Need | Tools |
|---|---|
| See the screen | `Screenshot` (fast), `Snapshot` (UI tree + refs), `FindText` (OCR), `DisplayInventory` |
| Mouse/keyboard | `Click`, `Type`, `Scroll`, `Move` (drag=True), `Shortcut`, `MultiSelect`, `MultiEdit` |
| Timing | `Wait`, `WaitFor` |
| Apps/files/shell | `App`, `PowerShell`, `FileSystem`, `Registry`, `Process`, `Clipboard`, `Notification`, `Scrape` |
| Clipboard extras | `Clipboard mode=set_image/set_files` — pastes images/files into Explorer & dialogs |
| System | `System` (power/session), `Window` (focus/min/max/snap/topmost/close), `Display`, `Identity` |
| Hardware | `Audio` (volume/mute/devices/per-app), `Device` (PnP/printers), `Network` (adapters/ip/profiles/proxy) |
| Admin | `Service`, `Task` (scheduled), `Env` (env vars), `DevMode` (developer mode/features), `EventLog` |

## Safety gate

Destructive/elevated actions (shutdown, service stop, process kill, registry
write, device disable, file delete, dev-mode change) return
`CONFIRM_REQUIRED ... confirm='<token>'`. Re-call the same tool with
`--arg 'confirm="<token>"'` within 60 s to execute. Tokens are single-use and
bound to the exact action. Policy env var `WINDOWS_MCP_REQUIRE_CONFIRM`:
`dangerous` (default) | `all` | `off`. Every decision is appended to
`%LOCALAPPDATA%\windows-mcp\audit.log`.

When unsure whether an action is destructive, call it once — the gate answers.

## Setup

```powershell
uv tool install D:\Tool\Windows-MCP     # or: uv sync; uv run windows-mcp serve
```

MCP client config:

```json
{ "mcpServers": { "windows-mcp": { "command": "uvx", "args": ["windows-mcp"] } } }
```

CLI smoke test: `windows-mcp call Identity`

## Notes

- Elevation matters: a non-elevated server cannot drive admin windows —
  `Identity` reports elevation; run the server as Administrator for full reach.
- `Snapshot` on a busy desktop can be slow/large — pass `region=[x,y,w,h]` or
  `--arg 'use_ui_tree=false'` when you only need the screenshot.
- Structured errors carry codes: `STALE_REF`, `AMBIGUOUS_REF`,
  `ELEMENT_NOT_FOUND`, `ACCESS_DENIED`, `CONFIRM_REQUIRED`, `ENGINE_UNAVAILABLE`.
