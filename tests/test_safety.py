"""Tests for the safety gate — confirm-token flow for dangerous actions."""

import time

import pytest

import windows_mcp.safety as safety


@pytest.fixture(autouse=True)
def clean_tokens(monkeypatch, tmp_path):
    safety._tokens.clear()
    # Keep the audit log out of the user's real LOCALAPPDATA during tests.
    monkeypatch.setattr(safety, "_AUDIT_PATH", str(tmp_path / "audit.log"))
    yield
    safety._tokens.clear()


def _gate(action_key, token=None, dangerous=True):
    return safety.gate(action_key, f"desc:{action_key}", token, dangerous=dangerous)


def _token_from(msg: str) -> str:
    return msg.split("confirm='")[1].split("'")[0]


def test_gate_without_token_returns_confirm_required():
    result = _gate("system.shutdown")
    assert result is not None
    assert result.startswith("CONFIRM_REQUIRED")
    assert "confirm=" in result


def test_gate_with_valid_token_passes():
    token = _token_from(_gate("service.stop:Spooler"))
    assert _gate("service.stop:Spooler", token=token) is None


def test_token_is_single_use():
    token = _token_from(_gate("process.kill:1"))
    assert _gate("process.kill:1", token=token) is None
    assert _gate("process.kill:1", token=token) is not None


def test_token_bound_to_action():
    token = _token_from(_gate("system.shutdown"))
    assert _gate("system.restart", token=token) is not None


def test_expired_token_rejected(monkeypatch):
    token = _token_from(_gate("fs.delete:C:\\x"))
    future = time.time() + safety._TOKEN_TTL + 5
    monkeypatch.setattr(time, "time", lambda: future)
    assert _gate("fs.delete:C:\\x", token=token) is not None


def test_unknown_token_rejected():
    assert _gate("system.shutdown", token="deadbeefdeadbeef") is not None


def test_policy_off_never_gates(monkeypatch):
    monkeypatch.setenv("WINDOWS_MCP_REQUIRE_CONFIRM", "off")
    assert _gate("system.shutdown") is None


def test_policy_dangerous_allows_readonly(monkeypatch):
    monkeypatch.setenv("WINDOWS_MCP_REQUIRE_CONFIRM", "dangerous")
    assert _gate("service.list", dangerous=False) is None


def test_policy_all_gates_readonly(monkeypatch):
    monkeypatch.setenv("WINDOWS_MCP_REQUIRE_CONFIRM", "all")
    assert _gate("service.list", dangerous=False) is not None


def test_audit_log_written(tmp_path):
    _gate("system.shutdown")
    log = tmp_path / "audit.log"
    assert log.exists()
    assert '"event": "blocked"' in log.read_text()
    assert "system.shutdown" in log.read_text()
