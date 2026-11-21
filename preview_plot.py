# -*- coding: utf-8 -*-
"""Interactive plotting widgets for Preview and analysis Plot tabs."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget


# User-tunable Preview font sizes.
x_title_font_size = 14
y_title_font_size = 14
user_label_font_size = 14
x_y_unit_font_size = 14


@dataclass
class PlotSeries:
    """One drawable series in an interactive plot."""

    name: str
    x: np.ndarray
    y: np.ndarray
    unit: str
    color: str
    interactive: bool = True

    @property
    def point_count(self) -> int:
        return int(self.x.size)


@dataclass
class InteractivePlotData:
    """Renderer-ready data for one Preview or Plot tab."""

    title: str
    x_label: str
    y_label: str
    x_scale: str
    symmetric_y: bool
    primary_series: list[PlotSeries]
    criteria_series: list[PlotSeries] = field(default_factory=list)

    @property
    def all_series(self) -> list[PlotSeries]:
        return [*self.primary_series, *self.criteria_series]


@dataclass
class PreviewSeries:
    """Raw waveform data prepared for the interactive Preview tab."""

    time_ms: np.ndarray
    amplitude: np.ndarray
    unit: str
    title: str

    @property
    def point_count(self) -> int:
        return int(self.time_ms.size)


def minmax_envelope(
    x_values: np.ndarray,
    y_values: np.ndarray,
    bin_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reduce a waveform to one min/max envelope per horizontal pixel."""
    if bin_count <= 0:
        raise ValueError("bin_count must be positive")
    if x_values.size == 0:
        return x_values, y_values, y_values
    if x_values.size <= bin_count * 2:
        return x_values, y_values, y_values

    starts = np.linspace(
        0,
        x_values.size,
        bin_count + 1,
        endpoint=True,
        dtype=np.int64,
    )[:-1]
    minimums = np.minimum.reduceat(y_values, starts)
    maximums = np.maximum.reduceat(y_values, starts)
    ends = np.concatenate((starts[1:], np.array([x_values.size])))
    centers = np.minimum((starts + ends) // 2, x_values.size - 1)
    return x_values[centers], minimums, maximums


class InteractivePlotWidget(QWidget):
    """Paint zoomable series and report the nearest primary curve on hover."""

    LEFT_MARGIN = 90
    RIGHT_MARGIN = 22
    TOP_MARGIN = 36
    BOTTOM_MARGIN = 64
    GRID_COLOR = QColor("#dfe5ec")
    AXIS_COLOR = QColor("#46515c")
    ZERO_COLOR = QColor("#111827")
    HOVER_COLOR = QColor("#b42318")
    TEXT_COLOR = QColor("#20242a")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._plot_data: InteractivePlotData | None = None
        self._view_x = (0.0, 1.0)
        self._view_y = (-1.0, 1.0)
        self._plot_x_min = 0.0
        self._plot_x_max = 1.0
        self._hover_series_index: int | None = None
        self._hover_index: int | None = None
        self._dragging = False
        self._drag_last_x = 0.0
        self._last_mouse_y = 0.0
        self._placeholder = "No plot data."

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 280)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    @property
    def plot_data(self) -> InteractivePlotData | None:
        return self._plot_data

    @property
    def hover_index(self) -> int | None:
        return self._hover_index

    @property
    def hover_series_name(self) -> str | None:
        if self._plot_data is None or self._hover_series_index is None:
            return None
        return self._plot_data.primary_series[self._hover_series_index].name

    @property
    def visible_time_range(self) -> tuple[float, float]:
        return self._view_x

    @property
    def visible_x_range(self) -> tuple[float, float]:
        return self._view_x

    @property
    def visible_amplitude_range(self) -> tuple[float, float]:
        return self._view_y

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        if self._plot_data is None:
            self.update()

    def has_data(self) -> bool:
        return self._plot_data is not None

    def set_plot_data(self, plot_data: InteractivePlotData) -> None:
        if not plot_data.primary_series:
            raise ValueError("Interactive plot requires at least one primary series")
        if plot_data.x_scale not in {"linear", "log"}:
            raise ValueError(f"Unsupported x scale: {plot_data.x_scale}")
        all_series = plot_data.all_series
        for series in all_series:
            if series.x.size != series.y.size:
                raise ValueError(f"Series {series.name} has mismatched arrays")
            if series.x.size < 2:
                raise ValueError(f"Series {series.name} requires at least two points")
            if not np.all(np.diff(series.x) >= 0):
                raise ValueError(f"Series {series.name} x values must be sorted")
            if plot_data.x_scale == "log" and np.any(series.x <= 0):
                raise ValueError(
                    f"Series {series.name} requires positive x values for log scale"
                )
        self._plot_data = plot_data
        self._plot_x_min = min(float(np.min(s.x)) for s in all_series)
        self._plot_x_max = max(float(np.max(s.x)) for s in all_series)
        self.reset_view()

    def clear_plot(self) -> None:
        self._plot_data = None
        self._hover_series_index = None
        self._hover_index = None
        self._dragging = False
        self._view_x = (0.0, 1.0)
        self._view_y = (-1.0, 1.0)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def reset_view(self) -> None:
        if self._plot_data is None:
            return
        self._view_x = (self._plot_x_min, self._plot_x_max)
        if self._view_x[1] <= self._view_x[0]:
            self._view_x = (self._view_x[0], self._view_x[0] + 1.0)
        self._update_y_range()
        self._hover_series_index = None
        self._hover_index = None
        self.update()

    def fit_to_width(self) -> None:
        self.reset_view()

    def zoom_in(self) -> None:
        self.zoom_at(self._plot_rect().center().x(), 0.8)

    def zoom_out(self) -> None:
        self.zoom_at(self._plot_rect().center().x(), 1.25)

    def zoom_at(self, x_position: float, factor: float) -> None:
        if self._plot_data is None or factor <= 0:
            return
        plot_rect = self._plot_rect()
        if plot_rect.width() <= 0:
            return
        fraction = min(
            max((x_position - plot_rect.left()) / plot_rect.width(), 0.0),
            1.0,
        )
        low, high = self._transformed_x_range()
        anchor = low + fraction * (high - low)
        minimum_span = self._minimum_transformed_x_span()
        target_span = min(
            max((high - low) * factor, minimum_span),
            self._full_transformed_x_span(),
        )
        new_low = anchor - fraction * target_span
        self._view_x = self._clamped_x_range(
            self._inverse_x(new_low),
            self._inverse_x(new_low + target_span),
        )
        self._update_y_range()
        self._clear_hover()

    def pan_by_pixels(self, delta_pixels: float) -> None:
        if self._plot_data is None:
            return
        plot_rect = self._plot_rect()
        if plot_rect.width() <= 0:
            return
        low, high = self._transformed_x_range()
        shift = -float(delta_pixels) / plot_rect.width() * (high - low)
        self._view_x = self._clamped_x_range(
            self._inverse_x(low + shift),
            self._inverse_x(high + shift),
        )
        self._update_y_range()
        self._clear_hover()

    def value_at_x_pixel(
        self,
        x_position: float,
    ) -> tuple[PlotSeries, int, float, float] | None:
        if self._plot_data is None:
            return None
        plot_rect = self._plot_rect()
        if plot_rect.width() <= 0:
            return None
        clamped_x = min(max(float(x_position), plot_rect.left()), plot_rect.right())
        fraction = (clamped_x - plot_rect.left()) / plot_rect.width()
        target_x = self._x_at_fraction(fraction)
        best = None
        best_distance = float("inf")
        for series in self._plot_data.primary_series:
            index = self._nearest_index(series.x, target_x)
            screen_y = self._map_y(float(series.y[index]), plot_rect)
            distance = abs(screen_y - self._last_mouse_y)
            if distance < best_distance:
                best_distance = distance
                best = (
                    series,
                    index,
                    float(series.x[index]),
                    float(series.y[index]),
                )
        return best

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        if self._plot_data is None:
            painter.setPen(QColor("#7a8490"))
            painter.setFont(QFont("Helvetica Neue", 12))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._placeholder,
            )
            return

        plot_rect = self._plot_rect()
        self._draw_title(painter)
        self._draw_grid_and_axes(painter, plot_rect)
        painter.save()
        painter.setClipRect(plot_rect)
        self._draw_all_series(painter, plot_rect)
        self._draw_legend(painter, plot_rect)
        self._draw_hover(painter, plot_rect)
        painter.restore()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._plot_data is not None
            and self._plot_rect().contains(event.position())
        ):
            self._dragging = True
            self._drag_last_x = event.position().x()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._last_mouse_y = event.position().y()
        if self._dragging:
            current_x = event.position().x()
            self.pan_by_pixels(current_x - self._drag_last_x)
            self._drag_last_x = current_x
            event.accept()
            return
        self._update_hover(event.position())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self._last_mouse_y = event.position().y()
            self._update_hover(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:
        self._clear_hover()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._plot_data is None:
            return
        factor = 0.8 if event.angleDelta().y() > 0 else 1.25
        self.zoom_at(event.position().x(), factor)
        event.accept()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self.LEFT_MARGIN,
            self.TOP_MARGIN,
            max(1.0, self.width() - self.LEFT_MARGIN - self.RIGHT_MARGIN),
            max(1.0, self.height() - self.TOP_MARGIN - self.BOTTOM_MARGIN),
        )

    def _transformed_x_range(self) -> tuple[float, float]:
        return self._transform_x(self._view_x[0]), self._transform_x(
            self._view_x[1]
        )

    def _full_transformed_x_span(self) -> float:
        return max(
            self._transform_x(self._plot_x_max)
            - self._transform_x(self._plot_x_min),
            1e-9,
        )

    def _minimum_transformed_x_span(self) -> float:
        if self._plot_data is None:
            return 1e-6
        if self._plot_data.x_scale == "log":
            return max(self._full_transformed_x_span() * 0.002, 1e-9)
        minimum_interval = min(
            float(np.min(np.diff(series.x)))
            for series in self._plot_data.primary_series
            if series.x.size > 1
        )
        return max(minimum_interval * 2.0, 1e-6)

    def _transform_x(self, value: float) -> float:
        if self._plot_data is not None and self._plot_data.x_scale == "log":
            return float(np.log10(max(value, np.finfo(float).tiny)))
        return float(value)

    def _inverse_x(self, value: float) -> float:
        if self._plot_data is not None and self._plot_data.x_scale == "log":
            return float(np.power(10.0, value))
        return float(value)

    def _clamped_x_range(
        self,
        requested_min: float,
        requested_max: float,
    ) -> tuple[float, float]:
        full_low = self._transform_x(self._plot_x_min)
        full_high = self._transform_x(self._plot_x_max)
        low = self._transform_x(requested_min)
        high = self._transform_x(requested_max)
        span = min(
            max(high - low, self._minimum_transformed_x_span()),
            max(full_high - full_low, 1e-9),
        )
        low = max(full_low, min(low, full_high - span))
        return self._inverse_x(low), self._inverse_x(low + span)

    def _x_at_fraction(self, fraction: float) -> float:
        low, high = self._transformed_x_range()
        return self._inverse_x(low + fraction * (high - low))

    def _x_fraction(self, value: float) -> float:
        low, high = self._transformed_x_range()
        span = high - low
        return (self._transform_x(value) - low) / span if span else 0.0

    def _map_y(self, value: float, plot_rect: QRectF) -> float:
        span = self._view_y[1] - self._view_y[0]
        fraction = (value - self._view_y[0]) / span if span else 0.0
        return plot_rect.bottom() - fraction * plot_rect.height()

    @staticmethod
    def _nearest_index(x_values: np.ndarray, target: float) -> int:
        insertion = int(np.searchsorted(x_values, target))
        insertion = min(max(insertion, 0), x_values.size - 1)
        previous = max(0, insertion - 1)
        if abs(float(x_values[previous]) - target) <= abs(
            float(x_values[insertion]) - target
        ):
            return previous
        return insertion

    def _visible_indices(self, series: PlotSeries) -> tuple[int, int]:
        start = int(np.searchsorted(series.x, self._view_x[0], side="left"))
        stop = int(np.searchsorted(series.x, self._view_x[1], side="right"))
        start = min(max(start, 0), series.x.size - 1)
        stop = min(max(stop, start + 1), series.x.size)
        return start, stop

    def _update_y_range(self) -> None:
        if self._plot_data is None:
            return
        visible_values = []
        for series in self._plot_data.all_series:
            start, stop = self._visible_indices(series)
            visible_values.append(series.y[start:stop])
        values = np.concatenate(visible_values) if visible_values else np.array([])
        if values.size == 0:
            self._view_y = (-25.0, 25.0)
        elif self._plot_data.symmetric_y:
            maximum = float(np.max(np.abs(values)))
            step = max(5.0, float(np.ceil(maximum / 25.0) * 5.0))
            self._view_y = (-5.0 * step, 5.0 * step)
        else:
            maximum = max(0.0, float(np.max(values)))
            step = max(5.0, float(np.ceil(maximum / 50.0) * 5.0))
            self._view_y = (0.0, 10.0 * step)
        self.update()

    def _clear_hover(self) -> None:
        self._hover_series_index = None
        self._hover_index = None
        self.update()

    def _update_hover(self, position: QPointF) -> None:
        if self._plot_data is None or not self._plot_rect().contains(position):
            self._clear_hover()
            return
        self._last_mouse_y = position.y()
        value = self.value_at_x_pixel(position.x())
        if value is None:
            self._clear_hover()
            return
        series = value[0]
        self._hover_series_index = next(
            index
            for index, primary in enumerate(self._plot_data.primary_series)
            if primary is series
        )
        self._hover_index = value[1]
        self.update()

    def _draw_title(self, painter: QPainter) -> None:
        painter.setPen(self.TEXT_COLOR)
        title_font = QFont("Helvetica Neue", 10, QFont.Weight.DemiBold)
        painter.setFont(title_font)
        title_width = max(100.0, self.width() - 240.0)
        title = QFontMetrics(title_font).elidedText(
            self._plot_data.title if self._plot_data else "",
            Qt.TextElideMode.ElideRight,
            int(title_width),
        )
        painter.drawText(
            QRectF(12.0, 8.0, title_width, 22.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )

    def _draw_grid_and_axes(self, painter: QPainter, plot_rect: QRectF) -> None:
        tick_font = QFont("Helvetica Neue", x_y_unit_font_size)
        tick_height = max(18, QFontMetrics(tick_font).height() + 4)
        painter.setFont(tick_font)
        grid_pen = QPen(self.GRID_COLOR, 1.0)
        for index in range(6):
            fraction = index / 5.0
            x = plot_rect.left() + fraction * plot_rect.width()
            painter.setPen(grid_pen)
            painter.drawLine(
                QPointF(x, plot_rect.top()),
                QPointF(x, plot_rect.bottom()),
            )
            painter.setPen(self.AXIS_COLOR)
            painter.drawText(
                QRectF(x - 55.0, plot_rect.bottom() + 4.0, 110.0, tick_height),
                Qt.AlignmentFlag.AlignCenter,
                self._format_axis_tick(self._x_at_fraction(fraction)),
            )

        for value in self._y_tick_values(
            self._view_y[0],
            self._view_y[1],
        ):
            y = self._map_y(value, plot_rect)
            painter.setPen(grid_pen)
            painter.drawLine(
                QPointF(plot_rect.left(), y),
                QPointF(plot_rect.right(), y),
            )
            painter.setPen(self.AXIS_COLOR)
            painter.drawText(
                QRectF(
                    2.0,
                    y - tick_height / 2.0,
                    self.LEFT_MARGIN - 8.0,
                    tick_height,
                ),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._format_axis_tick(value),
            )

        if self._plot_data and self._plot_data.symmetric_y:
            zero_y = self._map_y(0.0, plot_rect)
            painter.setPen(QPen(self.ZERO_COLOR, 1.8, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(plot_rect.left(), zero_y),
                QPointF(plot_rect.right(), zero_y),
            )

        painter.setPen(QPen(self.AXIS_COLOR, 1.0))
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.bottomRight())
        painter.drawLine(plot_rect.bottomLeft(), plot_rect.topLeft())
        painter.setFont(
            QFont(
                "Helvetica Neue",
                x_title_font_size,
                QFont.Weight.Bold,
            )
        )
        painter.drawText(
            QRectF(
                plot_rect.left(),
                self.height() - 24.0,
                plot_rect.width(),
                20.0,
            ),
            Qt.AlignmentFlag.AlignCenter,
            self._plot_data.x_label if self._plot_data else "",
        )
        painter.save()
        painter.translate(13.0, plot_rect.center().y())
        painter.rotate(-90.0)
        painter.setFont(
            QFont(
                "Helvetica Neue",
                y_title_font_size,
                QFont.Weight.Bold,
            )
        )
        painter.drawText(
            QRectF(-110.0, -10.0, 220.0, 20.0),
            Qt.AlignmentFlag.AlignCenter,
            self._plot_data.y_label if self._plot_data else "",
        )
        painter.restore()

    def _draw_all_series(self, painter: QPainter, plot_rect: QRectF) -> None:
        if self._plot_data is None:
            return
        active = None
        if self._hover_series_index is not None:
            active = self._plot_data.primary_series[self._hover_series_index]
        for series in self._plot_data.all_series:
            if series is active:
                continue
            self._draw_series(painter, plot_rect, series, active=False)
        if active is not None:
            self._draw_series(painter, plot_rect, active, active=True)

    def _draw_series(
        self,
        painter: QPainter,
        plot_rect: QRectF,
        series: PlotSeries,
        *,
        active: bool,
    ) -> None:
        start, stop = self._visible_indices(series)
        x_values = series.x[start:stop]
        y_values = series.y[start:stop]
        if x_values.size < 2:
            return
        color = QColor(series.color)
        width = 2.4 if active else 1.15
        style = (
            Qt.PenStyle.DashLine
            if not series.interactive
            else Qt.PenStyle.SolidLine
        )
        painter.setPen(QPen(color, width, style))
        envelope_x, minimums, maximums = minmax_envelope(
            x_values,
            y_values,
            max(1, int(plot_rect.width())),
        )
        if envelope_x.size == x_values.size:
            path = QPainterPath()
            path.moveTo(self._map_point(x_values[0], y_values[0], plot_rect))
            for x_value, y_value in zip(x_values[1:], y_values[1:]):
                path.lineTo(self._map_point(x_value, y_value, plot_rect))
            painter.drawPath(path)
            return
        for x_value, low, high in zip(envelope_x, minimums, maximums):
            painter.drawLine(
                self._map_point(x_value, low, plot_rect),
                self._map_point(x_value, high, plot_rect),
            )

    def _map_point(
        self,
        x_value: float,
        y_value: float,
        plot_rect: QRectF,
    ) -> QPointF:
        return QPointF(
            plot_rect.left() + self._x_fraction(x_value) * plot_rect.width(),
            self._map_y(y_value, plot_rect),
        )

    def _draw_legend(self, painter: QPainter, plot_rect: QRectF) -> None:
        if self._plot_data is None:
            return
        font = QFont("Helvetica Neue", max(8, x_y_unit_font_size - 4))
        metrics = QFontMetrics(font)
        row_height = metrics.height() + 4
        width = max(
            110,
            max(
                metrics.horizontalAdvance(series.name)
                for series in self._plot_data.all_series
            )
            + 42,
        )
        height = row_height * len(self._plot_data.all_series) + 10
        rect = QRectF(
            plot_rect.right() - width - 8.0,
            plot_rect.top() + 8.0,
            width,
            height,
        )
        painter.setPen(QPen(QColor("#d0d5dd"), 1.0))
        painter.setBrush(QColor(255, 255, 255, 232))
        painter.drawRoundedRect(rect, 4.0, 4.0)
        painter.setFont(font)
        for index, series in enumerate(self._plot_data.all_series):
            y = rect.top() + 5.0 + index * row_height + row_height / 2.0
            painter.setPen(
                QPen(
                    QColor(series.color),
                    2.0,
                    (
                        Qt.PenStyle.SolidLine
                        if series.interactive
                        else Qt.PenStyle.DashLine
                    ),
                )
            )
            painter.drawLine(
                QPointF(rect.left() + 8.0, y),
                QPointF(rect.left() + 28.0, y),
            )
            painter.setPen(self.TEXT_COLOR)
            painter.drawText(
                QRectF(
                    rect.left() + 34.0,
                    y - row_height / 2.0,
                    rect.width() - 38.0,
                    row_height,
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                series.name,
            )

    def _draw_hover(self, painter: QPainter, plot_rect: QRectF) -> None:
        if (
            self._plot_data is None
            or self._hover_series_index is None
            or self._hover_index is None
        ):
            return
        series = self._plot_data.primary_series[self._hover_series_index]
        x_value = float(series.x[self._hover_index])
        y_value = float(series.y[self._hover_index])
        point = self._map_point(x_value, y_value, plot_rect)

        painter.setPen(QPen(self.HOVER_COLOR, 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(point.x(), plot_rect.top()),
            QPointF(point.x(), plot_rect.bottom()),
        )
        painter.drawLine(
            QPointF(plot_rect.left(), point.y()),
            QPointF(plot_rect.right(), point.y()),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(series.color))
        painter.drawEllipse(point, 4.0, 4.0)

        label_font = QFont("Helvetica Neue", user_label_font_size)
        metrics = QFontMetrics(label_font)
        label_text = self._format_hover_label(x_value, y_value)
        label_height = metrics.height() * 2 + 12
        label_width = max(
            176.0,
            float(metrics.horizontalAdvance(label_text.splitlines()[0]) + 20),
        )
        label_x = (
            plot_rect.right() - label_width - 8.0
            if point.x() < plot_rect.center().x()
            else plot_rect.left() + 8.0
        )
        label_rect = QRectF(
            label_x,
            plot_rect.top() + 8.0,
            label_width,
            label_height,
        )
        painter.setPen(QPen(QColor("#d0d5dd"), 1.0))
        painter.setBrush(QColor(255, 255, 255, 242))
        painter.drawRoundedRect(label_rect, 4.0, 4.0)
        painter.setPen(self.TEXT_COLOR)
        painter.setFont(label_font)
        painter.drawText(
            label_rect.adjusted(8.0, 4.0, -8.0, -4.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label_text,
        )

        badge_font = QFont("Helvetica Neue", max(8, user_label_font_size - 4))
        badge_metrics = QFontMetrics(badge_font)
        badge_width = badge_metrics.horizontalAdvance(series.name) + 18.0
        badge_rect = QRectF(
            label_rect.left(),
            label_rect.bottom() + 4.0,
            badge_width,
            badge_metrics.height() + 6.0,
        )
        badge_color = QColor(series.color)
        badge_color.setAlpha(220)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(badge_color)
        painter.drawRoundedRect(badge_rect, 4.0, 4.0)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(badge_font)
        painter.drawText(
            badge_rect,
            Qt.AlignmentFlag.AlignCenter,
            series.name,
        )

    @classmethod
    def _format_hover_label(
        cls,
        x_value: float,
        y_value: float,
    ) -> str:
        return (
            f"X:{cls._format_coordinate(x_value)}\n"
            f"Y:{cls._format_coordinate(y_value)}"
        )

    @staticmethod
    def _format_coordinate(value: float) -> str:
        return f"{value:.3f}"

    @staticmethod
    def _format_axis_tick(value: float) -> str:
        return f"{value:.0f}"

    @staticmethod
    def _y_tick_values(
        lower: float,
        upper: float,
    ) -> list[float]:
        """Return eleven Y boundaries forming ten intervals."""
        if upper <= lower:
            return [0.0] * 11
        step = (upper - lower) / 10.0
        return [lower + index * step for index in range(11)]


class PreviewPlotWidget(InteractivePlotWidget):
    """Backward-compatible Preview wrapper for a single raw waveform."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_series: PreviewSeries | None = None
        self.set_placeholder("No preview data.")

    @property
    def series(self) -> PreviewSeries | None:
        return self._preview_series

    def set_series(self, series: PreviewSeries) -> None:
        self._preview_series = series
        self.set_plot_data(
            InteractivePlotData(
                title=series.title,
                x_label="Time (ms)",
                y_label=f"Amplitude ({series.unit})",
                x_scale="linear",
                symmetric_y=True,
                primary_series=[
                    PlotSeries(
                        name="Raw",
                        x=series.time_ms,
                        y=series.amplitude,
                        unit=series.unit,
                        color="#147d64",
                        interactive=True,
                    )
                ],
            )
        )

    def clear_series(self) -> None:
        self._preview_series = None
        self.clear_plot()
