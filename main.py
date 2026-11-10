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

from PyQt6.QtCore import QStandardPaths, QThread, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox, QStyle,
)


# Shown in the bottom-left corner of the window (see window.ui / lbl_version).
__version__ = "0.0.3.6"
APP_NAME = "GFCI Analyzer"
APP_USER_MODEL_ID = "GFCI.Analyzer"
APP_ICON_RELATIVE_PATH = Path("assets") / "torchdragon.ico"
DEFAULT_CSV_SAMPLE_INTERVAL = 3.2e-7
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

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
from report_export import export_markdown_to_pdf, render_report_html  # noqa: E402


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


def configure_windows_app_id() -> bool:
    """Give the Windows taskbar a stable identity for the application icon."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        set_app_id = shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        return set_app_id(APP_USER_MODEL_ID) == 0
    except Exception:  # Icon configuration is best-effort.
        return False


def apply_windows_taskbar_icon(
    window,
    icon_path: str | Path | None = None,
) -> bool:
    """Set both native window icons so Windows uses them in the taskbar."""
    if sys.platform != "win32":
        return False

    source = (
        Path(icon_path)
        if icon_path is not None
        else resource_path(APP_ICON_RELATIVE_PATH)
    )
    if not source.is_file():
        return False

    try:
        import ctypes

        hwnd = int(window.winId())
        if not hwnd:
            return False

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        load_image = user32.LoadImageW
        load_image.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        load_image.restype = ctypes.c_void_p

        icon_handle = load_image(
            None,
            str(source),
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not icon_handle:
            icon_handle = load_image(
                None,
                str(source),
                IMAGE_ICON,
                32,
                32,
                LR_LOADFROMFILE,
            )
        if not icon_handle:
            return False

        send_message = user32.SendMessageW
        send_message.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        send_message.restype = ctypes.c_ssize_t
        send_message(hwnd, WM_SETICON, ICON_SMALL, icon_handle)
        send_message(hwnd, WM_SETICON, ICON_BIG, icon_handle)
        window._windows_taskbar_icon = icon_handle
        return True
    except Exception:  # Icon configuration must not block application startup.
        return False


def _read_csv_metadata(file_path):
    """Return channel metadata and the data duration from a CSV header."""
    channels = []
    units = set()
    sample_interval = DEFAULT_CSV_SAMPLE_INTERVAL
    record_length = None
    data_row_count = 0
    header_found = False
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
                if header_found:
                    if any(value.strip() for value in row):
                        data_row_count += 1
                    continue
                if key == "time":
                    seen = set()
                    for value in row[1:]:
                        name = value.strip()
                        if name and name.casefold() not in seen:
                            seen.add(name.casefold())
                            channels.append(name)
                    header_found = True
                    if (
                        record_length is not None
                        and record_length > 1
                        and sample_interval > 0
                    ):
                        break
                elif key == "vertical units":
                    for value in row[1:]:
                        unit = value.strip()
                        if unit and unit.casefold() != "vertical units":
                            units.add(unit.upper())
                elif key == "sample interval" and len(row) > 1:
                    try:
                        sample_interval = float(row[1].strip())
                    except ValueError:
                        pass
                elif key == "record length" and len(row) > 1:
                    try:
                        record_length = int(float(row[1].strip()))
                    except ValueError:
                        pass
    except (OSError, csv.Error, LookupError):
        return [], set(), None

    if not header_found:
        return [], set(), None

    if (
        record_length is not None
        and record_length > 1
        and sample_interval > 0
    ):
        duration = (record_length - 1) * sample_interval
    elif data_row_count > 0 and sample_interval > 0:
        duration = (data_row_count - 1) * sample_interval
    else:
        duration = None
    return channels, units, duration


def read_csv_structure(file_path):
    """Return the channel names and vertical units declared in a CSV."""
    channels, units, _ = _read_csv_metadata(file_path)
    return channels, units


def read_csv_duration(file_path):
    """Return the zero-based data duration in seconds, when available."""
    _, _, duration = _read_csv_metadata(file_path)
    return duration


def find_csv_channels(file_path):
    """Return channel names declared in a CSV."""
    channels, _ = read_csv_structure(file_path)
    return channels


class AnalysisWorker(QThread):
    """Background analysis thread to keep the GUI responsive."""

    progress = pyqtSignal(int)          # 0-100, overall across all files
    stage = pyqtSignal(str)             # current pipeline stage, for the status bar
    log = pyqtSignal(str)               # log line
    file_done = pyqtSignal(str, str, str, str, str, str, str)
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
                    software_version=__version__,
                    **run_kwargs,
                )
                self.progress.emit(int((idx + 1) / total * 100))
                self.file_done.emit(
                    base,
                    result.time_plot_path or "",
                    getattr(result, "time_window_plot_path", None) or "",
                    getattr(result, "raw_fft_plot_path", None) or "",
                    result.fft_plot_path or "",
                    getattr(result, "report_path", None) or "",
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
        self.ui.mainLayout.setStretch(0, 39)
        self.ui.mainLayout.setStretch(1, 61)

        self.worker = None
        self._channel_user_selected = False
        self._curve_images = []
        self._current_report_path = None
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
        self.ui.btn_open_export_folder.clicked.connect(
            self.open_export_folder
        )
        self.ui.combo_channel.currentTextChanged.connect(
            self._on_channel_changed
        )

    def _setup_plot_views(self):
        """Wire the curve selector, zoom controls, and export-folder button."""
        self.ui.view_curve.set_placeholder(
            "No curve image generated in this run."
        )
        self.ui.combo_curve_image.setPlaceholderText(
            "No exported images in this run"
        )
        self.ui.combo_curve_image.currentIndexChanged.connect(
            self._on_curve_image_changed
        )
        self.ui.btn_zoom_in_curve.clicked.connect(
            self.ui.view_curve.zoom_in
        )
        self.ui.btn_zoom_out_curve.clicked.connect(
            self.ui.view_curve.zoom_out
        )
        self.ui.btn_fit_curve.clicked.connect(
            self.ui.view_curve.fit_to_width
        )
        self.ui.btn_open_export_folder.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self.ui.btn_open_export_folder.setEnabled(False)

    def _reset_curve_gallery(self):
        """Discard images from the previous run before starting a new one."""
        self._curve_images.clear()
        self.ui.combo_curve_image.clear()
        self.ui.view_curve.clear_image()

    def _on_curve_image_changed(self, index):
        path = self.ui.combo_curve_image.itemData(index)
        if not path:
            return
        self.show_image(self.ui.view_curve, str(path))

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

        time_start = self.ui.spin_time_start.value()
        time_end = self.ui.spin_time_end.value()
        invalid_windows = []
        for file_path in matching_files:
            duration = read_csv_duration(file_path)
            if duration is None:
                continue
            if time_start > duration or time_end > duration:
                invalid_windows.append(
                    f"{os.path.basename(file_path)}: "
                    f"data duration {duration:.6f} s"
                )
        if invalid_windows:
            QMessageBox.warning(
                self,
                "Time Window Out of Range",
                (
                    f"The selected time window "
                    f"({time_start:.3f}-{time_end:.3f} s) exceeds the "
                    "available data range (0.000000 s to the durations "
                    "shown below).\n\n"
                    + "\n".join(invalid_windows)
                    + "\n\nAnalysis was not started."
                ),
            )
            return

        params = {
            "time_start": time_start,
            "time_end": time_end,
            "fft_min": self.ui.spin_fft_min.value(),
            "fft_max": self.ui.spin_fft_max.value(),
            "channel": selected_channel.casefold(),
            "overlimit": self.ui.spin_overlimit.value(),
            "picture_format": self.ui.combo_format.currentIndex(),
            "output_dir": self.ui.edit_output_dir.text().strip() or "./export",
        }

        self.ui.txt_log.clear()
        self.ui.txt_report.clear()
        self._reset_curve_gallery()
        self._current_report_path = None
        self.ui.btn_open_export_folder.setEnabled(False)
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

    def on_file_done(
        self,
        base,
        time_png,
        time_window_png,
        raw_fft_png,
        fft_png,
        report_path,
        report_text,
    ):
        self.log(f"Finished: {base}")

        new_images = [
            path
            for path in (
                time_png,
                time_window_png,
                raw_fft_png,
                fft_png,
            )
            if path and os.path.exists(path)
        ]
        combo = self.ui.combo_curve_image
        post_letgo_index = -1
        combo.blockSignals(True)
        try:
            for path in new_images:
                self._curve_images.append(path)
                combo.addItem(Path(path).name, path)
                if path == fft_png:
                    post_letgo_index = combo.count() - 1
        finally:
            combo.blockSignals(False)

        if combo.count():
            target_index = (
                post_letgo_index
                if post_letgo_index >= 0
                else combo.count() - 1
            )
            if combo.currentIndex() == target_index:
                self._on_curve_image_changed(combo.currentIndex())
            else:
                combo.setCurrentIndex(target_index)

        report_file = Path(report_path) if report_path else None
        self._current_report_path = report_path or None

        if report_file is not None:
            try:
                pdf_path = export_markdown_to_pdf(report_file)
            except Exception as exc:  # noqa: BLE001
                message = (
                    f"Could not export the PDF report for {base}. "
                    "The Markdown report was kept."
                )
                self.log(f"!!! PDF export failed: {exc}")
                self._show_export_warning(message, str(exc))
            else:
                self._current_report_path = str(pdf_path)
                try:
                    report_file.unlink()
                except OSError as exc:
                    self.log(
                        f"!!! Could not remove temporary Markdown report: {exc}"
                    )
                    self._show_export_warning(
                        f"PDF exported for {base}, but the Markdown file "
                        "could not be removed.",
                        str(exc),
                    )
                else:
                    self.log(
                        f"PDF exported: {pdf_path}; Markdown removed"
                    )

        current_report = (
            Path(self._current_report_path)
            if self._current_report_path
            else None
        )
        self.ui.btn_open_export_folder.setEnabled(
            bool(
                current_report
                and current_report.is_file()
                and current_report.parent.is_dir()
            )
        )

        if report_text:
            self.show_report(
                report_text,
                report_file.parent if report_file is not None else None,
            )

    def open_export_folder(self):
        if not self._current_report_path:
            QMessageBox.warning(
                self,
                "Export Folder",
                "No successful analysis report is available yet.",
            )
            return

        export_dir = Path(self._current_report_path).parent
        if not export_dir.is_dir():
            message = f"The export folder does not exist:\n{export_dir}"
            self.log(message)
            QMessageBox.warning(self, "Export Folder", message)
            return

        if not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(export_dir.resolve()))
        ):
            message = f"Could not open the export folder:\n{export_dir}"
            self.log(message)
            QMessageBox.warning(self, "Export Folder", message)

    def on_finished(self, success, fail, skipped):
        self.ui.btn_run.setEnabled(True)
        self.set_progress(100)
        self.statusBar().showMessage(
            f"Analysis finished: {success} succeeded, {fail} failed, "
            f"{skipped} skipped",
            8000,
        )

    def show_report(
        self,
        report_text: str,
        base_dir: str | Path | None = None,
    ):
        """Render a Markdown report as an HTML preview."""
        document = self.ui.txt_report.document()
        if base_dir is not None:
            document.setBaseUrl(
                QUrl.fromLocalFile(f"{Path(base_dir).resolve()}{os.sep}")
            )
        html_text = render_report_html(
            report_text,
            base_dir,
            include_images=False,
            include_page_breaks=False,
        )
        self.ui.txt_report.setHtml(html_text)

    def _show_export_warning(self, message, detail):
        """Display a PDF warning without interrupting the completed analysis."""
        warning = QMessageBox(self)
        warning.setIcon(QMessageBox.Icon.Warning)
        warning.setWindowTitle("PDF Export")
        warning.setText(message)
        warning.setInformativeText(detail)
        warning.setStandardButtons(QMessageBox.StandardButton.Ok)
        warning.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        warning.setModal(False)
        warning.show()

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
    apply_windows_taskbar_icon(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
