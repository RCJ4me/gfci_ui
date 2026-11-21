# -*- coding: utf-8 -*-
"""Load interactive Plot data from analysis CSV exports."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from preview_plot import InteractivePlotData, PlotSeries


PLOT_KIND_CONTINUOUS = "continuous"
PLOT_KIND_WINDOW = "window"
PLOT_KIND_FFT_RAW = "fft_raw"
PLOT_KIND_FFT_POST = "fft_post"
SERIES_COLORS = ("#147d64", "#c2410c", "#2563eb", "#9333ea", "#be123c")


@dataclass(frozen=True)
class PlotSource:
    """One selectable interactive plot backed by an analysis CSV."""

    label: str
    kind: str
    csv_path: str


def build_plot_sources(
    data_name: str,
    channel: str,
    output_dir: str | Path,
    time_start: float,
    time_end: float,
) -> list[PlotSource]:
    """Return the four Plot entries in the same order as the exported data."""
    root = Path(output_dir)
    channel_upper = channel.upper()
    return [
        PlotSource(
            label=f"Continuous Plot {data_name}",
            kind=PLOT_KIND_CONTINUOUS,
            csv_path=str(root / f"Continuous Plot {data_name}.csv"),
        ),
        PlotSource(
            label=(
                f"{channel_upper} Time Window "
                f"{time_start:.3f}-{time_end:.3f} s"
            ),
            kind=PLOT_KIND_WINDOW,
            csv_path=str(
                root
                / (
                    f"{channel_upper}_Plot_{data_name}_"
                    f"{time_start:.3f}s_{time_end:.3f}s.csv"
                )
            ),
        ),
        PlotSource(
            label=f"FFT Raw {data_name}",
            kind=PLOT_KIND_FFT_RAW,
            csv_path=str(root / f"FFT Raw RMS Signal {data_name}.csv"),
        ),
        PlotSource(
            label=f"FFT Post-letgo {data_name}",
            kind=PLOT_KIND_FFT_POST,
            csv_path=str(root / f"FFT Post Letgo RMS Signal {data_name}.csv"),
        ),
    ]


def _display_unit(header: str) -> str:
    match = re.search(r"\(([^()]*)\)", header)
    return match.group(1) if match else ""


def _series_name(header: str) -> str:
    return header.split(" (", 1)[0].strip().upper()


def _load_time_csv(source: PlotSource) -> InteractivePlotData:
    frame = pd.read_csv(source.csv_path)
    if "time_sec" not in frame:
        raise ValueError(f"Missing time_sec column in {source.csv_path}")
    time_ms = frame["time_sec"].to_numpy(dtype=float) * 1000.0
    series: list[PlotSeries] = []
    unit = ""
    for index, header in enumerate(
        column for column in frame.columns if column != "time_sec"
    ):
        unit = _display_unit(header)
        if source.kind == PLOT_KIND_WINDOW:
            raw_name = header.split(" (", 1)[0].strip().casefold()
            name = "Post-letgo" if raw_name == "post_letgo" else "Raw"
        else:
            name = _series_name(header)
        series.append(
            PlotSeries(
                name=name,
                x=time_ms,
                y=frame[header].to_numpy(dtype=float),
                unit=unit,
                color=SERIES_COLORS[index % len(SERIES_COLORS)],
                interactive=True,
            )
        )
    if not series:
        raise ValueError(f"No data series found in {source.csv_path}")
    return InteractivePlotData(
        title=source.label,
        x_label="Time (ms)",
        y_label=f"Amplitude ({unit})",
        x_scale="linear",
        symmetric_y=True,
        primary_series=series,
        criteria_series=[],
    )


def _load_fft_csv(source: PlotSource) -> InteractivePlotData:
    with open(source.csv_path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if row and row[0].strip().lower() == "frequency (hz)"
        ),
        None,
    )
    if header_index is None:
        raise ValueError(f"Missing FFT spectrum table in {source.csv_path}")

    header = rows[header_index]
    data_rows = []
    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip():
            break
        data_rows.append(row)
    if not data_rows:
        raise ValueError(f"Empty FFT spectrum table in {source.csv_path}")

    frequencies = np.asarray(
        [float(row[0]) for row in data_rows],
        dtype=float,
    )
    amplitudes = np.asarray(
        [float(row[1]) for row in data_rows],
        dtype=float,
    )
    valid = (frequencies > 0) & np.isfinite(frequencies) & np.isfinite(amplitudes)
    frequencies = frequencies[valid]
    amplitudes = amplitudes[valid]
    unit = _display_unit(header[1])

    primary = [
        PlotSeries(
            name=f"{source.label} Spectrum",
            x=frequencies,
            y=amplitudes,
            unit=unit,
            color="#4f46e5",
            interactive=True,
        )
    ]
    criteria: list[PlotSeries] = []
    threshold_column = next(
        (
            index
            for index, column in enumerate(header)
            if column.strip().lower().startswith("over-limit threshold")
        ),
        None,
    )
    if threshold_column is not None and len(header) > threshold_column:
        thresholds = np.asarray(
            [float(row[threshold_column]) for row in data_rows],
            dtype=float,
        )
        threshold_valid = valid & np.isfinite(thresholds)
        criteria.append(
            PlotSeries(
                name="Pass Criteria",
                x=frequencies[threshold_valid],
                y=thresholds[threshold_valid],
                unit=unit,
                color="#dc2626",
                interactive=False,
            )
        )

    return InteractivePlotData(
        title=source.label,
        x_label="Frequency (Hz)",
        y_label=f"Amplitude ({unit})",
        x_scale="log",
        symmetric_y=False,
        primary_series=primary,
        criteria_series=criteria,
    )


def load_plot_source(source: PlotSource) -> InteractivePlotData:
    """Load one PlotSource into renderer-ready arrays."""
    if not Path(source.csv_path).is_file():
        raise FileNotFoundError(f"Plot data not found: {source.csv_path}")
    if source.kind in {PLOT_KIND_CONTINUOUS, PLOT_KIND_WINDOW}:
        return _load_time_csv(source)
    if source.kind in {PLOT_KIND_FFT_RAW, PLOT_KIND_FFT_POST}:
        return _load_fft_csv(source)
    raise ValueError(f"Unsupported plot kind: {source.kind}")


class PlotDataWorker(QThread):
    """Load one interactive plot without blocking the GUI."""

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, source: PlotSource, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        try:
            self.ready.emit(load_plot_source(self.source))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
