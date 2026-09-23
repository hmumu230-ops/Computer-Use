"""Protocol-level tests: spawn the real bridge.py on system python3 and
speak NDJSON. gi is absent on non-GNOME hosts — all AT-SPI paths degrade,
which is itself part of the contract (structured errors, never hangs).
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BRIDGE = os.path.join(ROOT, "bridge", "bridge.py")

pytestmark = pytest.mark.skipif(
    shutil.which("python3") is None or sys.platform == "win32",
    reason="needs a POSIX python3 to spawn the bridge")


@pytest.fixture(scope="module")
def bridge():
    p = subprocess.Popen(
        [shutil.which("python3"), BRIDGE],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)
    yield p
    p.kill()


def _call(bridge, cmd, **args) -> dict:
    rid = "t1"
    bridge.stdin.write(json.dumps({"id": rid, "cmd": cmd, **args}) + "\n")
    bridge.stdin.flush()
    line = bridge.stdout.readline()
    assert line, "bridge closed stdout"
    return json.loads(line)


def test_hello_handshake(bridge):
    r = _call(bridge, "hello")
    assert r["ok"] is True
    res = r["result"]
    assert "version" in res and "capabilities" in res and "session" in res
    assert res["session"]["session_type"] in ("x11", "wayland", "tty")


def test_ping(bridge):
    r = _call(bridge, "ping")
    assert r["ok"] and r["result"]["pong"]


def test_unknown_command(bridge):
    r = _call(bridge, "nonsense_xyz")
    assert r["ok"] is False
    assert r["error"]["code"] == "UNKNOWN_COMMAND"


def test_bad_json(bridge):
    bridge.stdin.write("{not json\n")
    bridge.stdin.flush()
    line = bridge.stdout.readline()
    r = json.loads(line)
    assert r["ok"] is False and r["error"]["code"] == "INVALID_ARGS"


def test_missing_arg_invalid(bridge):
    r = _call(bridge, "act")   # missing 'ref'
    assert r["ok"] is False
    assert r["error"]["code"] == "INVALID_ARGS"


def test_capabilities_shape(bridge):
    r = _call(bridge, "capabilities")
    assert r["ok"]
    caps = r["result"]
    for domain in ("window", "input", "screenshot", "clipboard", "atspi"):
        assert domain in caps
        assert caps[domain]["status"] in ("supported", "unsupported",
                                          "degraded")


def test_error_shape_complete(bridge):
    r = _call(bridge, "act", ref="@e999")
    assert r["ok"] is False
    e = r["error"]
    for k in ("code", "message", "hint", "retryable"):
        assert k in e


def test_bridge_survives_errors(bridge):
    """A stream of bad calls must not kill the loop."""
    for i in range(5):
        r = _call(bridge, "nonsense")
        assert r["ok"] is False
    r = _call(bridge, "ping")
    assert r["ok"] is True


def test_stale_ref_on_empty_store(bridge):
    r = _call(bridge, "click", ref="@e1", method="action")
    assert r["ok"] is False
    assert r["error"]["code"] in ("STALE_REF", "INVALID_ARGS")
