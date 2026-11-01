"""Recording a take: camera + microphone, with the other takes in the headphones.

Timing.  Everything is measured on the monotonic clock:
  * the camera's frames carry kernel timestamps on that clock (ffmpeg -copyts);
  * the mic reader notes when its first sample was taken;
  * the backing (count-in + mix of the other takes) is launched at play_t,
    so the backing's time 0 is `zero = play_t + count_in`.
The take is cut so that its time 0 is `zero`, plus the latency setting L
(sound out to the headphones + sound in from the mic, found by Calibrate),
so whatever you sang in time with what you heard lines up with it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import numpy as np

from . import media
from .project import Project, Take

PRE_ROLL = 0.4          # s of silence before the count-in


def click(freq: float = 1500, ms: float = 35, level: float = 0.6) -> np.ndarray:
    n = round(media.RATE * ms / 1000)
    t = np.arange(n) / media.RATE
    return (level * np.sin(2 * np.pi * freq * t) * np.exp(-t * 90)).astype(np.float32)


def click_track(seconds: float, bpm: float, start: float = 0.0, beats_per_bar: int = 4,
                level: float = 0.5) -> np.ndarray:
    """Clicks every beat from `start` (accent on each bar's first beat)."""
    out = np.zeros(max(0, round(seconds * media.RATE)), np.float32)
    beat, k = 60.0 / max(20.0, bpm), 0
    hi, lo = click(2000, level=level), click(1300, level=level * 0.8)
    while start + k * beat < seconds:
        c = hi if k % beats_per_bar == 0 else lo
        i = round((start + k * beat) * media.RATE)
        seg = out[i:i + len(c)]
        seg += c[: len(seg)]
        k += 1
    return out


class Session:
    """One take being recorded into `slot`."""

    def __init__(self, pr: Project, slot: str, cam: dict | None, cfg: dict,
                 preview_size: tuple[int, int], mirror: bool, on_preview):
        self.pr, self.slot, self.cam, self.cfg = pr, slot, cam, cfg
        self.mirror = mirror
        self.tid = pr.next_id()
        self.tmp = pr.path("takes", f".rec-{self.tid}")
        os.makedirs(self.tmp, exist_ok=True)
        self.cap = os.path.join(self.tmp, "camera.mkv")
        self.pw, self.ph = (max(2, v // 2 * 2) for v in preview_size)
        self.on_preview = on_preview
        self.cam_proc: subprocess.Popen | None = None
        self.first_frame: float | None = None
        self.mic, self.player = media.duplex(cfg.get("mic_target", ""))
        self.wall_minus_mono = time.time() - time.monotonic()
        self.count_in = 0.0
        self.zero = 0.0
        self.samples: np.ndarray | None = None
        self.cam_error = ""
        self.camera_fps = 0.0

    # ---- 1. arm: camera and mic running, nothing recorded for keeps yet
    def arm(self) -> None:
        vf = media.cover_filter(self.pw, self.ph, self.mirror, fps=False)
        cmd = [media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"] + \
            media.camera_input(self.cam) + [
            "-map", "0:v"] + self._codec() + [self.cap,
            "-map", "0:v", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.cam_proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, **media._kw())
        threading.Thread(target=self._preview, daemon=True).start()
        self.mic.start()

    def _codec(self) -> list[str]:
        """MJPEG cameras are stored as they come; others are compressed on the fly."""
        if self._real() and self.cam.get("format") == "mjpeg":
            return ["-c:v", "copy"]
        if not self._real():
            return ["-c:v", "mjpeg"]
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]

    def _real(self) -> bool:
        return bool(self.cam) and self.cam.get("device") != media.TEST_CAMERA

    def _preview(self) -> None:
        size = self.pw * self.ph * 3
        while True:
            buf = self.cam_proc.stdout.read(size)
            if len(buf) < size:
                break
            if self.first_frame is None:
                self.first_frame = time.monotonic()
            self.on_preview(buf, self.pw, self.ph)
        if self.cam_proc.poll() not in (None, 0) and self.first_frame is None:
            self.cam_error = self.cam_proc.stderr.read().decode(errors="replace").strip()[-600:]

    def ready(self) -> bool:
        return self.first_frame is not None and self.mic.start_time is not None

    def failed(self) -> str:
        if self.cam_proc and self.cam_proc.poll() is not None and self.first_frame is None:
            return self.cam_error or "The camera stopped before sending a picture."
        if getattr(self.mic, "error", ""):
            return self.mic.error
        if self.mic.proc and self.mic.proc.poll() is not None and self.mic.start_time is None:
            return "The microphone recorder stopped before sending any sound."
        return ""

    # ---- 2. go: count-in and backing into the headphones
    def go(self) -> float:
        """Start the backing; returns `zero` (monotonic time of the backing's t=0)."""
        bpm = float(self.cfg.get("bpm", 90))
        beats = int(self.cfg.get("count_in", 4))
        self.count_in = beats * 60.0 / bpm if beats > 0 else 0.5
        backing = self.pr.mix(exclude=self._replacing())
        lead = click_track(self.count_in, bpm, 0.0, max(1, beats)) if beats > 0 else \
            np.zeros(round(self.count_in * media.RATE), np.float32)
        body = backing * float(self.cfg.get("backing_level", 1.0))
        if self.cfg.get("metronome"):           # clicks for up to 10 minutes, past the backing too
            met = click_track(600.0, bpm, 0.0, max(1, beats or 4), level=0.35)
            body = np.pad(body, (0, max(0, len(met) - len(body))))
            body[: len(met)] += met
        # a moment of silence first, so a sound device waking up doesn't stutter the count-in
        quiet = np.zeros(round(PRE_ROLL * media.RATE), np.float32)
        wav = os.path.join(self.tmp, "backing.wav")
        media.write_wav(wav, np.clip(np.concatenate([quiet, lead, body]), -1, 1))
        self.player.play(wav)
        self.zero = self.player.started + PRE_ROLL + self.count_in
        return self.zero

    def _replacing(self) -> str:
        t = self.pr.in_slot(self.slot)
        return t.id if t else ""

    # ---- 3. stop
    def stop(self) -> None:
        """Stop the backing and the mic now; the camera keeps going until
        stop_camera() so frames still on their way (cameras lag) aren't lost."""
        self.player.stop()
        self.samples = self.mic.stop()
        self.stopped_at = time.monotonic()

    def stop_camera(self, grace: float = 0.0) -> None:
        if grace > 0:
            time.sleep(max(0.0, grace - (time.monotonic() - getattr(self, "stopped_at", 0.0))))
        if self.cam_proc and self.cam_proc.poll() is None:
            try:
                self.cam_proc.stdin.write(b"q")
                self.cam_proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.cam_proc.wait(8)
            except subprocess.TimeoutExpired:
                self.cam_proc.kill()

    def cancel(self) -> None:
        self.stop()
        self.stop_camera()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 4. finalize: cut both to the backing's t=0 and save take-NNN.mp4/.wav
    def finalize(self, progress=None) -> Take:
        self.stop_camera(grace=0.8)
        L = float(self.cfg.get("latency_ms", 0)) / 1000
        V = float(self.cfg.get("video_offset_ms", 0)) / 1000
        x = self.samples if self.samples is not None else np.zeros(0, np.float32)
        a0 = round((self.zero - self.mic.start_time + L) * media.RATE)
        x = x[a0:] if a0 >= 0 else np.concatenate([np.zeros(-a0, np.float32), x])
        if len(x) < media.RATE // 4:
            raise media.MediaError("The take is too short (stopped during the count-in?).")
        info = media.probe(self.cap)
        self.camera_fps = media.frame_rate(self.cap) if self._real() else float(media.FPS)
        clock = media.camera_clock(self.cam)
        if clock == "mono":
            vstart = info["start"]
        elif clock == "wall":                  # DirectShow: wall-clock arrival stamps
            vstart = info["start"] - self.wall_minus_mono
        else:
            vstart = self.first_frame - 1.0 / media.FPS
        v0 = self.zero - vstart + L + V
        take = Take(self.tid, slot=self.slot, mirror=self.mirror)
        wav = self.pr.wav(take)
        media.write_wav(wav, x)
        seek = ["-ss", f"{v0:.3f}"] if v0 > 0 else []
        secs = len(x) / media.RATE
        # The picture is held on its last frame if it falls short of the sound
        # (slow cameras deliver their final frames late), then both are cut to the sound.
        media.run_ffmpeg(seek + ["-i", self.cap, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
                                 "-vf", f"fps={media.FPS},tpad=stop_mode=clone:stop_duration=5,format=yuv420p",
                                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                 "-c:a", "aac", "-b:a", "192k", "-t", f"{secs:.3f}",
                                 "-movflags", "+faststart", self.pr.video(take)],
                         secs, progress)
        take.duration = media.probe(self.pr.video(take))["duration"]
        media.make_proxy(self.pr.video(take), self.pr.proxy(take))
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.pr.takes.append(take)
        self.pr.assign(take.id, self.slot)
        self.pr.save()
        return take


# ---------------------------------------------------------------- latency
GAPS = (0.45, 0.62, 0.38, 0.71, 0.50, 0.41, 0.66, 0.55)   # uneven, so a lag of one click can't match


def calibrate(mic_target: str = "") -> tuple[float, float]:
    """Play clicks through the speakers, hear them in the mic -> (latency ms, confidence).

    Uses the same start-time bookkeeping as a real take, so the result is the
    L to put in the latency setting.  Needs speakers (not headphones) and quiet.
    """
    mic, player = media.duplex(mic_target)
    mic.start()
    t_end = time.monotonic() + 5
    while mic.start_time is None and time.monotonic() < t_end:
        time.sleep(0.02)
    if mic.start_time is None:
        mic.stop()
        raise media.MediaError("No sound arrived from the microphone.")
    lead = 0.6
    times = [lead + sum(GAPS[:k]) for k in range(len(GAPS))]
    sig = np.zeros(round((times[-1] + 2.0) * media.RATE), np.float32)
    c = click(2500, 12, 0.9)
    for t in times:
        i = round(t * media.RATE)
        sig[i:i + len(c)] += c
    import tempfile
    fd, wav = tempfile.mkstemp(suffix=".wav", prefix="boxapella-cal-")
    os.close(fd)
    media.write_wav(wav, sig)
    time.sleep(0.3)
    player.play(wav)
    time.sleep(len(sig) / media.RATE + 0.3)
    player.stop()
    x = mic.stop()
    os.remove(wav)
    return detect_latency(x, mic.start_time, player.started, times)


def detect_latency(x: np.ndarray, mic_start: float, play_t: float,
                   times: list[float]) -> tuple[float, float]:
    """Find L (s) such that clicks sit at (play_t + t - mic_start + L) in x."""
    env = np.abs(x - np.convolve(x, np.ones(48) / 48, "same"))       # strip rumble
    env = np.convolve(env, np.ones(96) / 96, "same")
    base = np.array([(play_t + t - mic_start) * media.RATE for t in times])
    lags = np.arange(round(-0.1 * media.RATE), round(1.5 * media.RATE), 12)
    idx = (base[None, :] + lags[:, None]).astype(int)
    ok = (idx >= 0) & (idx < len(env))
    score = np.where(ok, env[np.clip(idx, 0, len(env) - 1)], 0).sum(axis=1)
    best = int(np.argmax(score))
    conf = float(score[best] / (np.median(score) + 1e-9))
    return float(lags[best]) / media.RATE * 1000, conf
