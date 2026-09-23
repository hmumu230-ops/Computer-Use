"""Confirm-token safety gate."""
import os
import pytest

import safety
from errors import ConfirmRequired


@pytest.fixture(autouse=True)
def _policy(monkeypatch):
    monkeypatch.setenv("LINUX_MCP_REQUIRE_CONFIRM", "dangerous")
    monkeypatch.setenv("LCU_AUDIT_LOG", "/tmp/lcu-test-audit.log")
    yield
    if os.path.exists("/tmp/lcu-test-audit.log"):
        os.remove("/tmp/lcu-test-audit.log")


def test_safe_action_passes():
    safety.gate("service:list", {}, dangerous=False)   # no raise


def test_dangerous_requires_token():
    with pytest.raises(ConfirmRequired) as e:
        safety.gate("power:poweroff", {}, True)
    assert e.value.token


def test_token_consumes_and_binds():
    try:
        safety.gate("power:poweroff", {}, True)
    except ConfirmRequired as e:
        tok = e.token
    # wrong action binding → still refused
    with pytest.raises(ConfirmRequired):
        safety.gate("power:reboot", {}, True, tok)
    # right action → passes, single-use
    safety.gate("power:poweroff", {}, True, tok)
    with pytest.raises(ConfirmRequired):
        safety.gate("power:poweroff", {}, True, tok)


def test_policy_off(monkeypatch):
    monkeypatch.setenv("LINUX_MCP_REQUIRE_CONFIRM", "off")
    safety.gate("power:poweroff", {}, True)


def test_policy_all(monkeypatch):
    monkeypatch.setenv("LINUX_MCP_REQUIRE_CONFIRM", "all")
    with pytest.raises(ConfirmRequired):
        safety.gate("service:list", {}, False)
