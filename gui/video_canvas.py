# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import cv2

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from core.overlay_renderer import draw_overlay, screen_point


class VideoCanvas(QWidget):
    point_clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.pixmap = None
        self.frame_size = (1, 1)
        self.lanes, self.result = [], None
        self.options = {"fill": True, "boxes": True, "ids": False, "lines": True, "opacity": 0.18}
        self.editing = False
        self.draft = {}
        self.setToolTip("画面标签：车道名、↑累计通过；圆点颜色表示车道状态。")

    def set_frame(self, frame):
        if frame is None:
            self.pixmap = None
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            self.frame_size = (width, height)
            self.pixmap = QPixmap.fromImage(QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy())
        self.update()

    def image_rect(self):
        if self.pixmap is None:
            return QRectF()
        scale = min(self.width() / self.frame_size[0], self.height() / self.frame_size[1])
        width, height = self.frame_size[0] * scale, self.frame_size[1] * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def normalized_point(self, position):
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(position):
            return None
        return ((position.x() - rect.left()) / rect.width(), (position.y() - rect.top()) / rect.height())

    def mousePressEvent(self, event):
        if self.editing and event.button() == Qt.MouseButton.LeftButton:
            point = self.normalized_point(event.position())
            if point is not None:
                self.point_clicked.emit(point)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F8FAFC"))
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self.pixmap is None:
            painter.setPen(QColor("#64748B"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "打开视频")
            return
        rect = self.image_rect()
        painter.drawPixmap(rect, self.pixmap, QRectF(self.pixmap.rect()))
        draw_overlay(painter, rect, self.frame_size, self.lanes, self.result, self.options)
        if self.editing:
            painter.save()
            painter.setClipRect(rect)
            for key, color in (("polygon", "#F4CB69"), ("monitor", "#63BDF2"), ("line", "#F19CA7")):
                points = self.draft.get(key, [])
                painter.setPen(QPen(QColor(color), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                polygon = QPolygonF([screen_point(point, rect) for point in points])
                if key != "line" and len(points) >= 3:
                    painter.drawPolygon(polygon)
                else:
                    painter.drawPolyline(polygon)
                for point in polygon:
                    painter.drawEllipse(point, 4, 4)
            painter.restore()
