"""Unit tests for macos_mcp.system — parsers are pure Python."""

import pytest

from macos_mcp import system
from macos_mcp.errors import CuError


class TestKvLines:
    def test_colon_and_equals(self):
        out = system._kv_lines(
            "ProductName: macOS\nProductVersion: 14.5\nBuild = 23F79\n")
        assert out["ProductName"] == "macOS"
        assert out["ProductVersion"] == "14.5"
        assert out["Build"] == "23F79"


class TestProcessList:
    PS = (
        "  PID COMM              %CPU %MEM ARGS\n"
        "    1 launchd            0.0  0.1 /sbin/launchd\n"
        "  442 Safari             3.2  2.1 /Applications/Safari.app/x\n"
    )

    def test_parse(self, monkeypatch):
        monkeypatch.setattr(system, "_run", lambda *a, **k: self.PS)
        rows = system.process_list()
        assert rows[0]["pid"] == 1 and rows[0]["comm"] == "launchd"
        assert rows[1]["cpu"] == 3.2

    def test_name_filter(self, monkeypatch):
        monkeypatch.setattr(system, "_run", lambda *a, **k: self.PS)
        rows = system.process_list(name="safari")
        assert len(rows) == 1 and rows[0]["pid"] == 442


class TestServiceList:
    def test_parse(self, monkeypatch):
        out = "PID\tStatus\tLabel\n-\t0\tcom.apple.cfprefsd\n512\t0\tcom.test\n"
        monkeypatch.setattr(system, "_run", lambda *a, **k: out)
        rows = system.service_list()
        assert rows[0]["label"] == "com.apple.cfprefsd"
        assert rows[1]["pid"] == "512"

    def test_filter(self, monkeypatch):
        out = ("PID\tStatus\tLabel\n-\t0\tcom.apple.cfprefsd\n"
               "-\t0\torg.other.svc\n")
        monkeypatch.setattr(system, "_run", lambda *a, **k: out)
        rows = system.service_list(filter="apple")
        assert len(rows) == 1


class TestAudioGet:
    def test_parse(self, monkeypatch):
        monkeypatch.setattr(system, "_run",
                            lambda *a, **k: "42|false\n")
        assert system.audio_get() == {"volume": 42, "muted": False}

    def test_muted(self, monkeypatch):
        monkeypatch.setattr(system, "_run", lambda *a, **k: "10|true\n")
        assert system.audio_get()["muted"] is True


class TestServiceControl:
    def test_kickstart_target(self, monkeypatch):
        calls = []

        def fake(cmd, **kw):
            calls.append(cmd)
            return "501\n" if cmd[:2] == ["id", "-u"] else ""

        monkeypatch.setattr(system, "_run", fake)
        system.service_control("kickstart", "com.test.svc")
        assert calls[-1] == ["launchctl", "kickstart", "-k",
                             "gui/501/com.test.svc"]

    def test_unknown_action(self, monkeypatch):
        monkeypatch.setattr(system, "_run", lambda *a, **k: "501\n")
        with pytest.raises(CuError):
            system.service_control("nuke", "com.test")


class TestRunGuards:
    def test_missing_tool(self, monkeypatch):
        monkeypatch.setattr(system.shutil, "which", lambda c: None)
        with pytest.raises(CuError) as ei:
            system._run(["definitely-not-a-tool"])
        assert ei.value.code == "TOOL_NOT_FOUND"
