# -*- coding: utf-8 -*-
"""
GFCI Oscilloscope Data Analysis Tool - PyQt6 GUI

Usage:
    python main.py

Dependencies:
    PyQt6, numpy, pandas, scipy, matplotlib, markdown

The UI layout is designed in Qt Designer; the source file is window.ui.
After layout changes, regenerate window_ui.py:
    pyuic6 -o window_ui.py window.ui
"""

import csv
import inspect
import os
import sys
import traceback
from pathlib import Path

import markdown
from PyQt6.QtCore import QStandardPaths, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox,
)


# Shown in the bottom-left corner of the window (see window.ui / lbl_version).
__version__ = "0.0.3.2"
APP_NAME = "GFCI Analyzer"
APP_USER_MODEL_ID = "GFCI.Analyzer"
APP_ICON_RELATIVE_PATH = Path("assets") / "torchdragon.ico"

# Analysis engine: prefer the copy bundled with this GUI, then the sibling repo.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ANALYZER_CANDIDATES = [
    _HERE,                                                     # bundled copy
    os.path.abspath(os.path.join(_HERE, "..", "gfci_analysis_refactored")),
]
# Keep the GUI directory importable and add available analysis engines so the
# bundled copy wins over the sibling repository.
_IMPORT_PATHS = [_HERE]
for _path in _ANALYZER_CANDIDATES:
    if _path != _HERE and os.path.isdir(os.path.join(_path, "gfci_analysis")):
        _IMPORT_PATHS.append(_path)

for _path in _ANALYZER_CANDIDATES + [_HERE]:
    while _path in sys.path:
        sys.path.remove(_path)
for _path in reversed(_IMPORT_PATHS):
    sys.path.insert(0, _path)

from window import Ui_MainWindow  # noqa: E402


def resource_path(relative_path):
    """Return an application resource path in source and PyInstaller builds."""
    root = Path(getattr(sys, "_MEIPASS", _HERE))
    return root / relative_path


def default_output_directory():
    """Return a writable output directory suitable for a packaged GUI app."""
    documents = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    root = Path(documents) if documents else Path.home()
    return str((root / "GFCI Export").resolve())


def configure_matplotlib_cache():
    """Keep Matplotlib's cache inside a writable per-user cache directory."""
    cache_root = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.CacheLocation
    )
    if not cache_root:
        return
    cache_dir = Path(cache_root) / "matplotlib"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))


def configure_windows_app_id():
    """Give the Windows taskbar a stable identity for the application icon."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        pass


def read_csv_structure(file_path):
    """Return the channel names and vertical units declared in a CSV."""
    channels = []
    units = set()
    try:
        with open(
            file_path,
            "r",
            encoding="utf-8-sig",
            errors="ignore",
            newline="",
        ) as handle:
            for row in csv.reader(handle):
                if not row:
                    continue
                key = row[0].strip().casefold()
                if key == "time":
                    seen = set()
                    for value in row[1:]:
                        name = value.strip()
                        if name and name.casefold() not in seen:
                            seen.add(name.casefold())
                            channels.append(name)
                    break
                if key == "vertical units":
                    for value in row[1:]:
                        unit = value.strip()
                        if unit and unit.casefold() != "vertical units":
                            units.add(unit.upper())
    except (OSError, csv.Error):
        return [], set()
    return channels, units


def find_csv_channels(file_path):
    """Return channel names declared in a CSV."""
    channels, _ = read_csv_structure(file_path)
    return channels


class AnalysisWorker(QThread):
    """Background analysis thread to keep the GUI responsive."""

    progress = pyqtSignal(int)          # 0-100, overall across all files
    stage = pyqtSignal(str)             # current pipeline stage, for the status bar
    log = pyqtSignal(str)               # log line
    file_done = pyqtSignal(str, str, str, str)  # filename, time plot, FFT plot, report
    finished_ok = pyqtSignal(int, int, int)  # success, failure, skipped

    def __init__(self, file_paths, params, parent=None):
        super().__init__(parent)
        self.file_paths = file_paths
        self.params = params

    def run(self):
        from pathlib import Path

        # Verify imports up front so failures produce a friendly error
        try:
            import numpy  # noqa: F401
            from gfci_analysis import (  # noqa: F401
                AnalysisConfig,
                OutputConfig,
                PlotConfig,
                run_pipeline,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"Could not import the gfci_analysis engine: {exc}")
            self.log.emit(
                "Make sure the bundled gfci_analysis/ package is present and "
                "numpy/pandas/scipy/matplotlib are installed."
            )
            self.finished_ok.emit(0, len(self.file_paths), 0)
            return

        analysis_cfg = AnalysisConfig(
            time_start=self.params["time_start"],
            time_end=self.params["time_end"],
            fft_min_frequency=self.params["fft_min"],
            fft_max_frequency=self.params["fft_max"],
            # The GUI collects in thousandths of the source unit (mV or mA).
            overlimit_threshold=self.params["overlimit"] / 1000.0,
        )
        plot_cfg = PlotConfig(
            picture_format=self.params["picture_format"],
            show=False,
        )
        output_cfg = OutputConfig(output_dir=Path(self.params["output_dir"]))
        output_cfg.ensure()

        # Older engine revisions have no stage hook; fall back to per-file progress.
        reports_stages = (
            "progress_callback" in inspect.signature(run_pipeline).parameters
        )
        if not reports_stages:
            self.log.emit(
                "This gfci_analysis engine does not report pipeline stages; "
                "the progress bar advances once per file."
            )

        success_count = 0
        fail_count = 0
        skipped_count = 0
        total = len(self.file_paths)
        selected_channel = self.params["channel"].casefold()

        for idx, file_path in enumerate(self.file_paths):
            base = os.path.basename(file_path)
            channels, units = read_csv_structure(file_path)

            if len(units) > 1:
                fail_count += 1
                self.progress.emit(int((idx + 1) / total * 100))
                self.log.emit(
                    f"!!! Analysis failed {base}: the CSV contains mixed "
                    f"vertical units ({', '.join(sorted(units))})."
                )
                continue

            if not channels:
                fail_count += 1
                self.progress.emit(int((idx + 1) / total * 100))
                self.log.emit(
                    f"!!! Analysis failed {base}: no channel columns were found."
                )
                continue

            if selected_channel not in {name.casefold() for name in channels}:
                skipped_count += 1
                self.progress.emit(int((idx + 1) / total * 100))
                self.log.emit(
                    f"Skipped {base}: channel {self.params['channel']} "
                    f"is not present (available: {', '.join(channels)})."
                )
                continue

            self.log.emit(f"[{idx + 1}/{total}] Analyzing: {base}")

            def report_stage(fraction, label, idx=idx, base=base):
                """Scale one file's 0-1 progress into the overall percentage."""
                self.progress.emit(int(round((idx + fraction) / total * 100.0)))
                self.stage.emit(f"{base} - {label}")

            try:
                run_kwargs = {"channel": selected_channel}
                if reports_stages:
                    run_kwargs["progress_callback"] = report_stage
                result = run_pipeline(
                    file_path,
                    analysis_cfg=analysis_cfg,
                    plot_cfg=plot_cfg,
                    output_cfg=output_cfg,
                    **run_kwargs,
                )
                self.progress.emit(int((idx + 1) / total * 100))
                self.file_done.emit(
                    base,
                    result.time_plot_path or "",
                    result.fft_plot_path or "",
                    result.report_text or "",
                )
                success_count += 1
            except Exception as exc:  # noqa: BLE001
                fail_count += 1
                self.log.emit(f"!!! Analysis failed {base}: {exc}")
                self.log.emit(traceback.format_exc())

        self.log.emit(
            f"All done: {success_count} succeeded, {fail_count} failed, "
            f"{skipped_count} skipped"
        )
        self.finished_ok.emit(success_count, fail_count, skipped_count)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.worker = None
        self._channel_user_selected = False
        self._progress_target = 0
        self._progress_ceiling = 0
        self._progress_ticks = 0

        # Eases the progress bar toward the latest stage value so the jumps
        # between pipeline stages do not look abrupt.
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(20)
        self._progress_timer.timeout.connect(self._advance_progress)

        self.ui.lbl_version.setText(f"Version {__version__}")
        self.ui.edit_output_dir.setText(default_output_directory())
        self._connect_signals()
        self._setup_plot_views()

    def _connect_signals(self):
        self.ui.btn_add_files.clicked.connect(self.add_files)
        self.ui.btn_remove_file.clicked.connect(self.remove_file)
        self.ui.btn_clear_files.clicked.connect(self.clear_files)
        self.ui.btn_browse_dir.clicked.connect(self.browse_output_dir)
        self.ui.btn_run.clicked.connect(self.run_analysis)
        self.ui.combo_channel.currentTextChanged.connect(
            self._on_channel_changed
        )

    def _setup_plot_views(self):
        """Wire the zoom controls and empty-state text of both plot tabs."""
        self.ui.view_time.set_placeholder("No time-domain plot generated yet.")
        self.ui.view_fft.set_placeholder("No FFT plot generated yet.")
        self.ui.btn_zoom_in_time.clicked.connect(self.ui.view_time.zoom_in)
        self.ui.btn_zoom_out_time.clicked.connect(self.ui.view_time.zoom_out)
        self.ui.btn_fit_time.clicked.connect(self.ui.view_time.fit_to_width)
        self.ui.btn_zoom_in_fft.clicked.connect(self.ui.view_fft.zoom_in)
        self.ui.btn_zoom_out_fft.clicked.connect(self.ui.view_fft.zoom_out)
        self.ui.btn_fit_fft.clicked.connect(self.ui.view_fft.fit_to_width)

    def _on_channel_changed(self, _text):
        self._channel_user_selected = True
        self._update_threshold_label()

    # ---------- Progress ----------
    # While a stage runs the bar is allowed to creep this far past the value
    # reported for that stage, so long steps (reading a large CSV) still move.
    CREEP_POINTS = 4
    CREEP_TICKS = 20          # timer ticks per crept point (20 ms each)

    def set_progress(self, value: int):
        """Point the progress bar at *value*; the bar then eases toward it."""
        self._progress_target = max(0, min(100, int(value)))
        self._progress_ceiling = min(100, self._progress_target + self.CREEP_POINTS)
        self._progress_ticks = 0
        if self._progress_target == 0:
            self._progress_timer.stop()
            self.ui.progress_bar.setValue(0)
        elif not self._progress_timer.isActive():
            self._progress_timer.start()

    def _advance_progress(self):
        bar = self.ui.progress_bar
        current = bar.value()
        if current >= self._progress_ceiling:
            self._progress_timer.stop()
            return
        if current < self._progress_target:
            step = max(1, (self._progress_target - current) // 4)
        else:
            # Stage finished reporting but is still working: creep slowly.
            self._progress_ticks += 1
            if self._progress_ticks < self.CREEP_TICKS:
                return
            self._progress_ticks = 0
            step = 1
        bar.setValue(min(self._progress_ceiling, current + step))

    def on_stage(self, text):
        self.statusBar().showMessage(text)

    # ---------- File operations ----------
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select oscilloscope CSV files", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        for f in files:
            if self.ui.list_files.findItems(f, Qt.MatchFlag.MatchExactly):
                continue
            self.ui.list_files.addItem(f)
        self._refresh_channels()

    def _refresh_channels(self):
        """Offer the channel names actually present in the loaded CSV files."""
        names = []
        seen = set()
        for i in range(self.ui.list_files.count()):
            channels, _ = read_csv_structure(
                self.ui.list_files.item(i).text()
            )
            for name in channels:
                key = name.casefold()
                if key not in seen:
                    seen.add(key)
                    names.append(name)

        previous = self.ui.combo_channel.currentText()
        keep = self._channel_user_selected and any(
            previous.casefold() == name.casefold() for name in names
        )

        self.ui.combo_channel.blockSignals(True)
        try:
            self.ui.combo_channel.clear()
            self.ui.combo_channel.addItems(names)
            if keep:
                self.ui.combo_channel.setCurrentText(previous)
            elif any(name.casefold() == "ch3" for name in names):
                self.ui.combo_channel.setCurrentText("CH3")
        finally:
            self.ui.combo_channel.blockSignals(False)

        if not names:
            self._channel_user_selected = False
        self._update_threshold_label()

    def _selected_value_unit(self):
        selected = self.ui.combo_channel.currentText().casefold()
        if not selected:
            return "V"

        units = set()
        for i in range(self.ui.list_files.count()):
            channels, file_units = read_csv_structure(
                self.ui.list_files.item(i).text()
            )
            if any(name.casefold() == selected for name in channels):
                units.update(file_units or {"V"})

        if not units:
            return "V"
        if len(units) == 1:
            return next(iter(units))
        return None

    def _update_threshold_label(self):
        unit = self._selected_value_unit()
        if unit == "A":
            suffix = "mA"
        elif unit == "V":
            suffix = "mV"
        else:
            suffix = "mixed V/A"
        self.ui.lbl_overlimit.setText(
            f"Base Over-limit Threshold ({suffix})"
        )

    def remove_file(self):
        row = self.ui.list_files.currentRow()
        if row >= 0:
            self.ui.list_files.takeItem(row)
            self._refresh_channels()

    def clear_files(self):
        self.ui.list_files.clear()
        self._refresh_channels()

    def browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory",
                                                self.ui.edit_output_dir.text())
        if path:
            self.ui.edit_output_dir.setText(path)

    # ---------- Run ----------
    def run_analysis(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Notice", "An analysis is already running. Please wait.")
            return

        files = [self.ui.list_files.item(i).text()
                 for i in range(self.ui.list_files.count())]
        if not files:
            QMessageBox.warning(self, "Notice", "Please add CSV files to analyze first.")
            return

        all_units = set()
        mixed_unit_files = []
        for file_path in files:
            channels, units = read_csv_structure(file_path)
            if not channels:
                continue
            if len(units) > 1:
                mixed_unit_files.append(os.path.basename(file_path))
            all_units.update(units or {"V"})

        if mixed_unit_files:
            QMessageBox.warning(
                self,
                "Mixed Units",
                "These files declare multiple vertical units:\n"
                + "\n".join(mixed_unit_files),
            )
            return
        if len(all_units) > 1:
            QMessageBox.warning(
                self,
                "Mixed Units",
                "The selected files mix voltage (V) and current (A). "
                "Analyze them in separate runs so the threshold unit is unambiguous.",
            )
            return

        selected_channel = self.ui.combo_channel.currentText().strip()
        if not selected_channel:
            QMessageBox.warning(
                self,
                "Notice",
                "No analysis channel is available in the selected CSV files.",
            )
            return
        matching_files = [
            file_path
            for file_path in files
            if selected_channel.casefold()
            in {
                name.casefold()
                for name in read_csv_structure(file_path)[0]
            }
        ]
        if not matching_files:
            QMessageBox.warning(
                self,
                "Notice",
                f"Channel {selected_channel} is not present in the selected files.",
            )
            return

        params = {
            "time_start": self.ui.spin_time_start.value(),
            "time_end": self.ui.spin_time_end.value(),
            "fft_min": self.ui.spin_fft_min.value(),
            "fft_max": self.ui.spin_fft_max.value(),
            "channel": selected_channel.casefold(),
            "overlimit": self.ui.spin_overlimit.value(),
            "picture_format": self.ui.combo_format.currentIndex(),
            "output_dir": self.ui.edit_output_dir.text().strip() or "./export",
        }

        self.ui.txt_log.clear()
        self.ui.txt_report.clear()
        self.set_progress(0)
        self.log(f"Starting analysis of {len(files)} file(s) ...")
        self.log(f"FFT analysis channel: {self.ui.combo_channel.currentText()}")
        self.ui.btn_run.setEnabled(False)

        self.worker = AnalysisWorker(files, params, self)
        self.worker.progress.connect(self.set_progress)
        self.worker.stage.connect(self.on_stage)
        self.worker.log.connect(self.log)
        self.worker.file_done.connect(self.on_file_done)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.start()

    def on_file_done(self, base, time_png, fft_png, report_text):
        self.log(f"Finished: {base}")
        if time_png and os.path.exists(time_png):
            self.show_image(self.ui.view_time, time_png)
        if fft_png and os.path.exists(fft_png):
            self.show_image(self.ui.view_fft, fft_png)
        if report_text:
            self.show_report(report_text)

    def on_finished(self, success, fail, skipped):
        self.ui.btn_run.setEnabled(True)
        self.set_progress(100)
        self.statusBar().showMessage(
            f"Analysis finished: {success} succeeded, {fail} failed, "
            f"{skipped} skipped",
            8000,
        )

    def show_report(self, report_text: str):
        """Render a Markdown report as an HTML preview."""
        html = markdown.markdown(
            report_text,
            extensions=["tables", "fenced_code"],
            output_format="html5",
        )
        styled_html = (
            "<style>"
            "body { font-family: 'Helvetica Neue', Arial, sans-serif; }"
            "table { border-collapse: collapse; margin: 8px 0; }"
            "th, td { border: 1px solid #bbb; padding: 4px 10px; }"
            "th { background: #e8eef7; }"
            "blockquote { color: #666; border-left: 3px solid #ccc; "
            "margin-left: 0; padding-left: 12px; }"
            "h1 { font-size: 20pt; } h2 { font-size: 15pt; } h3 { font-size: 12pt; }"
            "</style>"
            + html
        )
        self.ui.txt_report.setHtml(styled_html)

    def show_image(self, view, path):
        if not view.set_image(path):
            self.log(f"Could not load image: {path}")

    def log(self, message):
        self.ui.txt_log.appendPlainText(message)


def main():
    configure_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("GFCI")
    app_icon = QIcon(str(resource_path(APP_ICON_RELATIVE_PATH)))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    configure_matplotlib_cache()
    window = MainWindow()
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
