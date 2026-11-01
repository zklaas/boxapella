"""Bridge to VocalFry (~/Claude/VocalFry): reshape a take's voice.

Two ways, both through the `vocalfry` program:
  * a preset, rendered without the GUI (`vocalfry render ... --preset NAME`);
  * a custom voice: VocalFry's editor opens on the take
    (`vocalfry --boxapella OUT.wav [--settings S.json] TAKE.wav`) and its
    "Send to Boxapella" button writes OUT.wav plus OUT's .voice.json, which
    Boxapella notices and mixes in.
VocalFry's timing controls (speaking rate, pause length) would change the
clip's length and break lip sync, so they are always held at 100 %.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from .media import WINDOWS, _kw as _media_kw


def _kw() -> dict:
    """No console window on Windows, and VocalFry's output as UTF-8 either way."""
    return dict(_media_kw(), env=dict(os.environ, PYTHONIOENCODING="utf-8"))

VOCALFRY_DIR = os.path.expanduser("~/Claude/VocalFry")
KEEP_TIMING = ["--set", "rate=100", "--set", "pause=100"]


class VoiceError(Exception):
    pass


def command() -> list[str] | None:
    """How to run VocalFry: its launcher on PATH, else its own virtualenv's Python.
    Windows looks for VocalFry beside Boxapella too (e.g. both cloned into one folder)."""
    exe = shutil.which("vocalfry")
    local = os.path.expanduser("~/.local/bin/vocalfry")
    if not exe and not WINDOWS and os.access(local, os.X_OK):
        exe = local
    if exe:
        return [exe]
    for folder in _vocalfry_dirs():
        py = os.path.join(folder, ".venv", "Scripts" if WINDOWS else "bin",
                          "python.exe" if WINDOWS else "python")
        script = os.path.join(folder, "vocalfry.py")
        if os.path.exists(py) and os.path.exists(script):
            return [py, script]
    return None


def _vocalfry_dirs() -> list[str]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [VOCALFRY_DIR, os.path.join(os.path.dirname(here), "VocalFry"),
            os.path.join(os.path.dirname(here), "vocalfry")]


def available() -> bool:
    return command() is not None


def presets() -> list[tuple[str, str]]:
    """(name, path) of every VocalFry preset, menu or not."""
    cmd = command()
    if not cmd:
        return []
    try:
        out = subprocess.run(cmd + ["presets"], capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace", **_kw()).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.splitlines():               # "[menu] Name             /path/or/C:\\path"
        m = re.match(r"^.{6} (.*?)\s+((?:[A-Za-z]:[\\/]|/|\\\\).*)$", line)
        if m:
            found.append((m[1].strip(), m[2].strip()))
    return found


def render(src: str, out: str, preset: str = "", settings: str = "") -> None:
    """Reshape src into out with a preset (name or file) or a settings JSON."""
    cmd = command()
    if not cmd:
        raise VoiceError("VocalFry isn't installed (expected the `vocalfry` command).")
    args = cmd + ["render", src, out]
    if preset:
        args += ["--preset", preset]
    if settings:
        args += ["--settings", settings]
    p = subprocess.run(args + KEEP_TIMING, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **_kw())
    if p.returncode != 0 or not os.path.exists(out):
        raise VoiceError((p.stderr or p.stdout).strip()[-800:] or "vocalfry render failed")


def edit(src: str, out: str, settings: str = "") -> subprocess.Popen:
    """Open VocalFry's editor on src; it sends its result to out."""
    cmd = command()
    if not cmd:
        raise VoiceError("VocalFry isn't installed (expected the `vocalfry` command).")
    args = cmd + ["--boxapella", out]
    if settings and os.path.exists(settings):
        args += ["--settings", settings]
    extra = _kw() if WINDOWS else {"start_new_session": True}
    return subprocess.Popen(args + [src], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
