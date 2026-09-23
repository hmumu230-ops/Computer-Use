# Testing standards — enhanced linux-computer-use fork

## Layers

| Layer | Scope | Runs where | Marker |
|-------|-------|-----------|--------|
| Unit (`tests/unit/`) | pure logic: verb mapping, locator/fingerprint, NDJSON codec, error shaping, parsers (nmcli/journalctl/lsblk), capability matrix | anywhere incl. Windows dev host (all externals mocked) | default |
| Bridge protocol (`tests/protocol/`) | bridge subprocess over real stdio pipes, NDJSON roundtrip, handshake, schema validation, crash recovery | anywhere python3 exists (no `gi` needed for protocol-level) | default |
| X11 integration (`tests/integration/`) | real AT-SPI + real apps | Linux only: `Xvfb + openbox + dbus + at-spi2-registryd` | `-m xvfb` |
| Wayland integration | per-compositor backends | `mutter --headless`, `kwin_wayland --virtual`, `sway --headless` — optional lanes | `-m wayland` |
| E2E (`tests/e2e/`, `-m e2e`) | scripted app flows (gnome-calculator arithmetic, gedit edit+save) | desktop session or Xvfb lane | `-m e2e` |

## Commands

```bash
uv run pytest -x -q                    # unit + protocol (CI-safe everywhere)
uv run pytest -m xvfb                  # X11 integration (needs xvfb, openbox, at-spi2)
uv run pytest -m "xvfb or wayland"     # all GUI lanes available
uv run ruff check bridge mcp_server
```

## Xvfb lane recipe (CI)

```bash
export DISPLAY=:99
Xvfb :99 -screen 0 1280x800x24 &
openbox &                                   # any EWMH WM works
dbus-run-session -- sh -c '
  /usr/libexec/at-spi2-registryd &          # path varies: at-spi2-core/libexec
  /usr/libexec/at-spi-bus-launcher --launch-immediately &
  pytest -m xvfb'
# Debian: apt install xvfb openbox dbus-x11 at-spi2-core python3-gi \
#         gir1.2-atspi-2.0 xdotool wmctrl scrot xclip gnome-calculator gedit
```

The bridge under test must run `/usr/bin/python3` (system `gi`), not the uv venv —
assert this in a test (`sys.prefix` check) so a venv-local bridge fails loudly.

## Conventions

- **Never false-pass on missing GUI.** If `DISPLAY`/`WAYLAND_DISPLAY` or AT-SPI bus
  is absent, tests `pytest.skip(reason=...)` — and CI asserts the skip count is 0
  in lanes where the env is provisioned.
- New modules get `tests/unit/test_<area>.py` with mocked externals
  (`subprocess.run`, `gi.repository.Atspi`, D-Bus calls). Provide a `FakeAtspi`
  tree fixture — hand-rolled, since `gi` is unavailable off-Linux.
- Bridge tests spawn the real `bridge.py` subprocess; fake only the OS layer
  (monkeypatch `shutil.which`/command table or inject a fake backend module).
- Backend routing tests: parametrize `XDG_SESSION_TYPE`/`XDG_CURRENT_DESKTOP`/
  socket env vars → assert chosen backend class; each backend gets a fake
  transport (no real swaymsg/hyprctl needed).
- Safety-gated paths: assert `CONFIRM_REQUIRED` shape, single-use token,
  action binding, TTL expiry — never execute the dangerous op.
- Ref staleness: kill the app or drop the fake node → assert `STALE_REF`,
  never a wrong-target click.
- GUI-touching tests restore state (clipboard contents, focus, window rects,
  DND/notification settings).
- Parsers tested against recorded CLI output fixtures (`tests/fixtures/`),
  including locale-sensitive variants — always run real commands with
  `LC_ALL=C` + `--no-pager`.
- Screenshot assertions compare region crops or OCR text, not byte-identical
  PNGs (compositor-dependent pixels).

## Coverage expectations

- Every new tool: ≥1 happy-path + ≥1 error-path + ≥1 unsupported-path test
  (`UNSUPPORTED_*` when capability absent).
- Ref resolution: each ladder step (live probe, index path, fingerprint,
  STALE_REF) has a test; generation-mismatch ref → STALE_REF.
- Every backend dispatch table entry: detection → right class chosen.
- Every structured error carries `code`, `message`, `hint`, `retryable`,
  optional `permission`.
- Every write action in system tools: `required` permission declared and
  preflight tested with a mocked `pkcheck`/`sudo -n` matrix.
- OCR: Tier0 (tree text) tested with FakeAtspi; Tier1/2 absence →
  `ENGINE_UNAVAILABLE`; synthetic-ref registration has a test.
- Clipboard: format report + set/get roundtrip per session type (mock xclip /
  wl-copy binaries via PATH shim in `tests/fakes/`).

## Acceptance gate

A phase (L1–L7) is done when:

1. Its ACCEPTANCE.md rows move to 🧪 or better — no row silently dropped.
2. `pytest` unit+protocol green on the dev host.
3. `pytest -m xvfb` green in CI for anything touching AT-SPI/X11.
4. Rows requiring real compositors (GNOME ext, KWin EIS, portal consent) stay
   ⬜ until verified on real hardware — honest pending, not assumed.
