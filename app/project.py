"""A Boxapella project: a folder holding project.json, takes/, voices/ and exports/.

Each take is a recorded (or imported) clip: takes/take-NNN.mp4 (video + audio)
and takes/take-NNN.wav (its audio, 48 kHz mono, for mixing).  A take may sit in
one template slot; takes not in a slot are kept as alternates.  A take's voice
is either as recorded, a VocalFry preset, or a custom VocalFry voice; the
reshaped audio is voices/take-NNN.wav.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field

import numpy as np

from . import media, templates

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_DIR = os.path.join(HERE, "projects")


@dataclass
class Take:
    id: str                       # "take-001"
    duration: float = 0.0
    slot: str = ""                # template slot id, "" = not shown
    offset_ms: float = 0.0        # move the whole take later (+) / earlier (-)
    gain_db: float = 0.0
    mute: bool = False
    mirror: bool = False
    voice: dict = field(default_factory=dict)   # {} | {"kind": "preset", "name", "path"} | {"kind": "custom"}
    note: str = ""


@dataclass
class Project:
    folder: str
    name: str = "Untitled"
    template: str = "03-fourths"
    texts: dict = field(default_factory=dict)    # region id -> text
    takes: list[Take] = field(default_factory=list)

    # ---- files
    @property
    def json_path(self) -> str:
        return os.path.join(self.folder, "project.json")

    def path(self, *parts) -> str:
        return os.path.join(self.folder, *parts)

    def video(self, t: Take) -> str:
        return self.path("takes", t.id + ".mp4")

    def proxy(self, t: Take) -> str:
        return self.path("takes", "proxy", t.id + ".mp4")

    def preview_video(self, t: Take) -> str:
        """The small proxy if it's been made, else the full take."""
        p = self.proxy(t)
        return p if os.path.exists(p) else self.video(t)

    def wav(self, t: Take) -> str:
        return self.path("takes", t.id + ".wav")

    def voice_wav(self, t: Take) -> str:
        return self.path("voices", t.id + ".wav")

    def voice_settings(self, t: Take) -> str:
        return self.path("voices", t.id + ".voice.json")

    def save(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        d = {"boxapella": 1, "name": self.name, "template": self.template,
             "texts": self.texts, "takes": [asdict(t) for t in self.takes]}
        tmp = self.json_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.json_path)

    # ---- template & slots
    def get_template(self) -> templates.Template:
        try:
            return templates.find(self.template)
        except templates.TemplateError:
            return templates.discover()[0]

    def take(self, tid: str) -> Take | None:
        return next((t for t in self.takes if t.id == tid), None)

    def in_slot(self, sid: str) -> Take | None:
        return next((t for t in self.takes if t.slot == sid), None)

    def shown(self) -> list[Take]:
        """Takes sitting in a slot of the current template."""
        ids = {s.id for s in self.get_template().slots}
        return [t for t in self.takes if t.slot in ids]

    def assign(self, tid: str, sid: str) -> None:
        for t in self.takes:
            if t.slot == sid:
                t.slot = ""
        t = self.take(tid)
        if t:
            t.slot = sid

    def next_id(self) -> str:
        nums = [int(m[1]) for t in self.takes if (m := re.fullmatch(r"take-(\d+)", t.id))]
        os.makedirs(self.path("takes"), exist_ok=True)
        n = max(nums, default=0) + 1
        while os.path.exists(self.path("takes", f"take-{n:03d}.mp4")):
            n += 1
        return f"take-{n:03d}"

    def first_empty_slot(self) -> str:
        tpl = self.get_template()
        for s in tpl.slots:
            if not self.in_slot(s.id):
                return s.id
        return tpl.slots[0].id

    def duration(self, exclude: str = "") -> float:
        """Length of the master timeline (takes in slots, minus `exclude`)."""
        return max((t.offset_ms / 1000 + t.duration for t in self.shown() if t.id != exclude),
                   default=0.0)

    # ---- audio
    def take_audio(self, t: Take) -> np.ndarray:
        """The take's audio as heard: reshaped voice if there is one, else the recording."""
        if t.voice and os.path.exists(self.voice_wav(t)):
            return media.read_wav(self.voice_wav(t))
        return media.read_wav(self.wav(t))

    def mix(self, exclude: str = "", normalise: bool = True) -> np.ndarray:
        """Every shown, unmuted take summed at its offset and gain."""
        parts = []
        for t in self.shown():
            if t.id == exclude or t.mute or not os.path.exists(self.wav(t)):
                continue
            x = self.take_audio(t) * (10 ** (t.gain_db / 20))
            off = round(t.offset_ms / 1000 * media.RATE)
            x = x[-off:] if off < 0 else np.concatenate([np.zeros(off, np.float32), x])
            parts.append(x)
        n = max((len(p) for p in parts), default=0)
        out = np.zeros(n, np.float32)
        for p in parts:
            out[: len(p)] += p
        peak = float(np.abs(out).max()) if n else 0.0
        if normalise and peak > 0.98:
            out *= 0.98 / peak
        return out


def load(folder: str) -> Project:
    p = os.path.join(folder, "project.json") if os.path.isdir(folder) else folder
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    keys = Take.__dataclass_fields__.keys()
    takes = [Take(**{k: v for k, v in t.items() if k in keys}) for t in d.get("takes", [])]
    return Project(os.path.dirname(os.path.abspath(p)), d.get("name", "Untitled"),
                   d.get("template", "03-fourths"), d.get("texts", {}), takes)


def create(name: str, template: str, parent: str = PROJECTS_DIR) -> Project:
    safe = re.sub(r"[^\w .-]+", "", name).strip() or "Untitled"
    folder, n = os.path.join(parent, safe), 2
    while os.path.exists(folder):
        folder, n = os.path.join(parent, f"{safe} {n}"), n + 1
    pr = Project(folder, name, template)
    for sub in ("takes", "voices", "exports"):
        os.makedirs(pr.path(sub), exist_ok=True)
    pr.save()
    return pr


def import_video(pr: Project, src: str, slot: str = "", progress=None) -> Take:
    """Copy a video file into the project as a new take (re-encoded to 30 fps H.264 + AAC)."""
    info = media.probe(src)
    if not info["video"]:
        raise media.MediaError(f"{os.path.basename(src)} has no video.")
    tid = pr.next_id()
    t = Take(tid, slot=slot, note=os.path.basename(src))
    wav = pr.wav(t)
    if info["audio"]:
        media.extract_audio(src, wav)
    else:
        media.write_wav(wav, np.zeros(round(info["duration"] * media.RATE), np.float32))
    media.run_ffmpeg(["-i", src, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
                      "-vf", f"fps={media.FPS},format=yuv420p", "-c:v", "libx264",
                      "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", pr.video(t)], info["duration"], progress)
    t.duration = media.probe(pr.video(t))["duration"]
    media.make_proxy(pr.video(t), pr.proxy(t))
    pr.takes.append(t)
    if slot:
        pr.assign(tid, slot)
    pr.save()
    return t
