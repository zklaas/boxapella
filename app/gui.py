"""Boxapella main window: the stage (all insets as one master picture) plus controls."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time

import numpy as np
from PyQt6.QtCore import QObject, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QProgressBar, QProgressDialog, QPushButton, QSlider,
                             QSpinBox, QSplitter, QTableWidget, QVBoxLayout, QWidget)

from . import capture, compose, config, media, project, templates, voice

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(HERE, "icons", "boxapella.png")
AS_RECORDED, CUSTOM = "As recorded", "Custom (VocalFry editor)…"


class Bridge(QObject):
    """Carries results from worker threads back to the GUI thread."""
    done = pyqtSignal(object, object, object)       # callback, result, error
    progress = pyqtSignal(float)


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ---------------------------------------------------------------- stage
class Stage(QWidget):
    """The master picture: template background, each inset's current frame, borders."""
    slotClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.pr: project.Project | None = None
        self.tpl: templates.Template | None = None
        self.frames: dict[str, QImage] = {}
        self.lock = threading.Lock()
        self.dirty = False
        self.bg: QImage | None = None
        self.fg: QImage | None = None
        self.selected = ""
        self.rec_slot = ""
        self.banner = ""                 # big text over the picture (count-in)
        t = QTimer(self, interval=33)
        t.timeout.connect(self._tick)
        t.start()

    def set_project(self, pr):
        self.pr = pr
        self.tpl = pr.get_template() if pr else None
        self.bg = self.fg = None
        with self.lock:
            self.frames.clear()
        self.update()

    def canvas(self) -> QRectF:
        w, h = self.width(), self.height()
        cw = min(w, h * 16 / 9)
        ch = cw * 9 / 16
        return QRectF((w - cw) / 2, (h - ch) / 2, cw, ch)

    def slot_size(self, sid: str) -> tuple[int, int]:
        c = self.canvas()
        s = self.tpl.slot(sid) if self.tpl else None
        if not s:
            return 2, 2
        _, _, w, h = self.tpl.pixel_rect(s, int(c.width()), int(c.height()))
        return w, h

    def set_frame(self, sid: str, buf: bytes, w: int, h: int):
        """Thread-safe: show an RGB frame in slot sid."""
        img = QImage(buf, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        with self.lock:
            self.frames[sid] = img
            self.dirty = True

    def clear_frame(self, sid: str):
        with self.lock:
            self.frames.pop(sid, None)
            self.dirty = True

    def _tick(self):
        if self.dirty:
            self.dirty = False
            self.update()

    def resizeEvent(self, e):
        self.bg = self.fg = None
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        if not self.tpl:
            return
        c = self.canvas()
        x, y = (e.position().x() - c.left()) / c.width(), (e.position().y() - c.top()) / c.height()
        for s in reversed(self.tpl.slots):          # topmost first
            sx, sy, sw, sh = s.rect
            if sx <= x <= sx + sw and sy <= y <= sy + sh:
                self.slotClicked.emit(s.id)
                return

    def paintEvent(self, e):
        qp = QPainter(self)
        qp.fillRect(self.rect(), QColor("#0b0b0e"))
        if not self.tpl:
            qp.setPen(QColor("#888"))
            qp.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                        "No project open.\nFile → New project… to start.")
            return
        c = self.canvas()
        W, H = int(c.width()), int(c.height())
        if self.bg is None or self.bg.width() != W:
            self.bg = compose.background(self.tpl, self.pr.texts, W, H, placeholders=True)
            self.fg = compose.borders(self.tpl, W, H)
        ox, oy = int(c.left()), int(c.top())
        qp.drawImage(ox, oy, self.bg)
        with self.lock:
            frames = dict(self.frames)
        for s in self.tpl.slots:
            img = frames.get(s.id)
            if img is not None:
                x, y, w, h = self.tpl.pixel_rect(s, W, H)
                qp.drawImage(QRectF(ox + x, oy + y, w, h), img)
        if self.fg is not None:
            qp.drawImage(ox, oy, self.fg)
        for sid, colour, width in ((self.selected, "#e8a923", 2), (self.rec_slot, "#e0302a", 4)):
            s = self.tpl.slot(sid) if sid else None
            if s:
                x, y, w, h = self.tpl.pixel_rect(s, W, H)
                qp.setPen(QPen(QColor(colour), width))
                qp.drawRect(QRectF(ox + x + width / 2, oy + y + width / 2, w - width, h - width))
        s = self.tpl.slot(self.rec_slot) if self.rec_slot else None
        if s:
            x, y, w, h = self.tpl.pixel_rect(s, W, H)
            f = QFont("Sans Serif")
            f.setPixelSize(max(10, H // 28))
            f.setBold(True)
            qp.setFont(f)
            qp.setPen(QColor("#ff4a3d"))
            qp.drawText(QRectF(ox + x + 8, oy + y + 6, w, H // 20), "● REC")
        if self.banner:
            f = QFont("Sans Serif")
            f.setPixelSize(max(20, H // 5))
            f.setBold(True)
            qp.setFont(f)
            qp.setPen(QColor(255, 255, 255, 230))
            qp.drawText(c, Qt.AlignmentFlag.AlignCenter, self.banner)


# ---------------------------------------------------------------- dialogs
class NewProjectDialog(QDialog):
    def __init__(self, parent, tpls):
        super().__init__(parent)
        self.setWindowTitle("New project")
        lay = QFormLayout(self)
        self.name = QLineEdit("My song")
        self.tpl = QComboBox()
        for t in tpls:
            self.tpl.addItem(f"{t.name}  ({len(t.slots)} inset{'s' * (len(t.slots) > 1)})", t.key)
        self.tpl.setCurrentIndex(max(0, self.tpl.findData("03-fourths")))
        lay.addRow("Name", self.name)
        lay.addRow("Template", self.tpl)
        lay.addRow(QLabel(f"Saved under {project.PROJECTS_DIR}"))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.setWindowTitle("Timing & devices")
        self.cfg = cfg
        lay = QFormLayout(self)
        self.lat = QDoubleSpinBox(minimum=-500, maximum=2000, decimals=0, suffix=" ms")
        self.lat.setValue(cfg["latency_ms"])
        self.lat.setToolTip("Time from the backing leaving the computer to your voice coming back "
                            "in through the mic. New takes are shifted earlier by this much.")
        cal = QPushButton("Calibrate…")
        cal.clicked.connect(self._calibrate)
        row = QHBoxLayout()
        row.addWidget(self.lat)
        row.addWidget(cal)
        lay.addRow("Audio latency", row)
        self.vid = QDoubleSpinBox(minimum=-1000, maximum=1000, decimals=0, suffix=" ms")
        self.vid.setValue(cfg["video_offset_ms"])
        self.vid.setToolTip("Lip sync for new takes: positive = cut more from the start of the "
                            "video (picture earlier relative to the sound).")
        lay.addRow("Video offset", self.vid)
        self.mic = QLineEdit(cfg.get("mic_target", ""))
        self.mic.setPlaceholderText("default microphone")
        self.mic.setToolTip("PipeWire source name or serial (pw-record --target); blank = default.")
        lay.addRow("Microphone", self.mic)
        self.level = QDoubleSpinBox(minimum=0, maximum=2, singleStep=0.1, decimals=2)
        self.level.setValue(cfg.get("backing_level", 1.0))
        lay.addRow("Headphone backing level", self.level)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _calibrate(self):
        if QMessageBox.information(
                self, "Calibrate latency",
                "Take your headphones off and turn the speakers up to a normal level.\n"
                "Boxapella will play eight clicks and listen for them with the microphone.\n"
                "Keep quiet for about 6 seconds.",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Ok:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ms, conf = capture.calibrate(self.mic.text().strip())
        except media.MediaError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Calibrate", str(e))
            return
        QApplication.restoreOverrideCursor()
        if conf < 3:
            QMessageBox.warning(self, "Calibrate",
                                f"The clicks weren't heard clearly (confidence {conf:.1f}; "
                                f"best guess {ms:.0f} ms). Turn the speakers up and try again.")
            return
        self.lat.setValue(round(ms))
        QMessageBox.information(self, "Calibrate", f"Latency: {ms:.0f} ms (confidence {conf:.0f}).")

    def values(self) -> dict:
        return {"latency_ms": self.lat.value(), "video_offset_ms": self.vid.value(),
                "mic_target": self.mic.text().strip(), "backing_level": self.level.value()}


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    COLS = ["Inset", "Take", "Voice", "", "dB", "Offset", "Mute", "Flip"]

    def __init__(self, path: str | None = None):
        super().__init__()
        self.setWindowTitle("Boxapella")
        if os.path.exists(ICON):
            self.setWindowIcon(QIcon(ICON))
        self.cfg = config.load()
        self.pr: project.Project | None = None
        self.bridge = Bridge()
        self.bridge.done.connect(lambda cb, r, err: cb(r, err))
        self.player = media.make_player()
        self.readers: list[media.FrameReader] = []
        self.clock_base: float | None = None   # master time = monotonic - clock_base; None = not started
        self.start_deadline = 0.0
        self.playing = False
        self.session: capture.Session | None = None
        self.state = "idle"              # idle | starting | playing | arming | recording | saving
        self.tmp = tempfile.mkdtemp(prefix="boxapella-")
        self.cams: list[dict] = []
        self.presets: list[tuple[str, str]] = []
        self.voice_mtimes: dict[str, float] = {}
        self.busy_voice: set[str] = set()
        self._build()
        self.tick = QTimer(self, interval=50)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()
        self.watch = QTimer(self, interval=1000)
        self.watch.timeout.connect(self._watch_voices)
        self.watch.start()
        self.still_timer = QTimer(self, singleShot=True, interval=150)
        self.still_timer.timeout.connect(self._load_stills)
        self._refresh_cameras()
        self._bg(voice.presets, self._got_presets)
        start = path or self.cfg.get("last_project")
        if start and os.path.exists(start):
            self.open_project(start)
        self.resize(1400, 820)

    # ---- layout
    def _build(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        def act(text, slot, tip="", key=None, menu=None):
            a = QAction(text, self)
            a.setToolTip(tip or text)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(slot)
            (menu or tb).addAction(a)
            return a
        fm = self.menuBar().addMenu("&File")
        act("New project…", self._new_project, key="Ctrl+N", menu=fm)
        act("Open project…", self._open_dialog, key="Ctrl+O", menu=fm)
        act("Open project folder", self._open_folder, menu=fm)
        fm.addSeparator()
        act("Import video into selected inset…", self._import, key="Ctrl+I", menu=fm)
        act("Export master video…", self._export, key="Ctrl+E", menu=fm)
        fm.addSeparator()
        act("Delete takes not in an inset…", self._delete_unused, menu=fm)
        fm.addSeparator()
        act("Quit", self.close, key="Ctrl+Q", menu=fm)
        sm = self.menuBar().addMenu("&Settings")
        act("Timing && devices…", self._settings, menu=sm)
        act("Open my templates folder", self._open_templates, menu=sm)

        self.play_act = act("▶ Play", self._toggle_play, "Play the master from the playhead (Space)", "Space")
        act("⏮", lambda: self._seek(0), "Back to the start (Home)", "Home")
        tb.addSeparator()
        self.rec_act = act("● Record", self._toggle_record,
                           "Record a take into the selected inset (R); the other insets play in your headphones", "R")
        tb.addSeparator()
        act("Import video…", self._import, "Use an existing video file for the selected inset")
        act("Export MP4…", self._export, "Render the master video")

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)
        self.stage = Stage()
        self.stage.slotClicked.connect(self._select_slot)
        ll.addWidget(self.stage, 1)
        pos = QHBoxLayout()
        self.pos = QSlider(Qt.Orientation.Horizontal)
        self.pos.setRange(0, 0)
        self.pos.sliderMoved.connect(lambda v: self._seek(v / 10, from_slider=True))
        self.time_lbl = QLabel("0:00.0 / 0:00.0")
        self.time_lbl.setMinimumWidth(130)
        pos.addWidget(self.pos, 1)
        pos.addWidget(self.time_lbl)
        ll.addLayout(pos)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        g = QGroupBox("Template")
        gl = QVBoxLayout(g)
        self.tpl_combo = QComboBox()
        self.tpl_combo.activated.connect(self._template_chosen)
        gl.addWidget(self.tpl_combo)
        self.tpl_desc = QLabel()
        self.tpl_desc.setWordWrap(True)
        self.tpl_desc.setStyleSheet("color: #888;")
        gl.addWidget(self.tpl_desc)
        self.text_form = QFormLayout()
        gl.addLayout(self.text_form)
        rl.addWidget(g)

        g = QGroupBox("Insets")
        gl = QVBoxLayout(g)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        for col, tip in ((4, "Volume of this inset's audio, in dB"),
                         (5, "Offset in ms: slide the take later (+) or earlier (−), picture and sound together"),
                         (6, "Mute this inset's audio"), (7, "Flip the picture left-right (mirror)")):
            self.table.horizontalHeaderItem(col).setToolTip(tip)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._table_selected)
        gl.addWidget(self.table)
        hint = QLabel("Click an inset (here or on the picture), then ● Record. "
                      "Voice: reshape that inset's audio with VocalFry; ✎ opens VocalFry's editor.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888;")
        gl.addWidget(hint)
        rl.addWidget(g, 1)

        g = QGroupBox("Recording")
        fl = QFormLayout(g)
        cam_row = QHBoxLayout()
        self.cam_combo = QComboBox()
        self.cam_combo.activated.connect(self._camera_chosen)
        again = QPushButton("↻")
        again.setToolTip("Look for cameras again")
        again.setMaximumWidth(32)
        again.clicked.connect(self._refresh_cameras)
        cam_row.addWidget(self.cam_combo, 1)
        cam_row.addWidget(again)
        fl.addRow("Camera", cam_row)
        self.count_spin = QSpinBox(minimum=0, maximum=16, suffix=" clicks")
        self.count_spin.setValue(int(self.cfg["count_in"]))
        self.bpm_spin = QDoubleSpinBox(minimum=30, maximum=240, decimals=0, suffix=" bpm")
        self.bpm_spin.setValue(float(self.cfg["bpm"]))
        row = QHBoxLayout()
        row.addWidget(self.count_spin)
        row.addWidget(self.bpm_spin)
        fl.addRow("Count-in", row)
        self.met_chk = QCheckBox("Click track in the headphones while recording")
        self.met_chk.setChecked(bool(self.cfg["metronome"]))
        self.mirror_chk = QCheckBox("Mirror new takes (like a mirror)")
        self.mirror_chk.setChecked(bool(self.cfg["mirror"]))
        for w in (self.met_chk, self.mirror_chk):
            fl.addRow(w)
        for w in (self.count_spin, self.bpm_spin):
            w.valueChanged.connect(self._save_rec_opts)
        for w in (self.met_chk, self.mirror_chk):
            w.toggled.connect(self._save_rec_opts)
        self.lat_lbl = QLabel()
        fl.addRow("Latency", self.lat_lbl)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setMaximumHeight(10)
        fl.addRow("Mic", self.meter)
        rl.addWidget(g)
        split.addWidget(right)
        split.setSizes([760, 640])
        self.setCentralWidget(split)
        self._show_latency()
        self.statusBar().showMessage("Ready.")

    # ---- helpers
    def _bg(self, fn, cb, *args):
        def work():
            try:
                r, err = fn(*args), None
            except Exception as e:     # noqa: BLE001 - reported to the user
                r, err = None, e
            self.bridge.done.emit(cb, r, err)
        threading.Thread(target=work, daemon=True).start()

    def _with_progress(self, title, fn, cb):
        """Run fn(progress) in a thread behind a progress dialog."""
        dlg = QProgressDialog(title, None, 0, 1000, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        conn = self.bridge.progress.connect(lambda f: dlg.setValue(int(f * 1000)))

        def done(r, err):
            self.bridge.progress.disconnect(conn)
            dlg.close()
            cb(r, err)
        self._bg(lambda: fn(self.bridge.progress.emit), done)

    def _save_rec_opts(self):
        self.cfg.update(count_in=self.count_spin.value(), bpm=self.bpm_spin.value(),
                        metronome=self.met_chk.isChecked(),
                        mirror=self.mirror_chk.isChecked())
        config.save(self.cfg)

    def _show_latency(self):
        self.lat_lbl.setText(f"audio {self.cfg['latency_ms']:.0f} ms, video {self.cfg['video_offset_ms']:+.0f} ms "
                             f"(Settings → Timing)")

    # ---- project
    def _new_project(self):
        dlg = NewProjectDialog(self, templates.discover())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        pr = project.create(dlg.name.text().strip() or "Untitled", dlg.tpl.currentData())
        self.open_project(pr.folder)

    def _open_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Open project folder", project.PROJECTS_DIR)
        if d:
            self.open_project(d)

    def open_project(self, folder):
        try:
            pr = project.load(folder)
        except (OSError, ValueError, TypeError) as e:
            QMessageBox.warning(self, "Boxapella", f"Could not open {folder}:\n{e}")
            return
        self._stop_all()
        self.pr = pr
        self.cfg["last_project"] = pr.folder
        config.save(self.cfg)
        self.voice_mtimes = {t.id: self._mtime(pr.voice_wav(t)) for t in pr.takes}
        self.setWindowTitle(f"Boxapella — {pr.name}")
        self.stage.set_project(pr)
        self.stage.selected = pr.first_empty_slot()
        self._refresh_all()
        self._make_missing_proxies()

    def _make_missing_proxies(self):
        """Takes from before proxies existed get theirs, one at a time, in the background."""
        pr = self.pr
        todo = [t for t in pr.takes if os.path.exists(pr.video(t)) and not os.path.exists(pr.proxy(t))]
        if not todo:
            return
        self.statusBar().showMessage(f"Making small preview copies of {len(todo)} take(s) for smoother playback…")

        def work():
            for t in todo:
                media.make_proxy(pr.video(t), pr.proxy(t))

        def done(_r, err):
            if err:
                self.statusBar().showMessage(f"Preview copies failed: {err}")
            elif self.pr is pr:
                self.statusBar().showMessage("Preview copies ready.", 5000)
        self._bg(work, done)

    def _open_folder(self):
        if self.pr:
            self._xdg(self.pr.folder)

    def _open_templates(self):
        os.makedirs(templates.USER_DIR, exist_ok=True)
        self._xdg(templates.USER_DIR)

    def _xdg(self, path):
        if media.WINDOWS:
            os.startfile(path)              # noqa: S606 - opens Explorer
            return
        import subprocess
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _changed(self, stills=True):
        if self.pr:
            self.pr.save()
        self._update_duration()
        if stills:
            self.still_timer.start()

    def _refresh_all(self):
        self._fill_templates()
        self._fill_texts()
        self._fill_table()
        self._update_duration()
        self.still_timer.start()

    def _update_duration(self):
        d = self.pr.duration() if self.pr else 0.0
        self.pos.setRange(0, int(d * 10))
        self._show_time(self.pos.value() / 10)

    def _show_time(self, t):
        d = self.pr.duration() if self.pr else 0.0
        self.time_lbl.setText(f"{fmt_time(t)} / {fmt_time(d)}")

    # ---- template & texts
    def _fill_templates(self):
        self.tpl_combo.clear()
        cur = self.pr.get_template().key if self.pr else ""
        for t in templates.discover():
            self.tpl_combo.addItem(f"{t.name}  ({len(t.slots)})", t.key)
        self.tpl_combo.setCurrentIndex(max(0, self.tpl_combo.findData(cur)))
        tpl = self.pr.get_template() if self.pr else None
        self.tpl_desc.setText(tpl.description if tpl else "")

    def _template_chosen(self):
        if not self.pr or self.state != "idle":
            return
        key = self.tpl_combo.currentData()
        self.pr.template = key
        tpl = self.pr.get_template()
        ids = {s.id for s in tpl.slots}
        lost = [t.id for t in self.pr.takes if t.slot and t.slot not in ids]
        for t in self.pr.takes:
            if t.slot and t.slot not in ids:
                t.slot = ""
        if lost:
            self.statusBar().showMessage(f"{', '.join(lost)} had no inset in this template; "
                                         "kept as alternates (pick them under Take).")
        self.stage.set_project(self.pr)
        if self.stage.selected not in ids:
            self.stage.selected = self.pr.first_empty_slot()
        self.pr.save()
        self._refresh_all()

    def _fill_texts(self):
        while self.text_form.rowCount():
            self.text_form.removeRow(0)
        if not self.pr:
            return
        for r in self.pr.get_template().regions:
            if r.get("kind") != "text":
                continue
            rid = r.get("id", "")
            ed = QLineEdit(self.pr.texts.get(rid, r.get("text", "")))
            ed.editingFinished.connect(lambda rid=rid, ed=ed: self._text_changed(rid, ed.text()))
            self.text_form.addRow(rid.capitalize(), ed)

    def _text_changed(self, rid, text):
        self.pr.texts[rid] = text
        self.pr.save()
        self.stage.bg = None
        self.stage.update()

    # ---- inset table
    def _fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        if not self.pr:
            self.table.blockSignals(False)
            return
        tpl = self.pr.get_template()
        self.table.setRowCount(len(tpl.slots))
        names = [AS_RECORDED] + [n for n, _ in self.presets] + [CUSTOM]
        for row, s in enumerate(tpl.slots):
            t = self.pr.in_slot(s.id)
            lbl = QLabel(f" {s.id} · {s.label} ")
            self.table.setCellWidget(row, 0, lbl)
            tc = QComboBox()
            tc.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            tc.setMinimumContentsLength(13)
            tc.addItem("— empty —", "")
            for tk in self.pr.takes:
                where = "" if not tk.slot or tk.slot == s.id else f" (in {tk.slot})"
                tc.addItem(f"{tk.id}  {fmt_time(tk.duration)}{where}", tk.id)
            tc.setCurrentIndex(max(0, tc.findData(t.id if t else "")))
            tc.activated.connect(lambda _i, sid=s.id, tc=tc: self._take_chosen(sid, tc.currentData()))
            self.table.setCellWidget(row, 1, tc)
            if not t:
                for col in range(2, len(self.COLS)):
                    self.table.setCellWidget(row, col, QLabel(""))
                continue
            vc = QComboBox()
            vc.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            vc.setMinimumContentsLength(12)
            vc.addItems(names)
            if t.voice.get("kind") == "custom":
                vc.setItemText(len(names) - 1, "Custom voice (VocalFry)")
                vc.setCurrentIndex(len(names) - 1)
            elif t.voice.get("kind") == "preset":
                i = vc.findText(t.voice.get("name", ""))
                if i < 0:
                    vc.insertItem(1, t.voice.get("name", "?"))
                    i = 1
                vc.setCurrentIndex(i)
            if not voice.available():
                vc.setEnabled(False)
                vc.setToolTip("VocalFry isn't installed.")
            if t.id in self.busy_voice:
                vc.setEnabled(False)
                vc.setToolTip("Reshaping…")
            vc.activated.connect(lambda _i, tid=t.id, vc=vc: self._voice_chosen(tid, vc.currentText()))
            self.table.setCellWidget(row, 2, vc)
            ed = QPushButton("✎")
            ed.setMaximumWidth(30)
            ed.setToolTip("Shape this inset's voice in VocalFry's editor, then press "
                          "“Send to Boxapella” there")
            ed.setEnabled(voice.available())
            ed.clicked.connect(lambda _c, tid=t.id: self._edit_voice(tid))
            self.table.setCellWidget(row, 3, ed)
            gain = QDoubleSpinBox(minimum=-40, maximum=12, decimals=1, singleStep=1)
            gain.setValue(t.gain_db)
            gain.valueChanged.connect(lambda v, t=t: (setattr(t, "gain_db", v), self._changed(False)))
            self.table.setCellWidget(row, 4, gain)
            off = QSpinBox(minimum=-60000, maximum=60000, singleStep=10)
            off.setValue(int(t.offset_ms))
            off.setToolTip("Slide this take later (+) or earlier (−) against the others, "
                           "sound and picture together")
            off.valueChanged.connect(lambda v, t=t: (setattr(t, "offset_ms", float(v)), self._changed()))
            self.table.setCellWidget(row, 5, off)
            for col, attr in ((6, "mute"), (7, "mirror")):
                cb = QCheckBox()
                cb.setChecked(getattr(t, attr))
                cb.toggled.connect(lambda v, t=t, a=attr: (setattr(t, a, v), self._changed(a == "mirror")))
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(6, 0, 6, 0)
                hl.addWidget(cb)
                self.table.setCellWidget(row, col, w)
        ids = [s.id for s in tpl.slots]
        if self.stage.selected in ids:
            self.table.selectRow(ids.index(self.stage.selected))
        self.table.blockSignals(False)

    def _table_selected(self):
        rows = self.table.selectionModel().selectedRows()
        if rows and self.pr:
            self.stage.selected = self.pr.get_template().slots[rows[0].row()].id
            self.stage.update()

    def _select_slot(self, sid):
        self.stage.selected = sid
        ids = [s.id for s in self.pr.get_template().slots]
        self.table.blockSignals(True)
        self.table.selectRow(ids.index(sid))
        self.table.blockSignals(False)
        self.stage.update()

    def _take_chosen(self, sid, tid):
        if tid:
            self.pr.assign(tid, sid)
        else:
            t = self.pr.in_slot(sid)
            if t:
                t.slot = ""
        self.stage.clear_frame(sid)
        self._changed()
        self._fill_table()

    # ---- voices (VocalFry)
    def _got_presets(self, r, err):
        self.presets = r or []
        self._fill_table()

    def _voice_chosen(self, tid, name):
        t = self.pr.take(tid)
        if not t:
            return
        if name == AS_RECORDED:
            t.voice = {}
            self._remove(self.pr.voice_wav(t))
            self._changed(False)
            self.statusBar().showMessage(f"{tid}: back to the voice as recorded.")
            return
        if name.startswith("Custom"):
            self._edit_voice(tid)
            return
        path = dict(self.presets).get(name, t.voice.get("path", ""))
        t.voice = {"kind": "preset", "name": name, "path": path}
        self._changed(False)
        self._render_voice(t, preset=path or name)

    def _render_voice(self, t, preset):
        self.busy_voice.add(t.id)
        self._fill_table()
        out = self.pr.voice_wav(t)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        part = out[:-4] + ".rendering.wav"
        self.statusBar().showMessage(f"Reshaping {t.id} with VocalFry ({t.voice.get('name')})…")

        def work():
            voice.render(self.pr.wav(t), part, preset=preset)
            os.replace(part, out)

        def done(_r, err):
            self.busy_voice.discard(t.id)
            self.voice_mtimes[t.id] = self._mtime(out)
            if err:
                self._remove(part)
                QMessageBox.warning(self, "VocalFry", f"Could not reshape {t.id}:\n{err}")
            else:
                self.statusBar().showMessage(f"{t.id} now sings as {t.voice.get('name')}.")
            self._fill_table()
        self._bg(work, done)

    def _edit_voice(self, tid):
        t = self.pr.take(tid)
        if not t:
            return
        settings = self.pr.voice_settings(t)
        if t.voice.get("kind") == "preset" and t.voice.get("path"):
            settings = t.voice["path"]
        os.makedirs(self.pr.path("voices"), exist_ok=True)
        try:
            voice.edit(self.pr.wav(t), self.pr.voice_wav(t), settings)
        except voice.VoiceError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            return
        self.statusBar().showMessage(f"VocalFry opened on {tid}. Shape the voice there and press "
                                     "“⮐ Send to Boxapella”; it will be mixed in here.", 15000)

    def _watch_voices(self):
        """Pick up voices sent back from VocalFry's editor."""
        if not self.pr:
            return
        for t in self.pr.takes:
            if t.id in self.busy_voice:
                continue
            m = self._mtime(self.pr.voice_wav(t))
            if m and m != self.voice_mtimes.get(t.id):
                self.voice_mtimes[t.id] = m
                t.voice = {"kind": "custom"}
                self.pr.save()
                self._fill_table()
                self.statusBar().showMessage(f"New voice from VocalFry for {t.id}.", 8000)

    @staticmethod
    def _mtime(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    @staticmethod
    def _remove(p):
        try:
            os.remove(p)
        except OSError:
            pass

    # ---- stills & playback
    def _load_stills(self):
        if not self.pr or self.state != "idle":
            return
        t0 = self.pos.value() / 10
        for s in self.pr.get_template().slots:
            tk = self.pr.in_slot(s.id)
            if not tk or not os.path.exists(self.pr.video(tk)):
                self.stage.clear_frame(s.id)
                continue
            w, h = self.stage.slot_size(s.id)
            at = min(max(0.0, t0 - tk.offset_ms / 1000), max(0.0, tk.duration - 0.05))

            def work(path=self.pr.preview_video(tk), at=at, w=w, h=h, m=tk.mirror):
                return media.still(path, at, w, h, m), w, h

            def done(r, err, sid=s.id):
                if r and r[0]:
                    self.stage.set_frame(sid, *r)
            self._bg(work, done)

    def _start_readers(self, t0, exclude=""):
        """Video for every shown take from master time t0 on, against self.clock()."""
        for tk in self.pr.shown():
            if tk.id == exclude or not os.path.exists(self.pr.video(tk)):
                continue
            off = tk.offset_ms / 1000
            seek = max(0.0, t0 - off)
            if seek >= tk.duration:
                continue
            w, h = self.stage.slot_size(tk.slot)
            self.readers.append(media.FrameReader(
                self.pr.preview_video(tk), w, h, seek, off + seek, self.clock,
                lambda b, w, h, sid=tk.slot: self.stage.set_frame(sid, b, w, h), tk.mirror))

    def clock(self) -> float | None:
        return None if self.clock_base is None else time.monotonic() - self.clock_base

    def _primed(self) -> bool:
        """Every inset has frames decoded and waiting (or we've waited long enough)."""
        return all(r.primed.is_set() for r in self.readers) or time.monotonic() > self.start_deadline

    def _stop_readers(self):
        for r in self.readers:
            r.stop()
        self.readers = []

    def _toggle_play(self):
        if self.state in ("playing", "starting"):
            self._stop_play()
        elif self.state == "idle" and self.pr and self.pr.shown():
            self._play(self.pos.value() / 10)

    def _play(self, t0):
        d = self.pr.duration()
        if t0 >= d - 0.1:
            t0 = 0.0
        # A short silence first: a sound device waking from suspend can stutter
        # for a moment, and this way that moment is silent.
        # The insets' decoders start first and the sound only once each has frames
        # ready, so neither the pictures nor the sound stumble at the start.
        self.clock_base = None
        self._start_readers(t0)
        lead = 0.4
        mix = self.pr.mix()[round(t0 * media.RATE):]
        self.play_wav = os.path.join(self.tmp, "play.wav")
        media.write_wav(self.play_wav, np.concatenate([np.zeros(round(lead * media.RATE), np.float32), mix]))
        self.play_from, self.play_lead = t0, lead
        self.start_deadline = time.monotonic() + 3.0
        self.state = "starting"
        self.play_act.setText("■ Stop")

    def _stop_play(self):
        self.player.stop()
        self._stop_readers()
        self.state = "idle"
        self.play_act.setText("▶ Play")
        self.still_timer.start()

    def _seek(self, t, from_slider=False):
        if not from_slider:
            self.pos.setValue(int(t * 10))
        self._show_time(t)
        if self.state in ("playing", "starting"):
            self.player.stop()
            self._stop_readers()
            self._play(t)
        elif self.state == "idle":
            self.still_timer.start()

    def _on_tick(self):
        if self.state == "starting" and self._primed():
            self.player.play(self.play_wav)
            self.clock_base = (self.player.started + self.play_lead + self.cfg["latency_ms"] / 2000
                               - self.play_from)
            self.state = "playing"
        elif self.state == "playing":
            t = self.clock()
            if not self.pos.isSliderDown():
                self.pos.setValue(int(t * 10))
            self._show_time(t)
            if t > self.pr.duration() + 0.3 or not self.player.playing():
                self._stop_play()
        elif self.state == "arming":
            s = self.session
            err = s.failed()
            if err:
                self._abort_recording(err)
            elif s.ready() and self._primed():
                zero = s.go()
                self.clock_base = zero + self.cfg["latency_ms"] / 2000
                self.state = "recording"
                self.statusBar().showMessage("Recording… press ■ Stop (R) when done.")
        elif self.state == "recording":
            s = self.session
            t = self.clock()
            beat = 60.0 / max(30.0, self.bpm_spin.value())
            counting = s.cfg.get("count_in") and -s.count_in - 0.02 <= t < -0.05
            self.stage.banner = str(int(-t // beat) + 1) if counting else ""
            self._show_time(max(0.0, t))
            if t >= 0 and not self.pos.isSliderDown():
                self.pos.setValue(int(min(t, self.pr.duration()) * 10))
            self.meter.setValue(int(min(1.0, s.mic.level) * 100))
        if self.state in ("arming",) and self.session:
            self.meter.setValue(int(min(1.0, self.session.mic.level) * 100))

    # ---- recording
    def _refresh_cameras(self):
        def done(r, err):
            self.cams = r or []
            self.cam_combo.clear()
            for c in self.cams:
                self.cam_combo.addItem(f"{c['name']}  ({c['device']}, {c['size']} {c['format']})", c["device"])
            self.cam_combo.addItem("Test pattern (no camera)", media.TEST_CAMERA)
            i = self.cam_combo.findData(self.cfg.get("camera") or (self.cams[0]["device"] if self.cams else ""))
            self.cam_combo.setCurrentIndex(max(0, i))
            if not self.cams:
                self.statusBar().showMessage("No camera found. In VirtualBox: Devices → Webcams; then ↻.")
        self._bg(media.cameras, done)

    def _camera_chosen(self):
        self.cfg["camera"] = self.cam_combo.currentData()
        config.save(self.cfg)

    def _current_camera(self):
        dev = self.cam_combo.currentData()
        return next((c for c in self.cams if c["device"] == dev), {"device": media.TEST_CAMERA})

    def _toggle_record(self):
        if self.state in ("arming", "recording"):
            self._stop_recording()
            return
        if not self.pr:
            QMessageBox.information(self, "Boxapella", "Start a project first (File → New project…).")
            return
        if self.state == "playing":
            self._stop_play()
        if self.state != "idle":
            return
        sid = self.stage.selected or self.pr.first_empty_slot()
        self._select_slot(sid)
        cfg = dict(self.cfg, count_in=self.count_spin.value(), bpm=self.bpm_spin.value(),
                   metronome=self.met_chk.isChecked())
        try:
            self.session = capture.Session(self.pr, sid, self._current_camera(), cfg,
                                           self.stage.slot_size(sid), self.mirror_chk.isChecked(),
                                           lambda b, w, h, sid=sid: self.stage.set_frame(sid, b, w, h))
            self.session.arm()
            self.clock_base = None                  # other insets wait, primed, for the backing
            self._start_readers(0.0, exclude=self.session._replacing())
            self.start_deadline = time.monotonic() + 3.0
        except (media.MediaError, OSError) as e:
            self.session = None
            QMessageBox.warning(self, "Record", str(e))
            return
        self.state = "arming"
        self.stage.rec_slot = sid
        self.rec_act.setText("■ Stop")
        self.pos.setValue(0)
        self.statusBar().showMessage("Starting the camera and microphone…")

    def _abort_recording(self, msg):
        s, self.session = self.session, None
        if s:
            s.cancel()
        self._stop_readers()
        self._end_record_ui()
        QMessageBox.warning(self, "Record", msg)

    def _end_record_ui(self):
        self.state = "idle"
        self.stage.rec_slot = ""
        self.stage.banner = ""
        self.meter.setValue(0)
        self.rec_act.setText("● Record")
        self.still_timer.start()

    def _stop_recording(self):
        s = self.session
        if not s:
            return
        armed_only = self.state == "arming"
        self.state = "saving"
        self._stop_readers()
        s.stop()
        self.stage.banner = ""
        if armed_only or time.monotonic() < s.zero + 0.25:
            s.cancel()
            self.session = None
            self._end_record_ui()
            self.statusBar().showMessage("Recording cancelled.")
            return

        def done(take, err):
            self.session = None
            self._end_record_ui()
            if err:
                shutil.rmtree(s.tmp, ignore_errors=True)
                QMessageBox.warning(self, "Record", f"The take could not be saved:\n{err}")
                return
            self.voice_mtimes[take.id] = 0.0
            if 0 < s.camera_fps < 15:
                QMessageBox.warning(self, "Record",
                                    f"The camera only delivered {s.camera_fps:.0f} pictures per second "
                                    f"for {take.id}, so its movement will look jerky (30 is smooth).\n\n"
                                    "In VirtualBox, the Devices → Webcams passthrough is often this slow; "
                                    "passing the camera through as a USB device (Devices → USB) is usually "
                                    "much faster. `boxapella cameras --measure` checks the rate.")
            nxt = self.pr.first_empty_slot()
            self.statusBar().showMessage(f"Saved {take.id} ({fmt_time(take.duration)}) in inset {take.slot}."
                                         + (f" Next empty inset: {nxt}." if not self.pr.in_slot(nxt) else ""))
            if not self.pr.in_slot(nxt):
                self.stage.selected = nxt
            self._fill_table()
            self._changed()
        self._with_progress("Saving the take…", s.finalize, done)

    # ---- import / export
    def _import(self):
        if not self.pr or self.state != "idle":
            return
        p, _ = QFileDialog.getOpenFileName(self, "Import video", os.path.expanduser("~"),
                                           "Video (*.mp4 *.mov *.mkv *.webm *.avi);;All files (*)")
        if not p:
            return
        sid = self.stage.selected or self.pr.first_empty_slot()

        def done(t, err):
            if err:
                QMessageBox.warning(self, "Import", str(err))
                return
            self.voice_mtimes[t.id] = 0.0
            self.statusBar().showMessage(f"Imported {os.path.basename(p)} as {t.id} in inset {sid}.")
            self._fill_table()
            self._changed()
        self._with_progress(f"Importing {os.path.basename(p)}…",
                            lambda prog: project.import_video(self.pr, p, sid, prog), done)

    def _export(self):
        if not self.pr or self.state != "idle":
            return
        if not self.pr.shown():
            QMessageBox.information(self, "Export", "Record or import a take first.")
            return
        size, ok = QInputDialog.getItem(self, "Export", "Size", list(compose.SIZES),
                                        max(0, list(compose.SIZES).index(self.cfg["export_size"])
                                            if self.cfg["export_size"] in compose.SIZES else 0), False)
        if not ok:
            return
        self.cfg["export_size"] = size
        config.save(self.cfg)
        start = os.path.join(self.pr.path("exports"), f"{self.pr.name}.mp4")
        out, _ = QFileDialog.getSaveFileName(self, "Export master video", start, "MP4 video (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        os.makedirs(os.path.dirname(out), exist_ok=True)

        def done(d, err):
            if err:
                QMessageBox.warning(self, "Export", str(err))
            else:
                self.statusBar().showMessage(f"Exported {out} ({fmt_time(d)}).")
        self._with_progress("Exporting the master video…",
                            lambda prog: compose.export(self.pr, out, compose.SIZES[size], prog), done)

    def _delete_unused(self):
        if not self.pr or self.state != "idle":
            return
        unused = [t for t in self.pr.takes if not t.slot]
        if not unused:
            QMessageBox.information(self, "Boxapella", "Every take is in an inset.")
            return
        names = ", ".join(t.id for t in unused)
        if QMessageBox.question(self, "Delete takes", f"Delete {names} and their files?") \
                != QMessageBox.StandardButton.Yes:
            return
        for t in unused:
            for p in (self.pr.video(t), self.pr.proxy(t), self.pr.wav(t), self.pr.voice_wav(t),
                      self.pr.voice_settings(t)):
                self._remove(p)
            self.pr.takes.remove(t)
        self.pr.save()
        self._fill_table()

    def _settings(self):
        dlg = SettingsDialog(self, self.cfg)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.cfg.update(dlg.values())
            config.save(self.cfg)
            self._show_latency()

    # ---- shutdown
    def _stop_all(self):
        if self.session:
            self.session.cancel()
            self.session = None
        self.player.stop()
        self._stop_readers()
        self.state = "idle"

    def closeEvent(self, e):
        self._stop_all()
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().closeEvent(e)


def run(path: str | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Boxapella")
    app.setDesktopFileName("boxapella")
    w = MainWindow(path)
    w.show()
    return app.exec()
