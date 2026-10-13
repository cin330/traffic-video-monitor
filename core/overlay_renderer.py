# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Qt overlays keep Chinese labels readable without modifying source pixels."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QPolygonF

COLORS = {"畅通": "#2EAD78", "拥堵": "#D95C5C", "分析中": "#89939E", "数据不足": "#89939E"}


def screen_point(point, rect):
    return QPointF(rect.left() + point[0] * rect.width(), rect.top() + point[1] * rect.height())


def draw_overlay(painter, rect, frame_size, lanes, result, options):
    painter.save()
    painter.setClipRect(rect)
    painter.setFont(QFont("Sans Serif", 10))
    rows = {row["lane_id"]: row for row in (result or {}).get("lanes", [])}
    labels = []
    for lane in lanes:
        row = rows.get(lane.id, {})
        state = row.get("state", "分析中")
        color = QColor(COLORS.get(state, COLORS["分析中"]))
        polygon = QPolygonF([screen_point(point, rect) for point in lane.polygon])
        painter.setPen(QPen(color, 1.5))
        fill = QColor(color)
        fill.setAlphaF(options.get("opacity", 0.18) if options.get("fill", True) else 0)
        painter.setBrush(fill)
        painter.drawPolygon(polygon)
        if lane.monitor:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#BAC5CF"), 1, Qt.PenStyle.DashLine))
            painter.drawPolygon(QPolygonF([screen_point(point, rect) for point in lane.monitor]))
        if options.get("lines", True):
            painter.setPen(QPen(QColor("#F4CB69"), 1.5, Qt.PenStyle.DashLine))
            painter.drawLine(screen_point(lane.line[0], rect), screen_point(lane.line[1], rect))
        origin = polygon.boundingRect().center()
        text = f'{lane.name}  ↑{row.get("passed", 0)}'
        bounds = painter.fontMetrics().boundingRect(text)
        label = QRectF(origin.x() - (bounds.width() + 28) / 2, origin.y(), bounds.width() + 28, bounds.height() + 10)
        if label.right() > rect.right():
            label.moveRight(rect.right())
        if label.left() < rect.left():
            label.moveLeft(rect.left())
        # Keep adjacent lane labels readable when the perspective narrows the road.
        while any(label.adjusted(-2, -2, 2, 2).intersects(other) for other in labels):
            label.translate(0, label.height() + 4)
        if label.bottom() > rect.bottom():
            label.moveBottom(rect.bottom())
        labels.append(label)
        painter.fillRect(label, QColor(20, 28, 38, 220))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(label.left() + 9, label.center().y()), 3.5, 3.5)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(label.adjusted(16, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, text)
    if options.get("boxes", True):
        width, height = frame_size
        for vehicle in (result or {}).get("vehicles", []):
            x1, y1, x2, y2 = vehicle["box"]
            a, b = screen_point((x1 / width, y1 / height), rect), screen_point((x2 / width, y2 / height), rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#D4DDE5"), 1))
            painter.drawRect(QRectF(a, b))
            if options.get("ids", False):
                text = f'{vehicle["class_name"]} #{vehicle["id"]}'
                painter.drawText(QPointF(a.x(), max(rect.top() + 16, a.y() - 4)), text)
    painter.restore()
