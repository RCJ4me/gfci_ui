# -*- coding: utf-8 -*-
"""Zoomable, pannable image view used by the result tabs."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)


class ImageView(QGraphicsView):
    """Display a plot image fitted to the viewport width.

    The image is scaled so its width matches the viewport minus a small margin,
    and is re-fitted whenever the widget is resized while in fit-width mode.
    Zooming switches to a manual scale; once the scaled image is larger than the
    viewport the user can drag with the left mouse button to pan.
    """

    MARGIN = 10
    ZOOM_STEP = 1.25
    MIN_SCALE = 0.01
    MAX_SCALE = 40.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._fit_width = True

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._item = QGraphicsPixmapItem()
        self._item.setVisible(False)
        self._scene.addItem(self._item)

        self._placeholder = QGraphicsSimpleTextItem()
        self._placeholder.setBrush(QColor("#8a8a8a"))
        self._placeholder.setFont(QFont("Helvetica Neue", 13))
        self._scene.addItem(self._placeholder)

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setBackgroundBrush(QColor("#ffffff"))

    # ---------- content ----------
    def set_placeholder(self, text: str) -> None:
        """Text shown while no image has been produced."""
        self._placeholder.setText(text)
        self._refresh_placeholder()

    def set_image(self, path: str) -> bool:
        """Load an image; return False when it cannot be read."""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        self._pixmap = pixmap
        self._item.setPixmap(pixmap)
        self._item.setVisible(True)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._refresh_placeholder()
        self._fit_width = True
        self.fit_to_width()
        return True

    def clear_image(self) -> None:
        self._pixmap = None
        self._item.setPixmap(QPixmap())
        self._item.setVisible(False)
        self.resetTransform()
        self._refresh_placeholder()

    # ---------- zoom ----------
    def fit_to_width(self) -> None:
        """Scale the image so its width matches the viewport width."""
        self._fit_width = True
        if self._pixmap is None or self._pixmap.width() <= 0:
            return
        available = self.viewport().width() - self.MARGIN
        target = max(self.MIN_SCALE, available / self._pixmap.width())
        self.resetTransform()
        self.scale(target, target)

    def zoom_in(self) -> None:
        self._zoom(self.ZOOM_STEP)

    def zoom_out(self) -> None:
        self._zoom(1.0 / self.ZOOM_STEP)

    def _zoom(self, factor: float) -> None:
        if self._pixmap is None:
            return
        self._fit_width = False
        current = self.transform().m11() or 1.0
        target = max(self.MIN_SCALE, min(self.MAX_SCALE, current * factor))
        self.scale(target / current, target / current)

    # ---------- events ----------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap is None:
            self._refresh_placeholder()
        elif self._fit_width:
            self.fit_to_width()

    def showEvent(self, event):
        super().showEvent(event)
        if self._pixmap is None:
            self._refresh_placeholder()
        elif self._fit_width:
            self.fit_to_width()

    def _refresh_placeholder(self) -> None:
        has_image = self._pixmap is not None
        self._placeholder.setVisible(not has_image)
        if has_image:
            return
        rect = QRectF(self.viewport().rect())
        self._scene.setSceneRect(rect)
        bounds = self._placeholder.boundingRect()
        self._placeholder.setPos(
            rect.center().x() - bounds.width() / 2.0,
            rect.center().y() - bounds.height() / 2.0,
        )
