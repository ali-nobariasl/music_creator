"""PyQt6 control panel for the focus-audio generator.

Run with:  python3 control_panel.py
"""

import os
import sys
import json
import shutil

from PyQt6 import QtCore, QtWidgets

import audio_engine
from audio_engine import Params


# ---------------------------------------------------------------------------
# A labelled slider paired with a spin box that stay in sync.
# ---------------------------------------------------------------------------
class ParamControl(QtWidgets.QWidget):
    valueChanged = QtCore.pyqtSignal(float)

    def __init__(self, label, minv, maxv, value, step, decimals, suffix=""):
        super().__init__()
        self._scale = 10 ** decimals
        self._guard = False

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel(label)
        self.label.setMinimumWidth(120)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider.setRange(int(minv * self._scale), int(maxv * self._scale))

        self.spin = QtWidgets.QDoubleSpinBox()
        self.spin.setRange(minv, maxv)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(95)

        lay.addWidget(self.label)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spin.valueChanged.connect(self._spin_changed)
        self.setValue(value)

    def _slider_changed(self, v):
        if self._guard:
            return
        self._guard = True
        val = v / self._scale
        self.spin.setValue(val)
        self._guard = False
        self.valueChanged.emit(val)

    def _spin_changed(self, v):
        if self._guard:
            return
        self._guard = True
        self.slider.setValue(int(round(v * self._scale)))
        self._guard = False
        self.valueChanged.emit(v)

    def value(self):
        return self.spin.value()

    def setValue(self, v):
        self._guard = True
        self.spin.setValue(v)
        self.slider.setValue(int(round(v * self._scale)))
        self._guard = False


# ---------------------------------------------------------------------------
# Background worker that renders the full track off the UI thread.
# ---------------------------------------------------------------------------
class GenerateWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int)   # seconds_done, total_seconds
    finished = QtCore.pyqtSignal(str, float)  # path, size_mb
    failed = QtCore.pyqtSignal(str)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @QtCore.pyqtSlot()
    def run(self):
        try:
            path = audio_engine.generate(
                self.params,
                progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancel,
            )
            if path is None:
                self.failed.emit("Cancelled.")
                return
            size_mb = os.path.getsize(path) / 1024 / 1024
            self.finished.emit(path, size_mb)
        except Exception as exc:  # surface any engine/ffmpeg error in the UI
            self.failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Main window.
# ---------------------------------------------------------------------------
class ControlPanel(QtWidgets.QMainWindow):
    PREVIEW_SECONDS = 10

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Focus Audio — Control Panel")
        self.setMinimumWidth(540)

        self._thread = None
        self._worker = None
        self._player = None  # QProcess running ffplay/aplay for the preview

        defaults = Params()
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        # --- Binaural group ------------------------------------------------
        binaural = QtWidgets.QGroupBox("Binaural")
        bl = QtWidgets.QVBoxLayout(binaural)
        self.carrier = ParamControl("Carrier freq", 50, 500, defaults.carrier_freq, 1, 1, " Hz")
        self.beat = ParamControl("Beat freq", 1, 40, defaults.beat_freq, 0.5, 1, " Hz")
        bl.addWidget(self.carrier)
        bl.addWidget(self.beat)
        root.addWidget(binaural)

        # --- Rhythm & mix group -------------------------------------------
        rhythm = QtWidgets.QGroupBox("Rhythm & Mix")
        rl = QtWidgets.QVBoxLayout(rhythm)
        self.bpm = ParamControl("Tempo", 30, 200, defaults.bpm, 1, 0, " BPM")
        self.binaural_vol = ParamControl("Binaural vol", 0, 1, defaults.binaural_vol, 0.01, 2)
        self.rhythm_vol = ParamControl("Rhythm vol", 0, 1, defaults.rhythm_vol, 0.01, 2)
        rl.addWidget(self.bpm)
        rl.addWidget(self.binaural_vol)
        rl.addWidget(self.rhythm_vol)
        root.addWidget(rhythm)

        # --- Output group --------------------------------------------------
        output = QtWidgets.QGroupBox("Output")
        ol = QtWidgets.QVBoxLayout(output)
        self.duration = ParamControl("Duration", 0.1, 12, defaults.duration_hours, 0.1, 1, " h")
        ol.addWidget(self.duration)

        file_row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit(os.path.abspath(defaults.output_file))
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        file_row.addWidget(QtWidgets.QLabel("File"))
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        ol.addLayout(file_row)
        root.addWidget(output)

        # --- Presets row ---------------------------------------------------
        preset_row = QtWidgets.QHBoxLayout()
        save_preset = QtWidgets.QPushButton("Save preset…")
        load_preset = QtWidgets.QPushButton("Load preset…")
        save_preset.clicked.connect(self._save_preset)
        load_preset.clicked.connect(self._load_preset)
        preset_row.addWidget(save_preset)
        preset_row.addWidget(load_preset)
        preset_row.addStretch(1)
        root.addLayout(preset_row)

        # --- Progress + status --------------------------------------------
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.status = QtWidgets.QLabel("Ready.")
        root.addWidget(self.progress)
        root.addWidget(self.status)

        # --- Action buttons ------------------------------------------------
        btn_row = QtWidgets.QHBoxLayout()
        self.preview_btn = QtWidgets.QPushButton(f"▶ Preview ({self.PREVIEW_SECONDS}s)")
        self.generate_btn = QtWidgets.QPushButton("Generate")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._toggle_preview)
        self.generate_btn.clicked.connect(self._start_generate)
        self.cancel_btn.clicked.connect(self._cancel_generate)
        btn_row.addWidget(self.preview_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.generate_btn)
        root.addLayout(btn_row)

        self._player_cmd = self._find_player()
        if self._player_cmd is None:
            self.preview_btn.setEnabled(False)
            self.preview_btn.setToolTip("No audio player found (install ffmpeg/ffplay).")

    # -- parameter <-> widget plumbing -------------------------------------
    def _params(self):
        return Params(
            carrier_freq=self.carrier.value(),
            beat_freq=self.beat.value(),
            bpm=int(self.bpm.value()),
            binaural_vol=self.binaural_vol.value(),
            rhythm_vol=self.rhythm_vol.value(),
            duration_hours=self.duration.value(),
            output_file=self.path_edit.text().strip(),
        )

    def _apply_params(self, p):
        self.carrier.setValue(p.carrier_freq)
        self.beat.setValue(p.beat_freq)
        self.bpm.setValue(p.bpm)
        self.binaural_vol.setValue(p.binaural_vol)
        self.rhythm_vol.setValue(p.rhythm_vol)
        self.duration.setValue(p.duration_hours)
        if p.output_file:
            self.path_edit.setText(p.output_file)

    # -- output / presets ---------------------------------------------------
    def _browse_output(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save audio as", self.path_edit.text(),
            "Audio (*.mp3 *.wav);;MP3 (*.mp3);;WAV (*.wav)")
        if path:
            self.path_edit.setText(path)

    def _save_preset(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save preset", "preset.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(self._params().to_dict(), f, indent=2)
            self.status.setText(f"Preset saved → {os.path.basename(path)}")
        except OSError as exc:
            self._error(f"Could not save preset:\n{exc}")

    def _load_preset(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load preset", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                self._apply_params(Params.from_dict(json.load(f)))
            self.status.setText(f"Preset loaded ← {os.path.basename(path)}")
        except (OSError, ValueError) as exc:
            self._error(f"Could not load preset:\n{exc}")

    # -- preview ------------------------------------------------------------
    @staticmethod
    def _find_player():
        for cmd in ("ffplay", "aplay", "pw-play", "paplay"):
            if shutil.which(cmd):
                return cmd
        return None

    def _player_args(self, wav):
        if self._player_cmd == "ffplay":
            return ["-nodisp", "-autoexit", "-loglevel", "quiet", wav]
        return [wav]  # aplay / pw-play / paplay take the file directly

    def _toggle_preview(self):
        if self._player is not None:  # currently playing -> stop
            self._stop_preview()
            return
        try:
            wav = audio_engine.render_preview(self._params(), self.PREVIEW_SECONDS)
        except Exception as exc:
            self._error(f"Could not render preview:\n{exc}")
            return

        self._player = QtCore.QProcess(self)
        self._player.finished.connect(self._stop_preview)
        self._player.errorOccurred.connect(lambda _e: self._stop_preview())
        self._player.start(self._player_cmd, self._player_args(wav))
        self.preview_btn.setText("■ Stop preview")
        self.status.setText("Playing preview…")

    def _stop_preview(self, *args):
        if self._player is not None:
            player, self._player = self._player, None
            player.finished.disconnect()
            player.kill()
            player.deleteLater()
        self.preview_btn.setText(f"▶ Preview ({self.PREVIEW_SECONDS}s)")
        if self.status.text() == "Playing preview…":
            self.status.setText("Ready.")

    # -- generation ---------------------------------------------------------
    def _start_generate(self):
        params = self._params()
        if not params.output_file:
            self._error("Please choose an output file.")
            return
        self._stop_preview()
        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText("Generating…")

        self._thread = QtCore.QThread(self)
        self._worker = GenerateWorker(params)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cancel_generate(self):
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Cancelling…")
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, done, total):
        self.progress.setValue(int(done / total * 100))
        self.status.setText(f"Generating…  {done // 60} / {total // 60} min")

    def _on_finished(self, path, size_mb):
        self._teardown_thread()
        self._set_busy(False)
        self.progress.setValue(100)
        self.status.setText(f"Done → {path}  ({size_mb:.1f} MB)")

    def _on_failed(self, msg):
        self._teardown_thread()
        self._set_busy(False)
        if msg == "Cancelled.":
            self.progress.setValue(0)
            self.status.setText("Cancelled.")
        else:
            self.status.setText("Failed.")
            self._error(msg)

    def _teardown_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = None
            self._worker = None

    def _set_busy(self, busy):
        self.generate_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        for w in (self.carrier, self.beat, self.bpm, self.binaural_vol,
                  self.rhythm_vol, self.duration, self.path_edit):
            w.setEnabled(not busy)

    # -- misc ---------------------------------------------------------------
    def _error(self, msg):
        QtWidgets.QMessageBox.warning(self, "Focus Audio", msg)

    def closeEvent(self, event):
        self._stop_preview()
        if self._worker is not None:
            self._worker.cancel()
        self._teardown_thread()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = ControlPanel()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
