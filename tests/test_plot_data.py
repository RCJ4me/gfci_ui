from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plot_data import (
    PLOT_KIND_CONTINUOUS,
    PLOT_KIND_FFT_POST,
    PLOT_KIND_FFT_RAW,
    PLOT_KIND_WINDOW,
    PlotSource,
    build_plot_sources,
    load_plot_source,
)


class PlotDataTests(unittest.TestCase):
    def test_build_plot_sources_uses_four_exported_csv_paths(self) -> None:
        sources = build_plot_sources(
            "capture",
            "ch1",
            "/tmp/export/capture",
            0.2,
            0.4,
        )

        self.assertEqual(
            [source.kind for source in sources],
            [
                PLOT_KIND_CONTINUOUS,
                PLOT_KIND_WINDOW,
                PLOT_KIND_FFT_RAW,
                PLOT_KIND_FFT_POST,
            ],
        )
        self.assertIn("CH1 Time Window 0.200-0.400 s", sources[1].label)

    def test_load_continuous_time_domain_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuous.csv"
            path.write_text(
                "time_sec,ch1 (mV),ch2 (mV)\n"
                "0.0,1.0,2.0\n"
                "0.1,3.0,4.0\n"
                "0.2,-2.0,-4.0\n",
                encoding="utf-8",
            )
            data = load_plot_source(
                PlotSource("Continuous", PLOT_KIND_CONTINUOUS, str(path))
            )

        self.assertTrue(data.symmetric_y)
        self.assertEqual(data.x_scale, "linear")
        self.assertEqual([series.name for series in data.primary_series], ["CH1", "CH2"])
        self.assertEqual(data.primary_series[0].unit, "mV")
        self.assertAlmostEqual(float(data.primary_series[0].x[-1]), 200.0)

    def test_load_window_csv_with_raw_and_post_letgo_series(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "window.csv"
            path.write_text(
                "time_sec,raw (mA),post_letgo (mA)\n"
                "0.0,1.0,0.5\n"
                "0.1,2.0,1.0\n",
                encoding="utf-8",
            )
            data = load_plot_source(
                PlotSource("Window", PLOT_KIND_WINDOW, str(path))
            )

        self.assertEqual(
            [series.name for series in data.primary_series],
            ["Raw", "Post-letgo"],
        )
        self.assertTrue(all(series.interactive for series in data.primary_series))

    def test_load_raw_fft_keeps_criteria_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.csv"
            path.write_text(
                "Value Type,RMS\nValue Unit,mV\n\n"
                "Frequency (Hz),FFT RMS Amplitude (mV),"
                "Over-limit Threshold (mV RMS),Result\n"
                "40,1.0,2.0,PASS\n"
                "60,3.0,2.5,FAIL\n"
                "\n=== Summary ===\n",
                encoding="utf-8",
            )
            data = load_plot_source(
                PlotSource("Raw FFT", PLOT_KIND_FFT_RAW, str(path))
            )

        self.assertEqual(data.x_scale, "log")
        self.assertFalse(data.symmetric_y)
        self.assertEqual(len(data.primary_series), 1)
        self.assertEqual(len(data.criteria_series), 1)
        self.assertTrue(data.primary_series[0].interactive)
        self.assertFalse(data.criteria_series[0].interactive)
        self.assertEqual(data.criteria_series[0].name, "Pass Criteria")

    def test_load_post_fft_has_no_pass_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "post.csv"
            path.write_text(
                "Value Type,RMS\nValue Unit,mV\n\n"
                "Frequency (Hz),FFT RMS Amplitude (mV)\n"
                "40,1.0\n60,2.0\n"
                "\n=== Summary ===\n",
                encoding="utf-8",
            )
            data = load_plot_source(
                PlotSource("Post FFT", PLOT_KIND_FFT_POST, str(path))
            )

        self.assertEqual(data.criteria_series, [])
        self.assertEqual(len(data.primary_series), 1)


if __name__ == "__main__":
    unittest.main()
