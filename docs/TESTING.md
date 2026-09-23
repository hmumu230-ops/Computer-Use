# Testing standards — enhanced Windows-MCP fork

## Layers

| Layer | Scope | Runs where |
|-------|-------|-----------|
| Unit (`tests/`) | pure logic, mocked UIA/win32 | anywhere (CI-safe) |
| Integration | real tools against real host state (registry reads, window list, clipboard) | Windows desktop session |
| E2E (`tests/e2e/`, `-m e2e`) | scripted app flows | interactive desktop only |

## Commands

```powershell
uv run pytest -x -q              # full suite (661 tests at last run)
uv run ruff check src/windows_mcp
uv run ruff format --check src/windows_mcp
uv run python -m windows_mcp tools          # list registered tools
uv run python -m windows_mcp call Identity  # CLI smoke test
```

## Conventions

- New modules get a `tests/test_<area>.py` with mocked externals
  (`win32clipboard`, `uia.SendInput`, `PowerShellExecutor.execute_command`).
- Tools are invoked through a `FakeMCP` harness or `fastmcp.FastMCP` +
  `mcp.call_tool` for isError-compliance coverage.
- Safety-gated paths: assert `CONFIRM_REQUIRED` shape, token single-use,
  action binding, TTL expiry — never execute the dangerous op in tests.
- GUI-touching tests must restore state (clipboard, focus, window pos).

## Coverage expectations

- Every new tool: ≥1 happy-path test + ≥1 error-path test.
- Ref resolution: each ladder step (live probe, index path, AutomationId,
  RuntimeId scan, STALE_REF) has a test.
- Structured errors carry `code`, `message`, `hint`, `retryable`.
