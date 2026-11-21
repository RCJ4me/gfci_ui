from __future__ import annotations

import os
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from preview_plot import (  # noqa: E402
    InteractivePlotData,
    InteractivePlotWidget,
    PlotSeries,
    PreviewPlotWidget,
    PreviewSeries,
    minmax_envelope,
)


class PreviewPlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = QApplication.instance() or QApplication([])

    def _make_widget(self) -> PreviewPlotWidget:
        widget = PreviewPlotWidget()
        widget.resize(720, 420)
        time_ms = np.linspace(3000.0, 3032.0, 5000)
        amplitude = 8.0 * np.sin(
            2 * np.pi * (time_ms - 3000.0) / 5.0
        )
        widget.set_series(
            PreviewSeries(
                time_ms=time_ms,
                amplitude=amplitude,
                unit="mV",
                title="capture.csv | CH1 | Customize Scale Analysis",
            )
        )
        widget.show()
        self.app.processEvents()
        return widget

    def test_minmax_envelope_limits_points_to_pixel_bins(self) -> None:
        time_ms = np.linspace(0.0, 99.0, 1000)
        amplitude = np.sin(time_ms)

        envelope_time, minimums, maximums = minmax_envelope(
            time_ms,
            amplitude,
            50,
        )

        self.assertEqual(envelope_time.size, 50)
        self.assertEqual(minimums.size, 50)
        self.assertEqual(maximums.size, 50)
        self.assertTrue(np.all(minimums <= maximums))

    def test_hover_coordinates_use_three_decimals_without_units(self) -> None:
        self.assertEqual(
            PreviewPlotWidget._format_coordinate(3000.2),
            "3000.200",
        )
        self.assertEqual(
            PreviewPlotWidget._format_coordinate(3000.876),
            "3000.876",
        )
        self.assertEqual(PreviewPlotWidget._format_coordinate(-4.444), "-4.444")
        self.assertEqual(
            PreviewPlotWidget._format_hover_label(3000.2, 58.1234),
            "X:3000.200\nY:58.123",
        )

    def test_axis_ticks_use_integers(self) -> None:
        self.assertEqual(PreviewPlotWidget._format_axis_tick(3000.2), "3000")
        self.assertEqual(PreviewPlotWidget._format_axis_tick(3000.8), "3001")
        self.assertEqual(PreviewPlotWidget._format_axis_tick(-4.4), "-4")

    def test_hover_reports_nearest_real_sample(self) -> None:
        widget = self._make_widget()
        plot_rect = widget._plot_rect()
        QTest.mouseMove(
            widget,
            QPoint(
                int(plot_rect.center().x()),
                int(plot_rect.center().y()),
            ),
        )
        self.app.processEvents()

        self.assertIsNotNone(widget.hover_index)
        index = widget.hover_index
        self.assertGreaterEqual(
            float(widget.series.time_ms[index]),
            widget.visible_time_range[0],
        )
        self.assertLessEqual(
            float(widget.series.time_ms[index]),
            widget.visible_time_range[1],
        )
        image = widget.grab().toImage()
        self.assertFalse(image.isNull())
        self.assertTrue(
            any(
                image.pixelColor(x, y) != QColor("#ffffff")
                for y in range(0, image.height(), 12)
                for x in range(0, image.width(), 12)
            )
        )
        widget.close()

    def test_zoom_pan_and_double_click_reset(self) -> None:
        widget = self._make_widget()
        original_range = widget.visible_time_range
        center_x = widget._plot_rect().center().x()

        widget.zoom_at(center_x, 0.5)
        zoomed_span = (
            widget.visible_time_range[1] - widget.visible_time_range[0]
        )
        original_span = original_range[1] - original_range[0]
        self.assertLess(zoomed_span, original_span)

        before_pan = widget.visible_time_range
        widget.pan_by_pixels(20.0)
        self.assertLess(widget.visible_time_range[0], before_pan[0])

        QTest.mouseDClick(
            widget,
            Qt.MouseButton.LeftButton,
            pos=QPoint(
                int(widget._plot_rect().center().x()),
                int(widget._plot_rect().center().y()),
            ),
        )
        self.app.processEvents()
        self.assertAlmostEqual(
            widget.visible_time_range[0],
            original_range[0],
        )
        self.assertAlmostEqual(
            widget.visible_time_range[1],
            original_range[1],
        )
        widget.close()

    def test_time_domain_y_axis_is_symmetric_around_zero(self) -> None:
        widget = self._make_widget()

        low, high = widget.visible_amplitude_range

        self.assertLess(low, 0.0)
        self.assertGreater(high, 0.0)
        self.assertAlmostEqual(abs(low), high)
        self.assertEqual(low % 5.0, 0.0)
        self.assertEqual(high % 5.0, 0.0)
        widget.close()

    def test_y_axis_has_ten_intervals_and_uses_multiples_of_five(self) -> None:
        ticks = InteractivePlotWidget._y_tick_values(-100.0, 100.0)

        self.assertEqual(len(ticks), 11)
        self.assertIn(0.0, ticks)
        self.assertTrue(all(value % 5.0 == 0.0 for value in ticks))
        steps = np.diff(ticks)
        self.assertTrue(np.all(steps > 0))
        self.assertTrue(all(step % 5.0 == 0.0 for step in steps))

        fft_ticks = InteractivePlotWidget._y_tick_values(0.0, 100.0)
        self.assertEqual(len(fft_ticks), 11)
        self.assertEqual(fft_ticks[0], 0.0)
        self.assertIn(0.0, fft_ticks)

    def test_y_axis_stays_at_ten_intervals_after_zoom_and_pan(self) -> None:
        widget = self._make_widget()
        plot_rect = widget._plot_rect()

        widget.zoom_at(plot_rect.center().x(), 0.5)
        self.assertEqual(
            len(
                InteractivePlotWidget._y_tick_values(
                    *widget.visible_amplitude_range
                )
            ),
            11,
        )
        widget.pan_by_pixels(20.0)
        self.assertEqual(
            len(
                InteractivePlotWidget._y_tick_values(
                    *widget.visible_amplitude_range
                )
            ),
            11,
        )
        widget.close()

    def test_hover_chooses_nearest_primary_and_ignores_criteria(self) -> None:
        widget = InteractivePlotWidget()
        widget.resize(720, 420)
        x_values = np.linspace(0.0, 100.0, 101)
        low_series = PlotSeries(
            name="Low",
            x=x_values,
            y=np.full_like(x_values, -8.0),
            unit="mV",
            color="#147d64",
        )
        high_series = PlotSeries(
            name="High",
            x=x_values,
            y=np.full_like(x_values, 8.0),
            unit="mV",
            color="#2563eb",
        )
        criteria = PlotSeries(
            name="Pass Criteria",
            x=x_values,
            y=np.full_like(x_values, 20.0),
            unit="mV",
            color="#dc2626",
            interactive=False,
        )
        widget.set_plot_data(
            InteractivePlotData(
                title="multi",
                x_label="Time (ms)",
                y_label="Amplitude (mV)",
                x_scale="linear",
                symmetric_y=True,
                primary_series=[low_series, high_series],
                criteria_series=[criteria],
            )
        )
        widget.show()
        self.app.processEvents()
        plot_rect = widget._plot_rect()
        widget._last_mouse_y = widget._map_y(8.0, plot_rect)

        selected = widget.value_at_x_pixel(plot_rect.center().x())

        self.assertEqual(selected[0].name, "High")
        self.assertNotEqual(selected[0].name, "Pass Criteria")
        widget.close()

    def test_log_x_axis_zooms_and_hovers_positive_frequencies(self) -> None:
        widget = InteractivePlotWidget()
        widget.resize(720, 420)
        frequencies = np.geomspace(40.0, 100000.0, 300)
        spectrum = PlotSeries(
            name="Spectrum",
            x=frequencies,
            y=np.linspace(1.0, 5.0, frequencies.size),
            unit="mV",
            color="#4f46e5",
        )
        widget.set_plot_data(
            InteractivePlotData(
                title="fft",
                x_label="Frequency (Hz)",
                y_label="Amplitude (mV)",
                x_scale="log",
                symmetric_y=False,
                primary_series=[spectrum],
            )
        )
        widget.show()
        self.app.processEvents()
        original_span = np.log10(widget.visible_x_range[1]) - np.log10(
            widget.visible_x_range[0]
        )

        widget.zoom_at(widget._plot_rect().center().x(), 0.5)
        zoomed_span = np.log10(widget.visible_x_range[1]) - np.log10(
            widget.visible_x_range[0]
        )

        self.assertLess(zoomed_span, original_span)
        self.assertGreater(widget.visible_x_range[0], 0.0)
        self.assertAlmostEqual(widget.visible_amplitude_range[0], 0.0)
        widget.close()


if __name__ == "__main__":
    unittest.main()
