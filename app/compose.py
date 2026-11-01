"""Draw a template's background/borders with QPainter and export the master .mp4.

The master video is built in one ffmpeg pass: a background still (template
background + reserved regions), each take scaled to cover its slot and placed
at its offset (holding its last frame once it ends), a transparent border
layer on top, and the audio mix.
"""
from __future__ import annotations

import os
import tempfile

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen

from . import media
from .project import Project
from .templates import Template

SIZES = {"1920 × 1080": (1920, 1080), "1280 × 720": (1280, 720)}


def _ensure_gui():
    from PyQt6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _ensure_gui.app = QGuiApplication([])


def background(tpl: Template, texts: dict, w: int, h: int, placeholders: bool = False) -> QImage:
    """Template background with its regions; placeholders=True also marks empty slots."""
    _ensure_gui()
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(tpl.background))
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    qp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    for r in tpl.regions:
        x, y, rw, rh = r["rect"]
        box = QRectF(x * w, y * h, rw * w, rh * h)
        if r.get("fill"):
            qp.fillRect(box, QColor(r["fill"]))
        if r.get("kind") == "text":
            text = texts.get(r.get("id", ""), r.get("text", ""))
            if text:
                f = QFont("Sans Serif")
                f.setPixelSize(max(8, int(float(r.get("size", 0.05)) * h)))
                f.setBold(True)
                qp.setFont(f)
                qp.setPen(QColor(r.get("color", "#ffffff")))
                al = {"left": Qt.AlignmentFlag.AlignLeft, "right": Qt.AlignmentFlag.AlignRight}.get(
                    r.get("align"), Qt.AlignmentFlag.AlignHCenter)
                pad = h * 0.02
                qp.drawText(box.adjusted(pad, pad, -pad, -pad),
                            al | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, text)
    if placeholders:
        f = QFont("Sans Serif")
        f.setPixelSize(max(9, h // 30))
        qp.setFont(f)
        for s in tpl.slots:
            x, y, sw, sh = tpl.pixel_rect(s, w, h)
            qp.fillRect(x, y, sw, sh, QColor("#262630"))
            qp.setPen(QColor("#8a8a99"))
            qp.drawText(QRectF(x, y, sw, sh), Qt.AlignmentFlag.AlignCenter,
                        f"{s.id} · {s.label}\n(empty)")
    qp.end()
    return img


def borders(tpl: Template, w: int, h: int) -> QImage | None:
    """Transparent layer with each slot's border, or None if no slot has one."""
    _ensure_gui()
    if not any(float(tpl.border_of(s).get("width", 0)) > 0 for s in tpl.slots):
        return None
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img)
    for s in tpl.slots:
        b = tpl.border_of(s)
        bw = float(b.get("width", 0)) * w / 1920
        if bw <= 0:
            continue
        x, y, sw, sh = tpl.pixel_rect(s, w, h)
        qp.setPen(QPen(QColor(b.get("color", "#ffffff")), bw))
        qp.drawRect(QRectF(x + bw / 2, y + bw / 2, sw - bw, sh - bw))
    qp.end()
    return img


def export(pr: Project, out: str, size=(1920, 1080), progress=None, crf: int = 20) -> float:
    """Render the master video to `out`; returns its length in seconds."""
    tpl = pr.get_template()
    w, h = size
    takes = [t for t in pr.shown() if os.path.exists(pr.video(t))]
    if not takes:
        raise media.MediaError("There are no takes in the insets to export.")
    order = {s.id: i for i, s in enumerate(tpl.slots)}
    takes.sort(key=lambda t: order[t.slot])           # later slots draw on top
    dur = pr.duration()
    tmp = tempfile.mkdtemp(prefix="boxapella-export-")
    bg, fg, mix = (os.path.join(tmp, n) for n in ("bg.png", "fg.png", "mix.wav"))
    background(tpl, pr.texts, w, h).save(bg)
    fg_img = borders(tpl, w, h)
    if fg_img is not None:
        fg_img.save(fg)
    media.write_wav(mix, pr.mix())

    args = ["-loop", "1", "-framerate", str(media.FPS), "-t", f"{dur:.3f}", "-i", bg]
    for t in takes:
        args += ["-i", pr.video(t)]
    if fg_img is not None:
        args += ["-loop", "1", "-framerate", str(media.FPS), "-t", f"{dur:.3f}", "-i", fg]
    args += ["-i", mix]
    chains, last = [], "[0:v]"
    for i, t in enumerate(takes, start=1):
        x, y, sw, sh = tpl.pixel_rect(tpl.slot(t.slot), w, h)
        off = t.offset_ms / 1000
        shift = f"trim=start={-off:.3f},setpts=PTS-STARTPTS" if off < 0 else \
            f"setpts=PTS-STARTPTS+{off:.3f}/TB"
        chains.append(f"[{i}:v]{media.cover_filter(sw, sh, t.mirror)},{shift}[v{i}]")
        chains.append(f"{last}[v{i}]overlay={x}:{y}:eof_action=repeat[b{i}]")
        last = f"[b{i}]"
    n_in = len(takes) + 1
    if fg_img is not None:
        chains.append(f"{last}[{n_in}:v]overlay=0:0[bf]")
        last, n_in = "[bf]", n_in + 1
    chains.append(f"{last}format=yuv420p[vout]")
    args += ["-filter_complex", ";".join(chains), "-map", "[vout]", "-map", f"{n_in}:a",
             "-r", str(media.FPS), "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
             "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", "-movflags", "+faststart", out]
    try:
        media.run_ffmpeg(args, dur, progress)
    finally:
        for p in (bg, fg, mix):
            if os.path.exists(p):
                os.remove(p)
        os.rmdir(tmp)
    return dur
