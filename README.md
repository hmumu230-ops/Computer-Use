# Computer-Use

Cross-platform **computer-use** toolkit: give any LLM agent (Claude, GPT,
Gemini, local models, MCP clients, or direct CLI callers) full control of a
desktop — mouse, keyboard, windows, accessibility tree, clipboard,
screenshots, OCR, and system administration.

Three MCP servers, one shared architecture, one per OS:

| Dir | Base fork | Tools | Stack |
|-----|-----------|-------|-------|
| [`windows/`](windows/) | [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | 33 | UIA patterns, Win32, scan-code input, RapidOCR |
| [`macos/`](macos/) | [Jeomon/macos-mcp](https://github.com/Jeomon/macos-mcp) | 20 | Accessibility API (AX), Vision OCR, NSPasteboard, launchd |
| [`linux/`](linux/) | [tak-uukti/linux-computer-use](https://github.com/tak-uukti/linux-computer-use) | 35 | AT-SPI2, X11 + Wayland (GNOME/KDE/wlroots), portals, PipeWire |

## Shared architecture

Every platform speaks the same contract, so an agent that works on one OS
transfers to the others:

- **`@eN` element refs / `@wN` window refs** — minted per Snapshot
  generation, re-resolved at action time (live probe → locator search →
  `STALE_REF`). No blind coordinate replay.
- **Semantic-first actions** — UIA patterns / AT-SPI verbs / AX actions
  tried before synthetic pointer input; `Act`-style tools are ref-only.
- **Structured errors** — `{code, message, hint, retryable}` on every
  platform (`STALE_REF`, `CONFIRM_REQUIRED`, `PERMISSION_REQUIRED`,
  `UNSUPPORTED_*`, `ENGINE_UNAVAILABLE`, …).
- **Confirm-token safety gate** — destructive ops (kill, service control,
  power, shell under policy) return `CONFIRM_REQUIRED` + single-use token;
  env `{PLATFORM}_MCP_REQUIRE_CONFIRM`.
- **OCR fallback** — on-screen text → synthetic `@eN` refs (RapidOCR /
  Vision / tesseract).
- **Direct CLI** — `tools`, `call <Tool> --arg k=v`, `doctor` on every
  platform; no MCP client required.

## Quick start

Each directory is an independent, installable package — see its README:

```bash
# Windows
cd windows && uv sync && uv run windows-mcp

# macOS (requires macOS 12+)
cd macos && uv sync && uv run macos-mcp

# Linux (system python for AT-SPI)
cd linux && uv sync && linux-computer-use-mcp serve
```

Per-platform agent docs live in `*/skills/computer-use/SKILL.md`;
verification status in `*/docs/ACCEPTANCE.md` + `*/docs/TESTING.md`.

## Status

| Platform | Tests | Live-verified |
|----------|-------|---------------|
| Windows  | 665   | ✅ Snapshot/FindText/Clipboard/Window/Identity verified |
| macOS    | 94 (pure lane) | ⬜ pending a macOS host |
| Linux    | 69    | ⬜ pending a Linux desktop |

## Provenance & license

Each subdirectory is a fork preserving its upstream history and license
(see `windows/LICENSE`, `macos/LICENSE`, `linux/LICENSE`); enhanced-fork
work lives on the merged history of this repo's `main` branch.
