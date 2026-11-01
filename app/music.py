"""Music for an inset: an audio or MIDI file plus a still picture, lined up with the singing.

* Audio files (WAV, MP3, FLAC, ...) are decoded with ffmpeg.  MIDI files are
  rendered with FluidSynth: the `fluidsynth` program and a General MIDI
  SoundFont (on Windows the copy that Lorenzo's PlugPlay downloads is found too).
* Lining up: the music's chroma (how strongly each of the 12 pitch classes
  sounds, frame by frame) is cross-correlated with the chroma of the singing
  already in the other insets.  The best match gives one constant offset, so it
  assumes the singing kept the music's tempo (e.g. it was sung along to it).
* The picture is fitted, not cropped, onto a 1280 x 720 frame (letterboxed on the
  template background colour); without a picture the frame is plain.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile

import numpy as np

from . import config, media, project

AUDIO_EXTS = (".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma", ".aif", ".aiff")
MIDI_EXTS = (".mid", ".midi", ".kar")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
SIZE = (1280, 720)
HOP = 480                       # chroma frame: 10 ms at RATE
MIN_CONFIDENCE = 1.3            # best match / best match elsewhere, below = not lined up

SOUNDFONTS = ["/usr/share/sounds/sf2/FluidR3_GM.sf2", "/usr/share/sounds/sf2/default-GM.sf2",
              "/usr/share/soundfonts/default.sf2", "/usr/share/soundfonts/FluidR3_GM.sf2",
              "/usr/share/sounds/sf2/TimGM6mb.sf2"]


# ---------------------------------------------------------------- MIDI
def find_synth() -> tuple[str, str]:
    """(fluidsynth program, SoundFont) for rendering MIDI, or MediaError saying what's missing.
    Settings keys "fluidsynth" and "soundfont" override the search."""
    cfg = config.load()
    lorenzo = os.path.join(os.environ.get("LOCALAPPDATA", ""), "lorenzo-suite", "synth")
    exe = cfg.get("fluidsynth") or shutil.which("fluidsynth")
    if not exe and media.WINDOWS:
        found = sorted(glob.glob(os.path.join(lorenzo, "fluidsynth-*", "**", "fluidsynth.exe"), recursive=True))
        exe = found[-1] if found else ""
    sf2 = cfg.get("soundfont") or ""
    if not sf2:
        cands = SOUNDFONTS + sorted(glob.glob(os.path.join(lorenzo, "*.sf2")))
        sf2 = next((p for p in cands if os.path.exists(p)), "")
    if not exe or not sf2:
        how = ("Install FluidSynth (sudo apt install fluidsynth fluid-soundfont-gm)" if not media.WINDOWS else
               "Run `plugplay get-synth` (Lorenzo suite), or install FluidSynth and a General MIDI .sf2")
        missing = "the fluidsynth program" if not exe else "a General MIDI SoundFont (.sf2)"
        raise media.MediaError(f"Playing MIDI needs {missing}. {how}, or set \"fluidsynth\" / "
                               f"\"soundfont\" in {config.PATH}.")
    return exe, sf2


def render_midi(src: str, out_wav: str) -> None:
    exe, sf2 = find_synth()
    p = subprocess.run([exe, "-ni", "-q", "-r", str(media.RATE), "-g", "0.8", "-F", out_wav, sf2, src],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", **media._kw())
    if p.returncode != 0 or not os.path.exists(out_wav):
        raise media.MediaError("FluidSynth couldn't render the MIDI file: "
                               + ((p.stderr or p.stdout).strip()[-400:] or f"exit {p.returncode}"))


def load_music(src: str, tmp: str) -> np.ndarray:
    """The music as mono samples at RATE."""
    wav = os.path.join(tmp, "music.wav")
    if src.lower().endswith(MIDI_EXTS):
        render_midi(src, wav)
    else:
        media.extract_audio(src, wav)
    return media.read_wav(wav)


# ---------------------------------------------------------------- lining up
def chroma(x: np.ndarray) -> np.ndarray:
    """Unit-length 12-bin chroma per HOP, with silent frames zeroed."""
    x, fs, hop, n = x[::2], media.RATE // 2, HOP // 2, 2048         # 24 kHz is plenty
    frames = 1 + (len(x) - n) // hop
    if frames < 1:
        return np.zeros((0, 12))
    f = np.fft.rfftfreq(n, 1 / fs)
    band = (f >= 80) & (f <= 2000)
    pc = (np.round(12 * np.log2(f[band] / 440) + 69) % 12).astype(int)
    out = np.zeros((frames, 12))
    win = np.hanning(n)
    for a in range(0, frames, 2000):                                # in blocks, to keep memory low
        idx = np.arange(n)[None, :] + hop * np.arange(a, min(frames, a + 2000))[:, None]
        spec = np.abs(np.fft.rfft(x[idx] * win, axis=1))[:, band]
        for k in range(12):
            out[a:a + len(idx), k] = spec[:, pc == k].sum(1)
    out = np.log1p(100 * out / (out.max() + 1e-9))
    out -= out.mean(1, keepdims=True)                               # which notes stand out, not timbre
    norm = np.linalg.norm(out, axis=1, keepdims=True)
    loud = norm[:, 0] > 0.1 * np.median(norm[norm[:, 0] > 0]) if (norm > 0).any() else norm[:, 0] > 0
    return np.where(loud[:, None], out / (norm + 1e-9), 0.0)


def find_offset(music: np.ndarray, singing: np.ndarray) -> tuple[float, float]:
    """(seconds the music runs ahead of the singing, confidence).

    A positive offset means the singing starts that far into the music, so that
    much is cut from the music's start; negative means the music starts later.
    Confidence is the best match over the best match more than a second away."""
    a, b = chroma(singing), chroma(music)
    if not len(a) or not len(b) or not a.any() or not b.any():
        return 0.0, 0.0
    size = 1 << (len(a) + len(b) - 1).bit_length()
    xc = sum(np.fft.irfft(np.fft.rfft(b[:, k], size) * np.conj(np.fft.rfft(a[:, k], size)), size)
             for k in range(12))
    lags = np.r_[np.arange(len(b)), np.arange(-len(a) + 1, 0)]
    vals = np.r_[xc[:len(b)], xc[size - len(a) + 1:]]
    best = int(np.argmax(vals))
    frac = 0.0
    if 0 < best < len(vals) - 1 and lags[best - 1] + 1 == lags[best] == lags[best + 1] - 1:
        y0, y1, y2 = vals[best - 1], vals[best], vals[best + 1]
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den else 0.0
    away = vals[np.abs(lags - lags[best]) > media.RATE // HOP]
    second = float(away.max()) if len(away) else 0.0
    conf = float(vals[best] / second) if second > 0 else float("inf")
    return (lags[best] + frac) * HOP / media.RATE, conf


def shift(music: np.ndarray, offset: float) -> np.ndarray:
    """Cut `offset` seconds from the start (or add silence in front if negative)."""
    n = round(offset * media.RATE)
    return music[n:] if n >= 0 else np.concatenate([np.zeros(-n, np.float32), music])


# ---------------------------------------------------------------- picture video
def make_video(image: str, wav: str, out: str, background: str = "#111116", progress=None) -> None:
    """A still picture (or a plain frame) for as long as the audio, as H.264 + AAC."""
    w, h = SIZE
    colour = "0x" + background.lstrip("#")[:6]
    src = (["-loop", "1", "-framerate", str(media.FPS), "-i", image] if image else
           ["-f", "lavfi", "-i", f"color=c={colour}:s={w}x{h}:r={media.FPS}"])
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={colour},") if image else ""
    secs = len(media.read_wav(wav)) / media.RATE        # exact: -shortest overshoots with a looped picture
    media.run_ffmpeg(src + ["-i", wav, "-map", "0:v", "-map", "1:a",
                            "-vf", f"{fit}fps={media.FPS},format=yuv420p", "-c:v", "libx264",
                            "-tune", "stillimage", "-preset", "veryfast", "-crf", "20",
                            "-c:a", "aac", "-b:a", "192k", "-t", f"{secs:.3f}", "-movflags", "+faststart", out],
                     secs, progress)


# ---------------------------------------------------------------- all together
def import_music(pr: project.Project, src: str, slot: str, image: str = "", line_up: bool = True,
                 progress=None) -> tuple[project.Take, float | None, float]:
    """Put `src` (audio or MIDI) with `image` into `slot` as a new take.

    Returns (take, offset applied or None if not lined up, confidence)."""
    step = (lambda a, b: (lambda f: progress(a + (b - a) * f))) if progress else (lambda a, b: None)
    old = pr.in_slot(slot)
    with tempfile.TemporaryDirectory(prefix="boxapella-music-") as tmp:
        if progress:
            progress(0.02)
        music = load_music(src, tmp)
        if not len(music):
            raise media.MediaError(f"{os.path.basename(src)} has no sound.")
        offset, conf = None, 0.0
        if line_up:
            singing = pr.mix(exclude=old.id if old else "", normalise=False)
            if len(singing):
                best, conf = find_offset(music, singing)
                if conf >= MIN_CONFIDENCE:
                    offset = best
                    music = shift(music, best)
        if progress:
            progress(0.2)
        peak = float(np.abs(music).max()) if len(music) else 0.0
        if peak > 0.98:
            music = music * (0.98 / peak)
        wav, mp4 = os.path.join(tmp, "music-placed.wav"), os.path.join(tmp, "music.mp4")
        media.write_wav(wav, music)
        make_video(image, wav, mp4, pr.get_template().background, step(0.2, 0.55))
        t = project.import_video(pr, mp4, slot, step(0.55, 1.0))
    t.note = os.path.basename(src) + (f" + {os.path.basename(image)}" if image else "")
    t.mirror = False
    pr.save()
    return t, offset, conf
