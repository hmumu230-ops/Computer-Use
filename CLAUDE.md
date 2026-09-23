# macOS-MCP: Project Documentation for Claude

## Project Overview

macOS-MCP is a lightweight, open-source MCP (Model Context Protocol) server that enables AI agents to seamlessly integrate with and automate macOS through the Accessibility API. It provides tools for file navigation, application control, UI interaction, browser automation, and system command execution.

## Tech Stack

- **Language**: Python 3.11+
- **Package Manager**: UV
- **Build System**: Hatchling
- **Code Quality**: Ruff (formatter/linter at 100 character line length)

## Architecture

The project is organized into modular services:

### Entry Point (`src/macos_mcp/__main__.py`)
- Registers all MCP tools
- Initializes core services
- Manages server lifecycle

### Desktop Service (`src/macos_mcp/desktop/service.py`)
- High-level automation orchestrator
- Handles window management, screenshots, input actions, and clipboard operations
- Coordinates with Tree service for UI discovery

### Tree Service (`src/macos_mcp/tree/service.py`)
- Captures the macOS accessibility tree from active and background windows
- Traverses UI elements and identifies interactive components
- Scans multiple sources concurrently (focused app, dock, menu bar, control center, etc.)

### Supporting Modules
- **Config modules**: Constants for interactive roles, actions, and UI configuration
- **Views modules**: Data classes for structured representation of desktop and tree state

## Key Features

- **Native macOS Integration**: Uses Accessibility API (`ApplicationServices`) for native UI interaction
- **Vision-Optional**: Works with any LLM, no requirement for specialized vision models
- **Parallel Scanning**: Scans multiple UI sources concurrently for improved performance
- **Smart Context Awareness**: Detects application state (Launchpad, Control Center, etc.) and adjusts behavior
- **Screenshot Annotations**: Generates visual references with numbered bounding boxes

## Tools Provided

| Tool | Purpose |
|------|---------|
| `Click` | Click at coordinates or `ref='@eN'` (semantic AXPress first, coords fallback) |
| `Type` | Type text at coordinates or into a `ref` element (focus + AXValue when settable) |
| `Scroll` | Scroll vertically or horizontally, at coords or a `ref` element's centre |
| `Move` | Move or drag mouse pointer to coords or a `ref` element's centre |
| `Act` | Perform a semantic AX action on a `ref` (AXPress/AXShowMenu/AXIncrement…) — no coordinates |
| `FindElements` | Live-search the accessibility tree by role/name; hits mint fresh `@eN` refs |
| `WaitFor` | Poll until a ref resolves again or a role/name match appears |
| `Shortcut` | Press keyboard shortcuts (Cmd+C, etc.) |
| `Wait` | Pause execution for defined duration |
| `Snapshot` | Capture desktop state with optional visual annotations; mints `@eN`/`@wN` refs |
| `FindText` | Vision OCR over the screen; hits mint synthetic `@eN` refs |
| `Clipboard` | Get/set clipboard payloads: text, image (base64 PNG), file lists |
| `App` | Launch/manage applications |
| `Shell` | Execute shell commands or AppleScript (confirm-token gate via `MACOS_MCP_REQUIRE_CONFIRM`) |
| `System` | System domains: probe/identity/power/display/device/network/audio/env/log |
| `Process` | List processes or kill by pid (kill is confirm-gated) |
| `Service` | launchd service list/control (kickstart/enable/disable/bootout, confirm-gated) |
| `Scrape` | Extract and convert webpage content to Markdown |

### Enhanced-fork additions (branch `enhanced`)

- **Persistent refs**: `Snapshot` mints `@eN` element refs and `@wN` window refs, scoped to a
  capture generation — refs from an older Snapshot are stale. Resolution ladder at action
  time: live element probe → runtime re-search by `(pid, role, name, nth)` → `StaleRef`.
- **Pattern-first input**: ref-based actions prefer AX verbs (`AXPress`, `AXShowMenu`,
  settable `AXValue`/`AXFocused`) before synthetic coordinate input.
- **Structured errors**: `macos_mcp/errors.py` `{code, message, hint, retryable}` — e.g.
  `STALE_REF`, `CONFIRM_REQUIRED`, `PERMISSION_REQUIRED`.
- **Safety gate**: `macos_mcp/safety.py` — single-use confirm tokens bound to the action
  digest, 120 s TTL, enabled via `MACOS_MCP_REQUIRE_CONFIRM` (`1`, or comma-separated
  action prefixes like `shell`).
- **Clipboard payloads** (`clipboard.py`): text via pbcopy/pbpaste; image (PNG/TIFF)
  and file-URL lists via NSPasteboard.
- **OCR** (`ocr.py`): native Vision `VNRecognizeTextRequest`; `FindText` mints synthetic
  refs with Retina physical→logical scale correction.
- **System toolkit** (`system.py`): subprocess-only domains (probe/identity/process/
  launchd/audio/network/display/device/power/env/log); destructive writes are
  confirm-gated.
- **Direct CLI**: `macos-mcp doctor` (env/framework/TCC diagnosis), `macos-mcp tools`,
  `macos-mcp call <Tool> --arg k=v`.
- Core modules `errors.py`, `refs.py`, `safety.py`, `clipboard.py` (text path),
  `ocr.py`, `system.py` are PyObjC-free and unit-testable on any platform;
  tests/conftest.py skips PyObjC-dependent test files when the frameworks are absent.

## Development Guidelines

### Code Style
- Line length: 100 characters maximum
- Use double quotes for strings
- Follow PEP 8 naming conventions (snake_case functions, PascalCase classes, UPPER_CASE constants)

### Testing
- Use pytest for unit and integration tests
- Add tests for new features
- Ensure all tests pass before submitting PRs

### Documentation
- Include Google-style docstrings for public functions
- Document Args, Returns, and Raises sections
- Include type hints

## Security Considerations

⚠️ **Important**: macOS-MCP has full system access with no sandboxing. It executes real actions directly on the macOS system.

- Grant accessibility permissions only to trusted applications
- Be cautious when using the Shell tool with elevated commands
- Review and understand actions being performed by AI agents
- Consider deployment only in virtual machines or isolated environments

## Deployment Recommendations

- **Safe**: Virtual machines with snapshots, macOS VMs, isolated test systems
- **Unsafe**: Production systems, machines with irreplaceable data, shared systems

## System Requirements

- macOS 12 (Monterey) or later
- Python 3.11+
- UV package manager
- Accessibility permissions granted to the terminal/application

## Grant Accessibility Permissions

1. Open **System Settings** > **Privacy & Security** > **Accessibility**
2. Click the lock icon and authenticate
3. Add your terminal application (Terminal, iTerm2, VS Code, etc.)
4. Restart the terminal after granting permissions

## Running the Server

```shell
# Direct execution
uvx macos-mcp

# In Claude Desktop config
{
  "mcpServers": {
    "macos-mcp": {
      "command": "uvx",
      "args": ["macos-mcp"]
    }
  }
}
```

## Dependencies

Key dependencies and their purposes:
- **pyobjc-framework-ApplicationServices**: Accessibility API bridge
- **pyobjc-framework-Cocoa**: Cocoa framework access
- **pyobjc-framework-Quartz**: Quartz/CoreGraphics access
- **pillow**: Image processing for screenshots
- **fastmcp**: MCP protocol implementation
- **markdownify**: HTML to Markdown conversion
- **requests**: HTTP client for web scraping

## Future Enhancements

Consider areas for improvement and extension:
- Enhanced multi-monitor support
- Improved performance optimization for large UI trees
- Additional browser automation tools
- System preference management

## Contributing

See CONTRIBUTING.md for detailed contribution guidelines.

## Security Policy

See SECURITY.md for comprehensive security information and responsible disclosure process.

## License

MIT License - see LICENSE file for details
