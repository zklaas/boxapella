"""Settings in ~/.config/boxapella/settings.json (Windows: %APPDATA%\\Boxapella;
macOS: ~/Library/Application Support/Boxapella)."""
from __future__ import annotations

import json
import os
import sys

if os.name == "nt":
    CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Boxapella")
elif sys.platform == "darwin":
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Boxapella")
else:
    CONFIG_DIR = os.path.expanduser("~/.config/boxapella")
PATH = os.path.join(CONFIG_DIR, "settings.json")
DEFAULTS = {
    "latency_ms": 0.0,         # headphones out + mic in (Calibrate finds it)
    "video_offset_ms": 0.0,    # extra lip-sync nudge for new takes' video
    "camera": "",              # /dev/videoN or "test"; "" = first found
    "mic_target": "",          # PipeWire source; "" = default
    "count_in": 4,
    "bpm": 90.0,
    "metronome": False,
    "mirror": True,
    "backing_level": 1.0,
    "keep_key": True,          # VocalFry voices move by whole octaves only
    "export_size": "1920 × 1080",
    "last_project": "",
    "picture": "auto",         # Linux only: light | full | auto (= light inside a virtual machine)
}


_VM = None


def in_virtual_machine() -> bool:
    """True when this is Linux inside a virtual machine (cached)."""
    global _VM
    if _VM is None:
        _VM = False
        if sys.platform.startswith("linux"):
            try:
                import subprocess
                out = subprocess.run(["systemd-detect-virt", "--vm"], capture_output=True,
                                     text=True, timeout=3)
                _VM = out.returncode == 0 and out.stdout.strip() not in ("", "none")
            except Exception:       # noqa: BLE001 - no systemd, timeout...: assume real hardware
                _VM = False
    return _VM


def light_picture(cfg) -> bool:
    """Fewer, smaller redraws of the picture.  On a VirtualBox guest, copying many
    screen updates to the host starves the host's audio and the sound stutters
    (listening tests in FacebookDiary and PlugPlay, 2026-11-22; the guest's own
    audio tools show nothing).  Linux only: Windows and macOS draw as before."""
    if not sys.platform.startswith("linux"):
        return False
    mode = cfg.get("picture", "auto")
    if mode in ("light", "full"):
        return mode == "light"
    return in_virtual_machine()


def load() -> dict:
    d = dict(DEFAULTS)
    try:
        with open(PATH) as f:
            d.update(json.load(f))
    except (OSError, ValueError):
        pass
    return d


def save(d: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, PATH)
