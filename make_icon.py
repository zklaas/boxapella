#!/usr/bin/env python3
"""Draw the Boxapella icon: a golden rectangle cut into ever-smaller squares
(each cut leaves another golden rectangle), the golden spiral running through
them, on a dark rounded tile.  Writes icons/boxapella.png (512) + smaller sizes.
"""
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QPointF, QRectF, Qt          # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen  # noqa: E402

PHI = (1 + 5 ** 0.5) / 2
HERE = os.path.dirname(os.path.abspath(__file__))
COLOURS = ["#e0483c", "#f08a2c", "#f2c230", "#5cb85c", "#2fa4a9", "#3d6fd1", "#7b55c9",
           "#c4489a", "#e0483c", "#f08a2c"]


def squares(x, y, w, h, n):
    """Cut n squares off a golden rectangle, turning left → top → right → bottom.

    Yields (square rect, arc centre, start angle) for the spiral quarter in each.
    """
    for i in range(n):
        side = min(w, h)
        d = i % 4
        if d == 0:                        # square on the left
            sq = (x, y, side, h)
            centre, start = (x + side, y + side), 180
            x, w = x + side, w - side
        elif d == 1:                      # on top
            sq = (x, y, w, side)
            centre, start = (x, y + side), 90
            y, h = y + side, h - side
        elif d == 2:                      # on the right
            sq = (x + w - side, y, side, h)
            centre, start = (x + w - side, y), 0
            w = w - side
        else:                             # at the bottom
            sq = (x, y + h - side, w, side)
            centre, start = (x + w, y + h - side), 270
            h = h - side
        yield sq, centre, start, side


def draw(size=512) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 512
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(QColor("#17171e"))
    qp.drawRoundedRect(QRectF(8 * s, 8 * s, 496 * s, 496 * s), 96 * s, 96 * s)

    W = 440 * s
    H = W / PHI
    x0, y0 = (size - W) / 2, (size - H) / 2
    gap = max(1.0, 7 * s)
    cuts = list(squares(x0, y0, W, H, 9))
    for i, ((x, y, w, h), _c, _a, side) in enumerate(cuts):
        g = min(gap, side * 0.18)
        r = QRectF(x + g / 2, y + g / 2, w - g, h - g)
        qp.setBrush(QColor(COLOURS[i % len(COLOURS)]))
        qp.drawRoundedRect(r, min(r.width(), r.height()) * 0.12, min(r.width(), r.height()) * 0.12)

    path = QPainterPath()
    for i, (_sq, (cx, cy), start, side) in enumerate(cuts):
        rect = QRectF(cx - side, cy - side, 2 * side, 2 * side)
        if i == 0:
            a = math.radians(start)
            path.moveTo(QPointF(cx + side * math.cos(a), cy - side * math.sin(a)))
        path.arcTo(rect, start, -90)
    qp.setBrush(Qt.BrushStyle.NoBrush)
    qp.setPen(QPen(QColor(0, 0, 0, 90), 14 * s, cap=Qt.PenCapStyle.RoundCap))
    qp.drawPath(path)
    qp.setPen(QPen(QColor("#ffffff"), 8 * s, cap=Qt.PenCapStyle.RoundCap))
    qp.drawPath(path)
    qp.end()
    return img


def write_ico(path, images):
    """A Windows .ico holding PNG-compressed images (sizes up to 256)."""
    import struct
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    blobs = []
    for img in images:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        blobs.append((img.width(), bytes(ba)))
    head = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for w, png in blobs:
        entries += struct.pack("<BBBBHHII", w % 256, w % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(head + entries + data)


def main():
    app = QGuiApplication(sys.argv[:1])          # noqa: F841 - needed for QPainter text/AA
    out = os.path.join(HERE, "icons")
    os.makedirs(out, exist_ok=True)
    draw(512).save(os.path.join(out, "boxapella.png"))
    for n in (256, 128, 64, 48):
        draw(n).save(os.path.join(out, f"boxapella-{n}.png"))
    write_ico(os.path.join(out, "boxapella.ico"), [draw(n) for n in (256, 64, 48, 32, 16)])
    print("wrote", out)


if __name__ == "__main__":
    main()
