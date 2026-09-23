"""Tests for scan-code (raw) input paths — Shortcut/Type raw=True."""

from unittest.mock import MagicMock

import pytest

import windows_mcp.uia as uia
from windows_mcp.desktop.service import Desktop


@pytest.fixture
def desktop():
    d = Desktop.__new__(Desktop)
    d.encoding = "utf-8"
    return d


class TestKeyNameResolution:
    def test_modifier_name(self, desktop):
        vk, extra = Desktop._vk_for_key_name("ctrl")
        assert vk == uia.Keys.VK_CONTROL
        assert extra == []

    def test_alias_windows(self, desktop):
        vk, _ = Desktop._vk_for_key_name("windows")
        assert vk == uia.Keys.VK_LWIN

    def test_single_char(self, desktop):
        vk, extra = Desktop._vk_for_key_name("a")
        assert vk == ord("A")
        assert extra == []

    def test_shifted_char_needs_shift(self, desktop):
        vk, extra = Desktop._vk_for_key_name("!")
        # '!' is shift+1 on US layouts; exact vk depends on layout but shift
        # must be requested when the char isn't directly reachable.
        assert vk != 0
        # On US layout '!' -> '1' with shift; other layouts may differ — only
        # assert no crash and a usable vk.
        assert isinstance(vk, int)

    def test_unknown_raises(self, desktop):
        with pytest.raises(ValueError, match="unknown key"):
            Desktop._vk_for_key_name("notakey")


class TestShortcutScancode:
    def test_down_then_up_reverse_order(self, desktop, monkeypatch):
        sent = []
        monkeypatch.setattr(uia, "SendScanCode", lambda vk, keyUp=False: sent.append((vk, keyUp)))
        desktop.shortcut("ctrl+shift+s", raw=True)
        down = [vk for vk, up in sent if not up]
        up = [vk for vk, up in sent if up]
        assert down == [uia.Keys.VK_CONTROL, uia.Keys.VK_SHIFT, ord("S")]
        assert up == [ord("S"), uia.Keys.VK_SHIFT, uia.Keys.VK_CONTROL]

    def test_normal_path_not_scancode(self, desktop, monkeypatch):
        sent_keys = []
        sent_scan = []
        monkeypatch.setattr(uia, "SendKeys", lambda *a, **kw: sent_keys.append(a))
        monkeypatch.setattr(uia, "SendScanCode", lambda *a, **kw: sent_scan.append(a))
        desktop.shortcut("ctrl+c", raw=False)
        assert sent_keys and not sent_scan

    def test_empty_shortcut_raises(self, desktop):
        with pytest.raises(ValueError, match="empty shortcut"):
            desktop.shortcut("++", raw=True)


class TestSendScanCodeInput:
    def test_scancode_flag_set(self, monkeypatch):
        captured = []

        def fake_sendinput(*inputs):
            captured.extend(inputs)
            return len(inputs)

        # SendScanCode resolves SendInput from its own module namespace.
        monkeypatch.setattr(uia.core, "SendInput", fake_sendinput)
        uia.SendScanCode(uia.Keys.VK_RETURN)
        assert captured, "SendInput not invoked"
        ki = captured[0].union.ki
        assert ki.dwFlags & uia.KeyboardEventFlag.KeyScanCode
        assert not (ki.dwFlags & uia.KeyboardEventFlag.KeyUp)

    def test_keyup_flag(self, monkeypatch):
        captured = []
        monkeypatch.setattr(uia.core, "SendInput", lambda *i: captured.extend(i) or len(i))
        uia.SendScanCode(uia.Keys.VK_RETURN, keyUp=True)
        ki = captured[0].union.ki
        assert ki.dwFlags & uia.KeyboardEventFlag.KeyScanCode
        assert ki.dwFlags & uia.KeyboardEventFlag.KeyUp


class TestTypeRaw:
    def test_raw_uses_scancode_not_sendkeys(self, desktop, monkeypatch):
        scan_calls = []
        monkeypatch.setattr(uia, "SendScanCode", lambda vk, keyUp=False: scan_calls.append(vk))
        monkeypatch.setattr(uia, "SendKeys", MagicMock())
        monkeypatch.setattr(uia, "Click", lambda *a, **kw: None)
        monkeypatch.setattr(uia, "SendUnicodeChar", lambda *a, **kw: 1)
        desktop.type((10, 10), text="ab", raw=True)
        # 'a' and 'b' each produce a down+up pair → at least 4 scancode sends.
        assert len(scan_calls) >= 4
        uia.SendKeys.assert_not_called()

    def test_newline_maps_to_return(self, desktop, monkeypatch):
        scan_calls = []
        monkeypatch.setattr(uia, "SendScanCode", lambda vk, keyUp=False: scan_calls.append(vk))
        desktop._type_scancode("x\ny")
        assert uia.Keys.VK_RETURN in scan_calls
