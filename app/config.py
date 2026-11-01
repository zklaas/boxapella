"""Settings in ~/.config/boxapella/settings.json (Windows: %APPDATA%\\Boxapella)."""
from __future__ import annotations

import json
import os

CONFIG_DIR = (os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Boxapella")
              if os.name == "nt" else os.path.expanduser("~/.config/boxapella"))
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
}


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
