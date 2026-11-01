#!/usr/bin/env python3
"""Boxapella - one-person multitrack video: record takes into the insets of a template.

  boxapella [PROJECT_FOLDER]          open the app (PyQt6)
  boxapella new NAME [--template KEY] create a project under projects/
  boxapella templates                 list the layout templates
  boxapella cameras [--measure]       list cameras ffmpeg can record from (--measure: real frame rate)
  boxapella import PROJECT VIDEO [--slot ID]
                                      add a video file as a take
  boxapella music PROJECT FILE [--image PIC] [--slot ID] [--no-line-up]
                                      add music (audio or MIDI) with a picture, lined up with the singing
  boxapella export PROJECT OUT.mp4 [--size 1920x1080|1280x720]
                                      render the master video without the GUI
  boxapella calibrate                 measure audio latency (speakers, not headphones)
  boxapella devices                   list cameras and audio devices
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _bar(f):
    print(f"\r{f * 100:5.1f}%", end="", flush=True)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):     # Windows consoles aren't always UTF-8
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else ""
    if cmd in ("-h", "--help"):
        print(__doc__)
        return 0
    if cmd == "templates":
        from app import templates
        for t in templates.discover():
            print(f"{t.key:24s} {len(t.slots):2d} inset(s)  {t.name}")
        return 0
    if cmd == "cameras":
        from app import media
        cams = media.cameras()
        for c in cams:
            fps = f"  real rate {media.measure_camera(c):.1f} fps" if "--measure" in argv else ""
            print(f"{c['device']:12s} {c['format']:6s} {c['size']:10s} {c['name']}{fps}")
        if not cams:
            print("No camera found (in VirtualBox: Devices → Webcams).")
        return 0
    if cmd == "devices":
        from app import media
        print("Cameras:")
        for c in media.cameras():
            print(f"  {c['device']}  ({c['format']} {c['size']})")
        print("Audio:")
        for line in media.audio_devices():
            print("  " + line)
        return 0
    if cmd == "new":
        from app import project, templates
        ap = argparse.ArgumentParser(prog="boxapella new")
        ap.add_argument("name")
        ap.add_argument("--template", default="03-fourths")
        a = ap.parse_args(argv[1:])
        pr = project.create(a.name, templates.find(a.template).key)
        print(pr.folder)
        return 0
    if cmd == "import":
        from app import project
        ap = argparse.ArgumentParser(prog="boxapella import")
        ap.add_argument("project")
        ap.add_argument("video")
        ap.add_argument("--slot", default="")
        a = ap.parse_args(argv[1:])
        pr = project.load(a.project)
        t = project.import_video(pr, a.video, a.slot or pr.first_empty_slot(), _bar)
        print(f"\n{t.id} ({t.duration:.2f} s) in inset {t.slot}")
        return 0
    if cmd == "music":
        from app import music, project
        ap = argparse.ArgumentParser(prog="boxapella music")
        ap.add_argument("project")
        ap.add_argument("music", help="audio or MIDI file")
        ap.add_argument("--image", default="", help="picture to show (default: a plain frame)")
        ap.add_argument("--slot", default="")
        ap.add_argument("--no-line-up", action="store_true", help="don't line it up with the singing")
        a = ap.parse_args(argv[1:])
        pr = project.load(a.project)
        t, off, conf = music.import_music(pr, a.music, a.slot or pr.first_empty_slot(), a.image,
                                          not a.no_line_up, _bar)
        print(f"
{t.id} ({t.duration:.2f} s) in inset {t.slot}")
        if not a.no_line_up:
            print(f"lined up: music cut by {off:.3f} s (confidence {conf:.2f})" if off is not None else
                  f"not lined up: no clear match (confidence {conf:.2f})")
        return 0
    if cmd == "export":
        from app import compose, project
        ap = argparse.ArgumentParser(prog="boxapella export")
        ap.add_argument("project")
        ap.add_argument("output")
        ap.add_argument("--size", default="1920x1080", choices=["1920x1080", "1280x720"])
        a = ap.parse_args(argv[1:])
        size = tuple(int(v) for v in a.size.split("x"))
        d = compose.export(project.load(a.project), a.output, size, _bar)
        print(f"\nwrote {a.output} ({d:.2f} s)")
        return 0
    if cmd == "calibrate":
        from app import capture, config
        print("Playing clicks through the speakers; keep quiet…")
        ms, conf = capture.calibrate(config.load().get("mic_target", ""))
        print(f"latency {ms:.0f} ms (confidence {conf:.1f}; below 3 = unreliable)")
        if conf >= 3:
            cfg = config.load()
            cfg["latency_ms"] = round(ms)
            config.save(cfg)
            print("saved to settings")
        return 0
    from app.gui import run
    return run(argv[0] if argv else None)


if __name__ == "__main__":
    sys.exit(main())
