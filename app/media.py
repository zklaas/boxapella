"""ffmpeg, WAV and device helpers.

ffmpeg is the binary bundled with the imageio-ffmpeg package in .venv (it can
capture from Video4Linux cameras on Linux and DirectShow cameras on Windows),
or a system ffmpeg if that's missing.
Audio: on Linux PipeWire's pw-record / pw-play; on Windows and macOS one
full-duplex PortAudio stream (the sounddevice package), so the headphones and the
mic share a sample clock.
Cameras: Video4Linux on Linux, DirectShow on Windows, AVFoundation on macOS.
"""
from __future__ import annotations

import glob
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave

import numpy as np

FPS = 30
RATE = 48000
TEST_CAMERA = "test"          # pseudo-device: ffmpeg's test pattern
WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"
PORTAUDIO = WINDOWS or MACOS      # no PipeWire: audio through sounddevice


def _kw(low: bool = False) -> dict:
    """subprocess options: no console windows on Windows; optionally low CPU priority."""
    if WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW
        if low:
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return {"creationflags": flags}
    return {"preexec_fn": _low_priority} if low else {}


def _low_priority():
    """preexec_fn (Linux): video decoding yields the CPU to audio playback."""
    try:
        os.nice(10)
    except OSError:
        pass


class MediaError(Exception):
    pass


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:            # noqa: BLE001 - fall back to the system's
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise MediaError("No ffmpeg found. Run ./install.sh (installs imageio-ffmpeg into .venv).")


def run_ffmpeg(args: list[str], duration: float = 0.0, progress=None) -> None:
    """Run ffmpeg with args; progress(fraction) is called as it goes."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    if progress and duration > 0:
        cmd += ["-progress", "pipe:1", "-nostats"]
    err: list[str] = []
    with subprocess.Popen(cmd + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          encoding="utf-8", errors="replace", **_kw()) as p:
        t = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True)
        t.start()
        for line in p.stdout:
            if progress and duration > 0 and line.startswith("out_time_us="):
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
                except ValueError:
                    pass
        p.wait()
        t.join(1)
    if p.returncode != 0:
        raise MediaError("".join(err).strip()[-1500:] or f"ffmpeg failed ({p.returncode})")


def probe(path: str) -> dict:
    """Duration, size, fps, start time and audio presence, from `ffmpeg -i`."""
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", **_kw()).stderr
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": float(FPS),
            "start": 0.0, "audio": " Audio: " in out, "video": " Video: " in out}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"start: (-?[\d.]+)", out)
    if m:
        info["start"] = float(m[1])
    m = re.search(r"Video: .*?, (\d{2,5})x(\d{2,5})", out)
    if m:
        info["width"], info["height"] = int(m[1]), int(m[2])
    m = re.search(r"([\d.]+) fps", out)
    if m:
        info["fps"] = float(m[1])
    if not info["video"] and not info["audio"]:
        raise MediaError(f"Not a media file ffmpeg can read: {path}")
    return info


# ---------------------------------------------------------------- WAV
def read_wav(path: str) -> np.ndarray:
    """Mono float32 samples at RATE (other rates are resampled)."""
    with wave.open(path, "rb") as w:
        ch, width, fs, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2 ** 31
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = (np.where(v >= 1 << 23, v - (1 << 24), v) / (1 << 23)).astype(np.float32)
    else:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    if ch > 1:
        x = x[: len(x) - len(x) % ch].reshape(-1, ch).mean(axis=1)
    if fs != RATE and len(x) > 1:
        m = max(1, round(len(x) * RATE / fs))
        x = np.interp(np.arange(m) * fs / RATE, np.arange(len(x)), x).astype(np.float32)
    return x


def write_wav(path: str, y: np.ndarray, fs: int = RATE) -> None:
    pcm = np.clip(np.round(np.asarray(y) * 32767), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(fs))
        w.writeframes(pcm.tobytes())


def extract_audio(src: str, out_wav: str) -> None:
    run_ffmpeg(["-i", src, "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", out_wav])


# ---------------------------------------------------------------- cameras
def _formats(dev: str) -> list[tuple[str, list[str]]]:
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-f", "v4l2", "-list_formats", "all",
                          "-i", dev], capture_output=True, text=True, timeout=10, **_kw()).stderr
    fmts = []
    for line in out.splitlines():
        m = re.search(r"(Raw|Compressed)\s*:\s*(\S+)\s*:.*?:\s*(.*)$", line)
        if m:
            fmts.append((m[2], m[3].split()))
    return fmts


def _dshow(args: list[str]) -> str:
    return subprocess.run([ffmpeg_exe(), "-hide_banner", "-f", "dshow"] + args, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=15, **_kw()).stderr


def parse_dshow_devices(text: str) -> list[str]:
    """Video device names from `ffmpeg -list_devices true -f dshow -i dummy`."""
    return [m[1] for m in re.finditer(r'"([^"]+)"\s+\(video\)', text)]


def parse_dshow_options(text: str) -> dict | None:
    """The format to ask a DirectShow camera for, from `-list_options true`:
    MJPEG at the largest size up to 1080p that reaches 25 fps, else raw up to 720p."""
    modes = []
    for m in re.finditer(r"(vcodec|pixel_format)=(\S+)\s+min s=\d+x\d+ fps=[\d.]+\s+"
                         r"max s=(\d+)x(\d+) fps=([\d.]+)", text):
        modes.append((m[1], m[2], int(m[3]), int(m[4]), float(m[5])))

    def best(ok):
        ok = [x for x in ok if x[4] >= 25]
        return max(ok, key=lambda x: x[2] * x[3]) if ok else None
    pick = best([x for x in modes if x[1] == "mjpeg" and x[2] <= 1920]) or \
        best([x for x in modes if x[0] == "pixel_format" and x[2] <= 1280]) or \
        (max(modes, key=lambda x: x[2] * x[3]) if modes else None)
    if not pick:
        return None
    return {"kind": pick[0], "format": pick[1], "size": f"{pick[2]}x{pick[3]}"}


def _cameras_windows() -> list[dict]:
    found = []
    try:
        names = parse_dshow_devices(_dshow(["-list_devices", "true", "-i", "dummy"]))
    except (subprocess.SubprocessError, OSError):
        return found
    for name in names:
        try:
            opt = parse_dshow_options(_dshow(["-list_options", "true", "-i", f"video={name}"]))
        except (subprocess.SubprocessError, OSError):
            continue
        if opt:
            found.append({"device": f"video={name}", "name": name, "api": "dshow", **opt})
    return found


def parse_avfoundation_devices(text: str) -> list[tuple[str, str]]:
    """(index, name) of the video devices in `ffmpeg -f avfoundation
    -list_devices true -i ""` output (the part before the audio devices).
    Screen-capture entries ("Capture screen 0") are left out."""
    out, video = [], False
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            video = True
            continue
        if "AVFoundation audio devices" in line:
            break
        m = re.search(r"\]\s*\[(\d+)\]\s*(.+?)\s*$", line)
        if video and m and not m[2].lower().startswith("capture screen"):
            out.append((m[1], m[2]))
    return out


def _cameras_macos() -> list[dict]:
    """AVFoundation cameras.  macOS asks for camera permission the first time;
    ffmpeg then lets AVFoundation pick the pixel format at 1280x720."""
    try:
        text = subprocess.run([ffmpeg_exe(), "-hide_banner", "-f", "avfoundation",
                               "-list_devices", "true", "-i", ""], capture_output=True,
                              text=True, errors="replace", timeout=15).stderr
    except (subprocess.SubprocessError, OSError):
        return []
    return [{"device": f"{idx}:none", "name": name, "api": "avfoundation",
             "format": "", "size": "1280x720"} for idx, name in parse_avfoundation_devices(text)]


def cameras() -> list[dict]:
    """Usable cameras with the input format and size to ask for."""
    if WINDOWS:
        return _cameras_windows()
    if MACOS:
        return _cameras_macos()
    found = []
    for dev in sorted(glob.glob("/dev/video*")):
        try:
            fmts = _formats(dev)
        except (subprocess.SubprocessError, OSError, MediaError):
            continue
        if not fmts:
            continue                       # metadata-only node
        name = dev
        try:
            with open(f"/sys/class/video4linux/{os.path.basename(dev)}/name") as f:
                name = f.read().strip()
        except OSError:
            pass

        def best(sizes, cap):
            ok = [s for s in sizes if re.fullmatch(r"\d+x\d+", s) and int(s.split("x")[0]) <= cap]
            return max(ok, key=lambda s: int(s.split("x")[0]) * int(s.split("x")[1])) if ok else None
        pick = None
        for fmt, sizes in fmts:            # compressed first: raw 1080p rarely reaches 30 fps
            if fmt == "mjpeg" and best(sizes, 1920):
                pick = (fmt, best(sizes, 1920))
        if not pick:
            for fmt, sizes in fmts:
                if best(sizes, 1280):
                    pick = (fmt, best(sizes, 1280))
                    break
        if pick:
            found.append({"device": dev, "name": name, "format": pick[0], "size": pick[1]})
    return found


def frame_rate(path: str) -> float:
    """Distinct frames per second actually stored in a capture (packets / time span)."""
    out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", path,
                          "-map", "0:v:0", "-c", "copy", "-f", "framecrc", "-"],
                         capture_output=True, text=True, **_kw()).stdout
    rows = [r.split(",") for r in out.splitlines() if r and not r.startswith("#")]
    if len(rows) < 2:
        return 0.0
    tb = 1000.0
    for line in out.splitlines():
        if line.startswith("#tb 0:"):
            num, den = line.split(":")[1].strip().split("/")
            tb = int(den) / int(num)
    span = (int(rows[-1][1]) - int(rows[0][1])) / tb
    return (len(rows) - 1) / span if span > 0 else 0.0


def measure_camera(cam: dict, seconds: float = 3.0) -> float:
    """Record a few seconds and return the frame rate the camera really delivers."""
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".mkv", prefix="boxapella-fps-")
    os.close(fd)
    try:
        p = subprocess.Popen([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
                             + camera_input(cam) + ["-map", "0:v", "-c", "copy", tmp],
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             **_kw())
        time.sleep(seconds + 1.0)
        p.communicate(b"q", timeout=10)
        return frame_rate(tmp)
    finally:
        os.remove(tmp)


def camera_clock(cam: dict | None) -> str:
    """Which clock a camera's capture timestamps are on: "mono" (Video4Linux kernel
    timestamps = time.monotonic()), "wall" (DirectShow and AVFoundation, stamped on
    arrival with the wall clock = time.time()) or "none" (test pattern)."""
    if not cam or cam.get("device") == TEST_CAMERA:
        return "none"
    return "wall" if cam.get("api") in ("dshow", "avfoundation") else "mono"


def camera_input(cam: dict | None) -> list[str]:
    """ffmpeg input arguments for a camera from cameras() (None = test pattern).

    Real cameras keep their timestamps (-copyts) on the clock camera_clock()
    names: that is how takes line up.
    """
    if not cam or cam.get("device") == TEST_CAMERA:
        return ["-re", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate={FPS}"]
    if cam.get("api") == "avfoundation":
        return ["-f", "avfoundation", "-use_wallclock_as_timestamps", "1",
                "-video_size", cam["size"], "-framerate", str(FPS), "-i", cam["device"], "-copyts"]
    if cam.get("api") == "dshow":
        fmt = ["-vcodec", "mjpeg"] if cam.get("kind") == "vcodec" else ["-pixel_format", cam["format"]]
        return ["-f", "dshow", "-rtbufsize", "512M", "-use_wallclock_as_timestamps", "1"] + fmt + [
            "-video_size", cam["size"], "-framerate", str(FPS), "-i", cam["device"], "-copyts"]
    return ["-f", "v4l2", "-input_format", cam["format"], "-video_size", cam["size"],
            "-framerate", str(FPS), "-i", cam["device"], "-copyts"]


# ---------------------------------------------------------------- audio devices
class MicReader:
    """pw-record streaming raw s16 mono to us; knows when its first sample was taken."""

    def __init__(self, target: str = ""):
        self.target = target
        self.proc: subprocess.Popen | None = None
        self.chunks: list[bytes] = []
        self.start_time: float | None = None    # monotonic time of the first sample
        self._got = 0                           # bytes received
        self.level = 0.0
        self._t: threading.Thread | None = None

    def start(self) -> None:
        if not shutil.which("pw-record"):
            raise MediaError("pw-record (PipeWire) is needed to record audio.")
        cmd = ["pw-record", "--raw", "--rate", str(RATE), "--channels", "1",
               "--format", "s16", "--latency", "20ms"]
        if self.target:
            cmd += ["--target", self.target]
        self.proc = subprocess.Popen(cmd + ["-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.error = ""
        self._t = threading.Thread(target=self._read, daemon=True)
        self._t.start()

    def _read(self) -> None:
        out = self.proc.stdout
        while True:
            b = out.read1(16384)
            if not b:
                break
            # When was the first sample taken?  Each chunk says "at most now minus
            # everything received so far"; chunks arrive late by varying amounts
            # (a VM's mic is bursty), so the earliest such bound is the best guess.
            # Only the first few seconds count, so clock drift can't creep in.
            self._got += len(b)
            est = time.monotonic() - self._got / 2 / RATE
            if self.start_time is None:
                self.start_time = est
            elif self._got < 5 * RATE * 2:
                self.start_time = min(self.start_time, est)
            self.chunks.append(b)
            a = np.frombuffer(b[: len(b) - len(b) % 2], "<i2")
            if len(a):
                self.level = max(self.level * 0.6, float(np.abs(a).max()) / 32768)

    def stop(self, wait: float = 0.6) -> np.ndarray:
        """Samples from start_time up to now.  The mic delivers in bursts (in a VM
        up to ~0.1 s behind), so wait up to `wait` s for it to catch up to the
        moment of stopping, then cut to exactly that length."""
        t_stop = time.monotonic()
        if self.start_time is not None:
            want = int((t_stop - self.start_time) * RATE) * 2
            give_up = t_stop + wait
            while sum(map(len, self.chunks)) < want and time.monotonic() < give_up \
                    and self.proc and self.proc.poll() is None:
                time.sleep(0.01)
        else:
            want = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._t:
            self._t.join(2)
        raw = b"".join(self.chunks)
        if want is not None:
            raw = raw[:want]
        return np.frombuffer(raw[: len(raw) - len(raw) % 2], "<i2").astype(np.float32) / 32768


class Player:
    """pw-play a WAV; started() is the monotonic time it was launched."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.started = 0.0

    def play(self, path: str) -> None:
        self.stop()
        cmd = next(([c] for c in ("pw-play", "paplay", "aplay") if shutil.which(c)), None)
        if not cmd:
            raise MediaError("No audio player found (pw-play, paplay or aplay).")
        if cmd[0] == "pw-play":
            cmd += ["--latency", "200ms"]      # a deeper buffer rides out busy moments (VMs)
        self.started = time.monotonic()
        self.proc = subprocess.Popen(cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def playing(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.playing():
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


class SoundDeviceIO:
    """Windows: the microphone and the headphones as one full-duplex PortAudio stream.

    Recording runs from start() to stop().  play() queues a buffer that starts in
    the next audio callback, and `started` is then exact on the microphone's
    sample clock (start_time + frames recorded before it), so the backing's
    position in the recording is known to the sample.
    """

    def __init__(self, target: str = ""):
        self.target = target
        self.proc = None                    # MicReader compatibility
        self.error = ""
        self.stream = None
        self.chunks: list[np.ndarray] = []
        self.in_frames = 0
        self.start_time: float | None = None
        self.level = 0.0
        self.lock = threading.Lock()
        self.out: np.ndarray | None = None
        self.out_pos = 0
        self.out_start: int | None = None   # input frame at which playback began
        self.started = 0.0
        self._begun = threading.Event()

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as e:
            raise MediaError("The sounddevice package is needed (run install.ps1 on Windows, install-macos.sh on macOS).") from e
        device = (_input_device(sd, self.target), None)
        last = None
        for ch_out in (2, 1):
            try:
                self.stream = sd.Stream(samplerate=RATE, channels=(1, ch_out), dtype="float32",
                                        device=device, latency="high", callback=self._cb)
                break
            except Exception as e:          # noqa: BLE001 - try mono output, then report
                last = e
        if self.stream is None:
            raise MediaError(f"Could not open the microphone and headphones: {last}")
        self.stream.start()

    def _cb(self, indata, outdata, frames, _time, status) -> None:
        if self.start_time is None:
            self.start_time = time.monotonic() - frames / RATE
        x = np.array(indata[:, 0], dtype=np.float32)
        self.chunks.append(x)
        if len(x):
            self.level = max(self.level * 0.6, float(np.abs(x).max()))
        outdata.fill(0)
        with self.lock:
            if self.out is not None and self.out_pos < len(self.out):
                if self.out_start is None:
                    self.out_start = self.in_frames
                    self._begun.set()
                seg = self.out[self.out_pos:self.out_pos + frames]
                self.out_pos += len(seg)
                outdata[:len(seg)] = seg[:, None]
        self.in_frames += frames

    # -- player role
    def play_buffer(self, y: np.ndarray) -> None:
        with self.lock:
            self.out, self.out_pos, self.out_start = np.asarray(y, np.float32), 0, None
            self._begun.clear()
        if not self._begun.wait(3.0):
            raise MediaError("The headphones didn't start playing.")
        self.started = self.start_time + self.out_start / RATE

    def playing(self) -> bool:
        return self.out is not None and self.out_pos < len(self.out)

    def stop_playback(self) -> None:
        with self.lock:
            self.out = None

    # -- microphone role
    def stop(self, wait: float = 0.0) -> np.ndarray:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:               # noqa: BLE001 - already gone
                pass
            self.stream = None
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)


def _input_device(sd, target: str):
    """A microphone by (part of) its name, or an index; None = the default.

    Windows lists each device once per host API (MME, WASAPI, ...), and a duplex
    stream needs both ends on one API, so take the match on the default API."""
    if not target:
        return None
    if target.isdigit():
        return int(target)
    want = target.lower()
    hits = [i for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0 and want in d["name"].lower()]
    if not hits:
        raise MediaError(f"No microphone matching {target!r} (see `boxapella devices`).")
    default_api = sd.query_devices(kind="output")["hostapi"]
    same = [i for i in hits if sd.query_devices(i)["hostapi"] == default_api]
    return (same or hits)[0]


class _DuplexPlayer:
    """The headphone side of a SoundDeviceIO, shaped like Player."""

    def __init__(self, io: SoundDeviceIO):
        self.io = io

    @property
    def started(self) -> float:
        return self.io.started

    def play(self, path: str) -> None:
        self.io.play_buffer(read_wav(path))

    def playing(self) -> bool:
        return self.io.playing()

    def stop(self) -> None:
        self.io.stop_playback()


class SoundDevicePlayer:
    """Windows playback of a WAV through PortAudio; `started` = its first audio callback."""

    def __init__(self):
        self.stream = None
        self.started = 0.0
        self.y = np.zeros(0, np.float32)
        self.pos = 0
        self._begun = threading.Event()

    def play(self, path: str) -> None:
        self.stop()
        try:
            import sounddevice as sd
        except ImportError as e:
            raise MediaError("The sounddevice package is needed (run install.ps1 on Windows, install-macos.sh on macOS).") from e
        self.y, self.pos = read_wav(path), 0
        self._begun.clear()

        def cb(outdata, frames, _time, status):
            if not self._begun.is_set():
                self.started = time.monotonic()
                self._begun.set()
            seg = self.y[self.pos:self.pos + frames]
            self.pos += len(seg)
            outdata.fill(0)
            outdata[:len(seg)] = seg[:, None]
        self.stream = sd.OutputStream(samplerate=RATE, channels=2, dtype="float32",
                                      latency="high", callback=cb)
        self.stream.start()
        self._begun.wait(3.0)

    def playing(self) -> bool:
        return self.stream is not None and self.pos < len(self.y)

    def stop(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:               # noqa: BLE001
                pass
            self.stream = None


def make_player():
    """Something that plays a WAV file: play(path), started, playing(), stop()."""
    return SoundDevicePlayer() if PORTAUDIO else Player()


def duplex(target: str = ""):
    """(microphone, headphones) for recording against a backing.  On Windows and
    macOS both are one PortAudio stream with a shared clock; on Linux pw-record +
    pw-play."""
    if PORTAUDIO:
        io = SoundDeviceIO(target)
        return io, _DuplexPlayer(io)
    return MicReader(target), Player()


def audio_devices() -> list[str]:
    """Human-readable list of audio inputs/outputs (for `boxapella devices`)."""
    if not PORTAUDIO:
        return ["Linux: PipeWire's default microphone and output (choose them in Settings → Sound);",
                "a specific source can be named in Boxapella's Settings → Timing & devices → Microphone."]
    try:
        import sounddevice as sd
    except ImportError:
        return ["sounddevice isn't installed (run install.ps1 on Windows, install-macos.sh on macOS)."]
    lines = []
    for i, d in enumerate(sd.query_devices()):
        kind = "/".join(k for k, n in (("in", d["max_input_channels"]), ("out", d["max_output_channels"])) if n)
        api = sd.query_hostapis(d["hostapi"])["name"]
        lines.append(f"{i:3d}  {kind:6s} {api:22s} {d['name']}")
    return lines


# ---------------------------------------------------------------- video frames
PROXY_HEIGHT = 540


def make_proxy(src: str, out: str) -> None:
    """A small, quick-to-decode copy of a take for playing in the app."""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out[:-4] + ".part.mp4"
    run_ffmpeg(["-i", src, "-an", "-vf", f"scale=-2:{PROXY_HEIGHT}", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "23", "-g", "15", "-threads", "2", tmp])
    os.replace(tmp, out)


def cover_filter(w: int, h: int, mirror: bool = False, fps: bool = True) -> str:
    """Scale to fill w x h, cropping the overflow (centred)."""
    f = (f"fps={FPS}," if fps else "") + \
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    return f + (",hflip" if mirror else "")


class FrameReader:
    """Decode a video file to w x h RGB frames in a thread, released on a clock.

    Frame k of the file (after seeking to `seek` s) is due at master time
    `at + k / FPS`; clock() gives master time (return None until the clock has
    started).  A decoder thread keeps up to AHEAD frames buffered; `primed` is
    set once a few are ready, so callers can start the sound only when every
    inset can follow it.  Late frames are skipped (counted in `skipped`).
    on_frame(image_bytes, w, h) gets each frame that is shown.
    """
    AHEAD = 8
    PRIME = 3

    def __init__(self, path: str, w: int, h: int, seek: float, at: float, clock, on_frame,
                 mirror: bool = False):
        self.w, self.h = max(2, w // 2 * 2), max(2, h // 2 * 2)
        self.args = (["-ss", f"{seek:.3f}"] if seek > 0 else []) + [
            "-threads", "2", "-i", path, "-an", "-vf", cover_filter(self.w, self.h, mirror),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.at, self.clock, self.on_frame = at, clock, on_frame
        self.stopped = False
        self.proc: subprocess.Popen | None = None
        self.frames: queue.Queue = queue.Queue(self.AHEAD)
        self.primed = threading.Event()
        self.shown = self.skipped = 0
        threading.Thread(target=self._decode, daemon=True).start()
        threading.Thread(target=self._present, daemon=True).start()

    def _decode(self) -> None:
        try:
            self.proc = subprocess.Popen([ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                                          "-nostdin"] + self.args,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         **_kw(low=True))
        except (OSError, MediaError):
            self.primed.set()
            self._put(None)
            return
        size, n = self.w * self.h * 3, 0
        while not self.stopped:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                break
            self._put(buf)
            n += 1
            if n >= self.PRIME:
                self.primed.set()
        self.primed.set()
        self._put(None)                       # end of file

    def _put(self, item) -> None:
        while not self.stopped:
            try:
                self.frames.put(item, timeout=0.1)
                return
            except queue.Full:
                pass

    def _present(self) -> None:
        k = 0
        while not self.stopped:
            try:
                buf = self.frames.get(timeout=0.1)
            except queue.Empty:
                continue
            if buf is None:
                break
            due = self.at + k / FPS
            k += 1
            while not self.stopped:
                now = self.clock()
                if now is not None and now >= due - 0.004:
                    break
                time.sleep(0.01 if now is None else min(0.02, max(0.001, due - now)))
            if self.stopped:
                break
            if self.clock() <= due + 1.5 / FPS:
                self.on_frame(buf, self.w, self.h)
                self.shown += 1
            else:
                self.skipped += 1
        self.stop()

    def stop(self) -> None:
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


def still(path: str, t: float, w: int, h: int, mirror: bool = False) -> bytes | None:
    """One w x h RGB frame at time t (None if there isn't one)."""
    w, h = max(2, w // 2 * 2), max(2, h // 2 * 2)
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", f"{max(0.0, t):.3f}", "-i", path, "-an", "-frames:v", "1",
                        "-vf", cover_filter(w, h, mirror, fps=False),
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True,
                       **_kw(low=True))
    return p.stdout if len(p.stdout) == w * h * 3 else None
