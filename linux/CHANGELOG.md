# Changelog

All notable changes to **linux-computer-use** are documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-05-03

### Added

- **MCP server** (`mcp_server/server.py`) — same 8 tools exposed over the Model Context Protocol via FastMCP. Works with Claude Code, OpenCode, and any MCP-aware host.
- **`pyproject.toml`** — `uvx --from git+https://github.com/tak-uukti/linux-computer-use linux-computer-use-mcp` works out of the box.
- README rewritten with three install sections (Pi / Claude Code / OpenCode).

### Changed

- Repo and npm package renamed `pi-computer-use-linux` → `linux-computer-use`. The Pi helper directory is now `~/.pi/agent/helpers/linux-computer-use/bridge`.
- npm package: `@tak1tak/pi-computer-use-linux` → `@tak1tak/linux-computer-use`, version bumped to 0.2.0.

## [0.1.1] — 2026-05-03

### Fixed

- **AT-SPI element bounds collapsing to (0, 0).** GTK4 and Xwayland frequently report `CoordType.SCREEN` extents as `0,0,W,H`. The walker now falls back to `CoordType.WINDOW` extents plus the focused window's screen offset, so `@eN` clicks land on the correct pixel.
- **`canPress: false` on push buttons.** `Atspi.Action.get_name(k)` is deprecated and returns `null` on modern AT-SPI; switched to `Atspi.Action.get_action_name(ai, k)` which yields `"click"` / `"press"` / `"activate"`.
- **`postinstall` python resolution.** The bridge wrapper now prefers `/usr/bin/python3` over `python3` so PyGObject (`gi`) is found even when the active venv lacks system bindings.

### Verified

End-to-end on `Xvfb :99` + openbox + dbus + at-spi-bus:

- gnome-calculator — `keypress 7+8 Return` → display `15`
- gnome-calculator — `computer_actions [click @e3, click @e7]` → display `45`
- gedit — `type_text` 169-char string, then `ctrl+a` / `Delete` / `type_text "Taksheel"`

## [0.1.0] — 2026-05-03

### Added

- Initial Linux/X11 port of [`@injaneity/pi-computer-use`](https://github.com/injaneity/pi-computer-use).
- 8 slim tools (`list_windows`, `screenshot`, `click`, `type_text`, `set_text`, `keypress`, `scroll`, `computer_actions`) registered as a Pi extension.
- Python 3 bridge (`bridge/bridge.py`) using AT-SPI 2 (`gi.repository.Atspi`) + `xdotool` + `wmctrl` + `scrot`, speaking newline-delimited JSON over stdio.
- TypeScript ESM extension layer with local stubs for the `@mariozechner/pi-coding-agent` extension API so typecheck runs without the peer dependency installed.
- `scripts/setup-helper.mjs` postinstall — writes a bash wrapper to `~/.pi/agent/helpers/linux-computer-use/bridge`. No native build, no codesign.
- Pi skill at `skills/computer-use/SKILL.md` (≤80 lines).
- MIT license.

### Removed (vs upstream macOS)

- `move_mouse`, `drag`, `wait`, `double_click`, `arrange_window`, `navigate_browser`, `list_apps` — composable from the remaining 8 tools.
- Multi-arch prebuilt binaries, codesign helper, GitHub Actions CI, benchmark harness — not relevant on Linux.
