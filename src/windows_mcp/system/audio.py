"""Audio — volume/mute/devices/sessions via Core Audio API (pycaw → comtypes)."""

from __future__ import annotations

from typing import Any

_DEPS_HINT = "pip install pycaw"


def _endpoint():
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        raise RuntimeError(f"pycaw not installed — {_DEPS_HINT}")
    speakers = AudioUtilities.GetSpeakers()
    return speakers.EndpointVolume


def get_volume() -> dict[str, Any]:
    vol = _endpoint()
    return {
        "volume": round(vol.GetMasterVolumeLevelScalar() * 100),
        "muted": bool(vol.GetMute()),
    }


def set_volume(level: int) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    vol = _endpoint()
    vol.SetMasterVolumeLevelScalar(level / 100.0, None)
    return get_volume()


def set_mute(muted: bool) -> dict[str, Any]:
    vol = _endpoint()
    vol.SetMute(1 if muted else 0, None)
    return get_volume()


def list_devices() -> dict[str, Any]:
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        raise RuntimeError(f"pycaw not installed — {_DEPS_HINT}")
    devices = []
    default_id = None
    try:
        default_id = AudioUtilities.GetSpeakers().id
    except Exception:
        pass
    for dev in AudioUtilities.GetAllDevices():
        try:
            devices.append(
                {
                    "name": dev.FriendlyName,
                    "id": dev.id,
                    "state": int(dev.state) if dev.state is not None else None,
                    "is_default": dev.id == default_id,
                }
            )
        except Exception:
            continue
    return {"devices": devices}


def list_sessions() -> dict[str, Any]:
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        raise RuntimeError(f"pycaw not installed — {_DEPS_HINT}")
    sessions = []
    for s in AudioUtilities.GetAllSessions():
        try:
            proc = s.Process.name() if s.Process else None
        except Exception:
            proc = None
        try:
            sessions.append(
                {
                    "process": proc or "(system)",
                    "volume": round(s.SimpleAudioVolume.GetMasterVolume() * 100),
                    "muted": bool(s.SimpleAudioVolume.GetMute()),
                }
            )
        except Exception:
            continue
    return {"sessions": sessions}


def set_session_volume(process_name: str, level: int) -> dict[str, Any]:
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        raise RuntimeError(f"pycaw not installed — {_DEPS_HINT}")
    level = max(0, min(100, int(level)))
    target = process_name.lower()
    hit = False
    for s in AudioUtilities.GetAllSessions():
        try:
            name = s.Process.name() if s.Process else ""
        except Exception:
            continue
        if name.lower() == target or name.lower() == target + ".exe":
            s.SimpleAudioVolume.SetMasterVolume(level / 100.0, None)
            hit = True
    if not hit:
        raise ValueError(f"no audio session for process {process_name!r}")
    return list_sessions()
