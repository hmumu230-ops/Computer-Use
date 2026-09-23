"""Environment detection with faked env vars and tools."""
import detect


def test_x11_detected(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.setattr(detect, "_detect_init", lambda: ("systemd", 252))
    monkeypatch.setattr(detect, "_detect_audio", lambda: "pipewire")
    monkeypatch.setattr(detect, "_detect_net", lambda: "networkmanager")
    monkeypatch.setattr(detect, "_detect_virt", lambda: ("", False))
    monkeypatch.setattr(detect, "which", lambda t: None)
    detect._ENV_OBJ = None
    e = detect.detect_env(refresh=True)
    assert e.session_type == "x11" and e.compositor == "x11"


def test_sway_socket_wins(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("SWAYSOCK", "/run/user/1000/sway.sock")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("NIRI_SOCKET", raising=False)
    monkeypatch.delenv("WAYFIRE_SOCKET", raising=False)
    monkeypatch.setattr(detect, "_detect_init", lambda: ("systemd", 252))
    monkeypatch.setattr(detect, "_detect_audio", lambda: "pipewire")
    monkeypatch.setattr(detect, "_detect_net", lambda: "networkmanager")
    monkeypatch.setattr(detect, "_detect_virt", lambda: ("", False))
    monkeypatch.setattr(detect, "which", lambda t: None)
    monkeypatch.setattr(detect, "_proc_running", lambda n: False)
    detect._ENV_OBJ = None
    e = detect.detect_env(refresh=True)
    assert e.compositor == "sway"


def test_capabilities_domains(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("NIRI_SOCKET", raising=False)
    monkeypatch.delenv("WAYFIRE_SOCKET", raising=False)
    monkeypatch.setattr(detect, "_detect_init", lambda: ("systemd", 252))
    monkeypatch.setattr(detect, "_detect_audio", lambda: "pipewire")
    monkeypatch.setattr(detect, "_detect_net", lambda: "networkmanager")
    monkeypatch.setattr(detect, "_detect_virt", lambda: ("", False))
    monkeypatch.setattr(detect, "which",
                        lambda t: "/usr/bin/" + t if t in
                        ("wmctrl", "xdotool", "scrot", "xclip",
                         "notify-send", "tesseract") else None)
    detect._ENV_OBJ = None
    caps = detect.capabilities()
    assert caps["window"]["status"] == "supported"
    assert caps["input"]["status"] == "supported"
    assert caps["screenshot"]["status"] == "supported"
    assert caps["clipboard"]["status"] == "supported"


def test_gnome_locked_reports_unsupported(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("SWAYSOCK", raising=False)
    monkeypatch.delenv("NIRI_SOCKET", raising=False)
    monkeypatch.delenv("WAYFIRE_SOCKET", raising=False)
    monkeypatch.setattr(detect, "_detect_init", lambda: ("systemd", 252))
    monkeypatch.setattr(detect, "_detect_audio", lambda: "pipewire")
    monkeypatch.setattr(detect, "_detect_net", lambda: "networkmanager")
    monkeypatch.setattr(detect, "_detect_virt", lambda: ("", False))
    monkeypatch.setattr(detect, "which", lambda t: None)
    monkeypatch.setattr(detect, "_proc_running", lambda n: False)
    monkeypatch.setattr(detect, "_has_dbus_name", lambda n, e: True)

    def fake_run_out(cmd, *a, **kw):
        joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "Eval" in joined:
            return "(false, '')"                       # safe mode
        if "Extensions.Windows" in joined or "List" in joined:
            return "DBus.Error.AccessDenied"           # no window-calls ext
        return ""
    monkeypatch.setattr(detect, "run_out", fake_run_out)
    detect._ENV_OBJ = None
    caps = detect.capabilities()
    assert caps["window"]["status"] == "unsupported"
    assert "window-calls" in caps["window"]["hint"]
