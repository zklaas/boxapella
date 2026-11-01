"""Tests: .venv/bin/python -m unittest test_core   (needs ffmpeg via .venv; no camera)."""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np                                         # noqa: E402

from app import capture, compose, media, music, project, templates, voice   # noqa: E402


def make_clip(path, seconds, freq, colour):
    """A test video: solid colour with a moving test pattern, plus a tone."""
    media.run_ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:d={seconds}",
                      "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate=48000",
                      "-vf", f"colorbalance=rs={colour}", "-c:v", "libx264", "-preset", "ultrafast",
                      "-c:a", "aac", "-shortest", path])


class Templates(unittest.TestCase):
    def test_builtins_load(self):
        ts = templates.discover()
        self.assertGreaterEqual(len(ts), 10)
        for t in ts:
            for s in t.slots:
                x, y, w, h = s.rect
                self.assertTrue(0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001, (t.key, s))

    def test_pixel_rect_gap(self):
        t = templates.find("03-fourths")
        x, y, w, h = t.pixel_rect(t.slots[3], 1920, 1080)
        self.assertEqual((x, y), (964, 544))            # 8 px gap split either side
        self.assertEqual((w % 2, h % 2), (0, 0))
        self.assertEqual(x + w, 1920)

    def test_tv_inset_inside_upper_right_quadrant(self):
        t = templates.find("04-tv-inset")
        x, y, w, h = t.slots[1].rect
        self.assertTrue(x >= 0.5 and x + w <= 1 and y + h <= 0.5)


class Mixing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.pr = project.create("t", "02-side-by-side", self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def _take(self, tid, slot, x, **kw):
        t = project.Take(tid, duration=len(x) / media.RATE, slot=slot, **kw)
        media.write_wav(self.pr.wav(t), x)
        self.pr.takes.append(t)
        return t

    def test_offsets_gain_mute(self):
        one = np.full(media.RATE, 0.25, np.float32)
        self._take("take-001", "1", one)
        self._take("take-002", "2", one, offset_ms=500, gain_db=-6.0206)
        m = self.pr.mix()
        self.assertEqual(len(m), round(1.5 * media.RATE))
        self.assertAlmostEqual(float(m[100]), 0.25, places=3)
        self.assertAlmostEqual(float(m[media.RATE * 3 // 4]), 0.25 + 0.125, places=3)
        self.assertAlmostEqual(self.pr.duration(), 1.5, places=3)
        self.assertEqual(len(self.pr.mix(exclude="take-002")), media.RATE)
        self.pr.take("take-001").mute = True
        self.assertAlmostEqual(float(self.pr.mix()[100]), 0.0, places=4)

    def test_unslotted_take_is_silent(self):
        self._take("take-001", "", np.full(1000, 0.5, np.float32))
        self.assertEqual(len(self.pr.mix()), 0)

    def test_save_load_roundtrip(self):
        self._take("take-001", "1", np.zeros(10, np.float32), mirror=True, voice={"kind": "custom"})
        self.pr.texts["title"] = "Hi"
        self.pr.save()
        p2 = project.load(self.pr.folder)
        self.assertEqual(p2.take("take-001").voice, {"kind": "custom"})
        self.assertTrue(p2.take("take-001").mirror)
        self.assertEqual(p2.texts, {"title": "Hi"})
        self.assertEqual(p2.next_id(), "take-002")


class Latency(unittest.TestCase):
    def test_detect_known_delay(self):
        rng = np.random.default_rng(3)
        mic_start, play_t, L = 100.0, 100.4, 0.137
        times = [0.6 + sum(capture.GAPS[:k]) for k in range(len(capture.GAPS))]
        x = (0.01 * rng.standard_normal(round(7 * media.RATE))).astype(np.float32)
        c = capture.click(2500, 12, 0.5)
        for t in times:
            i = round((play_t + t - mic_start + L) * media.RATE)
            x[i:i + len(c)] += c
        ms, conf = capture.detect_latency(x, mic_start, play_t, times)
        self.assertAlmostEqual(ms, 137, delta=3)
        # a latency longer than one click gap must not be mistaken for a shorter one
        x2 = (0.01 * rng.standard_normal(round(8 * media.RATE))).astype(np.float32)
        for t in times:
            i = round((play_t + t - mic_start + 0.912) * media.RATE)
            x2[i:i + len(c)] += c
        self.assertAlmostEqual(capture.detect_latency(x2, mic_start, play_t, times)[0], 912, delta=3)
        self.assertGreater(conf, 3)

    def test_click_track_beats(self):
        y = capture.click_track(2.0, 120)
        onsets = np.flatnonzero((np.abs(y[1:]) > 0.05) & (np.abs(y[:-1]) <= 0.05))
        self.assertEqual(sorted({round(i / media.RATE * 2) for i in onsets}), [0, 1, 2, 3])


class Export(unittest.TestCase):
    """Import two clips, reshape one voice with VocalFry if present, export."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.pr = project.create("Export test", "04-tv-inset", cls.dir)
        a, b = os.path.join(cls.dir, "a.mp4"), os.path.join(cls.dir, "b.mp4")
        make_clip(a, 2.0, 220, 0.5)
        make_clip(b, 1.5, 330, -0.5)
        project.import_video(cls.pr, a, "1")
        project.import_video(cls.pr, b, "2")
        cls.pr.take("take-002").offset_ms = 300

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def test_import(self):
        t = self.pr.take("take-001")
        self.assertAlmostEqual(t.duration, 2.0, delta=0.1)
        self.assertTrue(os.path.exists(self.pr.wav(t)))
        self.assertEqual(media.probe(self.pr.video(t))["fps"], 30)

    def test_export(self):
        out = os.path.join(self.dir, "master.mp4")
        d = compose.export(self.pr, out, (1280, 720))
        self.assertAlmostEqual(d, 2.0, delta=0.1)
        info = media.probe(out)
        self.assertEqual((info["width"], info["height"]), (1280, 720))
        self.assertTrue(info["audio"])
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.15)

    @unittest.skipUnless(voice.available(), "VocalFry not installed")
    def test_vocalfry_preset_keeps_length(self):
        t = self.pr.take("take-001")
        name, path = voice.presets()[0]
        voice.render(self.pr.wav(t), self.pr.voice_wav(t), preset=path)
        t.voice = {"kind": "preset", "name": name, "path": path}
        self.assertAlmostEqual(len(self.pr.take_audio(t)), len(media.read_wav(self.pr.wav(t))),
                               delta=media.RATE * 0.02)


if __name__ == "__main__":
    unittest.main()


def tune(pitches, beat, harmonics, rate=media.RATE, seed=0):
    """Notes (MIDI numbers, one per beat) as a harmonic tone with a little vibrato."""
    rng = np.random.default_rng(seed)
    out = []
    for n in pitches:
        t = np.arange(round(beat * rate)) / rate
        f = 440 * 2 ** ((n - 69) / 12) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
        ph = 2 * np.pi * np.cumsum(f) / rate
        env = np.minimum(1, np.minimum(t / 0.03, (t[-1] - t) / 0.05 + 0.2))
        out.append(sum(np.sin(k * ph) / k ** 1.3 for k in range(1, harmonics + 1)) * env * 0.2)
    return (np.concatenate(out) + 0.003 * rng.standard_normal(sum(map(len, out)))).astype(np.float32)


class Music(unittest.TestCase):
    """Lining music up with singing, and the picture video."""

    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(7)
        cls.melody = list(rng.integers(55, 72, 40))
        bass = [m - 12 - int(rng.integers(0, 2)) * 5 for m in cls.melody]
        cls.music = tune(cls.melody, 0.5, 4, seed=1) + 0.8 * tune(bass, 0.5, 8, seed=2)
        cls.voice = tune(cls.melody, 0.5, 12, seed=3)          # same tune, different timbre

    def test_singing_starts_into_the_music(self):
        cut = round(3.37 * media.RATE)
        off, conf = music.find_offset(self.music, self.voice[cut:])
        self.assertAlmostEqual(off, 3.37, delta=0.03)
        self.assertGreater(conf, music.MIN_CONFIDENCE)

    def test_music_starts_after_the_singing(self):
        lead = np.zeros(round(2.0 * media.RATE), np.float32)
        off, _ = music.find_offset(self.music, np.concatenate([lead, self.voice]))
        self.assertAlmostEqual(off, -2.0, delta=0.03)
        placed = music.shift(self.music, off)
        self.assertAlmostEqual(len(placed) - len(self.music), round(2.0 * media.RATE), delta=0.03 * media.RATE)

    def test_import_with_picture_lines_up(self):
        d = tempfile.mkdtemp()
        try:
            pr = project.create("Music test", "02-side-by-side", d)
            sung = os.path.join(d, "sung.mp4")
            wav = os.path.join(d, "sung.wav")
            media.write_wav(wav, self.voice[round(1.5 * media.RATE):])
            music.make_video("", wav, sung)
            project.import_video(pr, sung, "1")
            song = os.path.join(d, "song.wav")
            media.write_wav(song, self.music)
            pic = os.path.join(d, "pic.png")
            media.run_ffmpeg(["-f", "lavfi", "-i", "color=c=red:s=300x400", "-frames:v", "1", pic])
            t, off, conf = music.import_music(pr, song, "2", pic)
            self.assertEqual(pr.in_slot("2").id, t.id)
            self.assertAlmostEqual(off, 1.5, delta=0.03)
            info = media.probe(pr.video(t))
            self.assertEqual((info["width"], info["height"]), music.SIZE)
            self.assertAlmostEqual(t.duration, len(self.music) / media.RATE - 1.5, delta=0.15)
            self.assertEqual(t.note, "song.wav + pic.png")
        finally:
            shutil.rmtree(d)

    def test_midi_renders(self):
        try:
            music.find_synth()
        except media.MediaError:
            self.skipTest("no FluidSynth / SoundFont")
        trk = bytes([0, 0x90, 60, 100, 0x83, 0x60, 0x80, 60, 0, 0, 0xFF, 0x2F, 0])   # one C4, 480 ticks
        mid = (b"MThd" + (6).to_bytes(4, "big") + bytes([0, 0, 0, 1, 1, 0xE0])
               + b"MTrk" + len(trk).to_bytes(4, "big") + trk)
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "c.mid")
            with open(p, "wb") as f:
                f.write(mid)
            y = music.load_music(p, d)
            self.assertGreater(float(np.abs(y).max()), 0.01)
            self.assertGreater(len(y) / media.RATE, 0.4)
        finally:
            shutil.rmtree(d)


class WindowsPaths(unittest.TestCase):
    """The Windows code, exercised on any OS: DirectShow parsing and the duplex audio clock."""

    DEVICES = '''[dshow @ 000001] "HP True Vision FHD Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid_0408"
[dshow @ 000001] "OBS Virtual Camera" (video)
[dshow @ 000001] "Microphone Array (Realtek(R) Audio)" (audio)
'''
    OPTIONS = '''[dshow @ 000002] DirectShow video device options (from video devices)
[dshow @ 000002]  Pin "Capture" (alternative pin name "0")
[dshow @ 000002]   vcodec=mjpeg  min s=1920x1080 fps=30 max s=1920x1080 fps=30
[dshow @ 000002]   vcodec=mjpeg  min s=1280x720 fps=30 max s=1280x720 fps=30
[dshow @ 000002]   pixel_format=yuyv422  min s=1920x1080 fps=5 max s=1920x1080 fps=5
[dshow @ 000002]   pixel_format=yuyv422  min s=640x480 fps=30 max s=640x480 fps=30
'''

    def test_dshow_parsing(self):
        self.assertEqual(media.parse_dshow_devices(self.DEVICES),
                         ["HP True Vision FHD Camera", "OBS Virtual Camera"])
        self.assertEqual(media.parse_dshow_options(self.OPTIONS),
                         {"kind": "vcodec", "format": "mjpeg", "size": "1920x1080"})
        raw_only = "\n".join(l for l in self.OPTIONS.splitlines() if "mjpeg" not in l)
        self.assertEqual(media.parse_dshow_options(raw_only),
                         {"kind": "pixel_format", "format": "yuyv422", "size": "640x480"})
        args = media.camera_input({"device": "video=HP True Vision FHD Camera", "api": "dshow",
                                   "kind": "vcodec", "format": "mjpeg", "size": "1920x1080"})
        self.assertIn("-use_wallclock_as_timestamps", args)
        self.assertEqual(args[args.index("-i") + 1], "video=HP True Vision FHD Camera")

    def test_duplex_clock_calibrates_exactly(self):
        import sys
        import threading
        import time
        import types
        delay = 21_000                                  # frames from headphones back to the mic

        class FakeStream:
            def __init__(self, samplerate, channels, dtype, device=None, latency=None, callback=None):
                self.cb, self.ch_out, self.on = callback, channels[1], False
                self.line = np.zeros(delay, np.float32)
                self.rng = np.random.default_rng(1)

            def start(self):
                self.on = True
                threading.Thread(target=self._run, daemon=True).start()

            def _run(self):
                while self.on:
                    n = 480
                    indata = (self.line[:n] + 0.005 * self.rng.standard_normal(n)).astype(np.float32)[:, None]
                    out = np.zeros((n, self.ch_out), np.float32)
                    self.cb(indata, out, n, None, None)
                    self.line = np.concatenate([self.line[n:], out[:, 0]])
                    time.sleep(n / media.RATE)

            def stop(self):
                self.on = False

            def close(self):
                pass

        fake = types.ModuleType("sounddevice")
        fake.Stream = FakeStream
        old_mod, old_win = sys.modules.get("sounddevice"), media.WINDOWS
        sys.modules["sounddevice"], media.WINDOWS = fake, True
        try:
            ms, conf = capture.calibrate()
        finally:
            media.WINDOWS = old_win
            if old_mod is None:
                sys.modules.pop("sounddevice", None)
            else:
                sys.modules["sounddevice"] = old_mod
        self.assertAlmostEqual(ms, delay / media.RATE * 1000, delta=1.0)
        self.assertGreater(conf, 3)
