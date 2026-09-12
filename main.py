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

import os
import re
import sys
import traceback

import markdown
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox,
)

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

from window_ui import Ui_MainWindow  # noqa: E402


def find_csv_channels(file_path):
    """Return the channel names (e.g. ['CH1', 'CH2', 'CH3']) declared in a CSV."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if "TIME" in line.upper():
                    names = [name.strip() for name in line.split(",")]
                    return [n for n in names if re.fullmatch(r"CH\d+", n, re.IGNORECASE)]
    except OSError:
        return []
    return []


class AnalysisWorker(QThread):
    """Background analysis thread to keep the GUI responsive."""

    progress = pyqtSignal(int)          # 0-100
    log = pyqtSignal(str)               # log line
    file_done = pyqtSignal(str, str, str, str)  # filename, time plot, FFT plot, report
    finished_ok = pyqtSignal(int, int)  # success count, failure count

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
            self.finished_ok.emit(0, len(self.file_paths))
            return

        analysis_cfg = AnalysisConfig(
            time_start=self.params["time_start"],
            time_end=self.params["time_end"],
            fft_min_frequency=self.params["fft_min"],
            fft_max_frequency=self.params["fft_max"],
            # The GUI collects the threshold in mV; the analysis core expects V.
            overlimit_threshold=self.params["overlimit"] / 1000.0,
        )
        plot_cfg = PlotConfig(
            picture_format=self.params["picture_format"],
            show=False,
        )
        output_cfg = OutputConfig(output_dir=Path(self.params["output_dir"]))
        output_cfg.ensure()

        success_count = 0
        fail_count = 0
        total = len(self.file_paths)

        for idx, file_path in enumerate(self.file_paths):
            base = os.path.basename(file_path)
            self.log.emit(f"[{idx + 1}/{total}] Analyzing: {base}")
            try:
                result = run_pipeline(
                    file_path,
                    analysis_cfg=analysis_cfg,
                    plot_cfg=plot_cfg,
                    output_cfg=output_cfg,
                    channel=self.params["channel"],
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

        self.log.emit(f"All done: {success_count} succeeded, {fail_count} failed")
        self.finished_ok.emit(success_count, fail_count)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.worker = None
        self._channel_user_selected = False
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
        for i in range(self.ui.list_files.count()):
            for name in find_csv_channels(self.ui.list_files.item(i).text()):
                if name not in names:
                    names.append(name)
        if not names:
            return
        previous = self.ui.combo_channel.currentText()
        keep = self._channel_user_selected and previous in names
        self.ui.combo_channel.clear()
        self.ui.combo_channel.addItems(names)
        if keep:
            self.ui.combo_channel.setCurrentText(previous)
        elif "CH3" in names:
            self.ui.combo_channel.setCurrentText("CH3")

    def remove_file(self):
        row = self.ui.list_files.currentRow()
        if row >= 0:
            self.ui.list_files.takeItem(row)

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

        params = {
            "time_start": self.ui.spin_time_start.value(),
            "time_end": self.ui.spin_time_end.value(),
            "fft_min": self.ui.spin_fft_min.value(),
            "fft_max": self.ui.spin_fft_max.value(),
            "channel": self.ui.combo_channel.currentText().lower() or "ch3",
            "overlimit": self.ui.spin_overlimit.value(),
            "picture_format": self.ui.combo_format.currentIndex(),
            "output_dir": self.ui.edit_output_dir.text().strip() or "./export",
        }

        self.ui.txt_log.clear()
        self.ui.txt_report.clear()
        self.ui.progress_bar.setValue(0)
        self.log(f"Starting analysis of {len(files)} file(s) ...")
        self.log(f"FFT analysis channel: {self.ui.combo_channel.currentText()}")
        self.ui.btn_run.setEnabled(False)

        self.worker = AnalysisWorker(files, params, self)
        self.worker.progress.connect(self.ui.progress_bar.setValue)
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

    def on_finished(self, success, fail):
        self.ui.btn_run.setEnabled(True)
        self.ui.progress_bar.setValue(100)
        self.statusBar().showMessage(
            f"Analysis finished: {success} succeeded, {fail} failed", 8000
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
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
