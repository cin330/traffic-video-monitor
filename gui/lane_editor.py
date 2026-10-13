# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

from copy import deepcopy

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QStyle, QVBoxLayout,
)

from detect.lane_manager import Lane, LaneManager
from gui.video_canvas import VideoCanvas

DIRECTIONS = {"向下（远→近）": [0, 1], "向上（近→远）": [0, -1], "向右": [1, 0], "向左": [-1, 0]}


class LaneEditor(QDialog):
    def __init__(self, frame, lanes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("车道配置")
        self.resize(1120, 760)
        self.lanes = deepcopy(lanes)
        self.edit_id = None
        root = QVBoxLayout(self)
        tip = QLabel("区域 → 计数线 → 应用")
        tip.setToolTip("依次点击车道顶点，再点击计数线两个端点；监测区可选。\n"
                       "黄线：车道；粉线：计数线；蓝线：监测区。\n"
                       "按边界顺序点击，不能交叉。重叠区域按列表顺序归属。")
        tip.setWordWrap(True)
        root.addWidget(tip)
        body = QHBoxLayout()
        self.canvas = VideoCanvas()
        self.canvas.editing = True
        self.canvas.set_frame(frame)
        body.addWidget(self.canvas, 4)
        side = QVBoxLayout()
        self.list = QListWidget()
        side.addWidget(self.list)
        form = QFormLayout()
        self.name = QLineEdit()
        self.group = QLineEdit("方向 A")
        self.direction = QComboBox()
        self.direction.addItems(DIRECTIONS)
        self.capacity = QDoubleSpinBox()
        self.capacity.setRange(1, 1000)
        self.capacity.setValue(10)
        self.slow = QDoubleSpinBox()
        self.slow.setRange(0.01, 10)
        self.slow.setDecimals(2)
        self.slow.setValue(0.25)
        self.slow.setToolTip("车辆框高度/秒；按机位校准。这不是 km/h。")
        self.mode = QComboBox()
        self.mode.addItems(["车道区域", "计数线", "监测区（可选）"])
        self.capacity.setToolTip("参考拥挤车辆数")
        for title, widget in (("名称", self.name), ("分组", self.group), ("方向", self.direction),
                              ("容量", self.capacity), ("低速（框高/秒）", self.slow), ("绘制", self.mode)):
            form.addRow(title, widget)
        side.addLayout(form)
        shape_tools = QHBoxLayout()
        for text, tooltip, icon, handler in (
            ("", "撤销最后一点", QStyle.StandardPixmap.SP_ArrowBack, self.undo),
            ("", "清空当前图形", QStyle.StandardPixmap.SP_DialogResetButton, self.clear_shape),
            ("应用", "应用车道", QStyle.StandardPixmap.SP_DialogApplyButton, self.apply_lane),
            ("新增", "新增车道", QStyle.StandardPixmap.SP_FileIcon, self.new_lane),
            ("", "删除选中车道", QStyle.StandardPixmap.SP_TrashIcon, self.delete_lane),
        ):
            button = QPushButton(text)
            button.setIcon(self.style().standardIcon(icon))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.clicked.connect(handler)
            shape_tools.addWidget(button)
        side.addLayout(shape_tools)
        body.addLayout(side, 1)
        root.addLayout(body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("完成")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.finish)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.canvas.point_clicked.connect(self.add_point)
        self.list.currentRowChanged.connect(self.select_lane)
        self.refresh_list()
        self.new_lane()

    def shape_key(self):
        return ("polygon", "line", "monitor")[self.mode.currentIndex()]

    def add_point(self, point):
        key = self.shape_key()
        points = self.canvas.draft.setdefault(key, [])
        if key == "line" and len(points) == 2:
            points.clear()
        points.append(list(point))
        self.canvas.update()

    def undo(self):
        points = self.canvas.draft.setdefault(self.shape_key(), [])
        if points:
            points.pop()
        self.canvas.update()

    def clear_shape(self):
        self.canvas.draft[self.shape_key()] = []
        self.canvas.update()

    def refresh_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems([lane.name for lane in self.lanes])
        self.list.blockSignals(False)
        self.canvas.lanes = self.lanes
        self.canvas.update()

    def new_lane(self):
        self.list.setCurrentRow(-1)
        self.edit_id = None
        self.name.setText(f"车道 {len(self.lanes) + 1}")
        self.mode.setCurrentIndex(0)
        self.canvas.draft = {"polygon": [], "line": [], "monitor": []}
        self.canvas.update()

    def select_lane(self, row):
        if row < 0:
            return
        lane = self.lanes[row]
        self.edit_id = lane.id
        self.name.setText(lane.name)
        self.group.setText(lane.group)
        self.capacity.setValue(lane.reference_count)
        self.slow.setValue(lane.slow_threshold)
        for index, vector in enumerate(DIRECTIONS.values()):
            if vector == lane.direction:
                self.direction.setCurrentIndex(index)
        self.canvas.draft = {"polygon": deepcopy(lane.polygon), "line": deepcopy(lane.line), "monitor": deepcopy(lane.monitor)}
        self.canvas.update()

    def apply_lane(self):
        from uuid import uuid4

        try:
            lane = Lane(id=self.edit_id or uuid4().hex[:8], name=self.name.text().strip(),
                        polygon=deepcopy(self.canvas.draft.get("polygon", [])),
                        line=deepcopy(self.canvas.draft.get("line", [])),
                        monitor=deepcopy(self.canvas.draft.get("monitor", [])),
                        direction=DIRECTIONS[self.direction.currentText()], group=self.group.text().strip(),
                        reference_count=self.capacity.value(), slow_threshold=self.slow.value())
            lane.validate()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "车道配置无效", str(exc))
            return False
        index = next((i for i, item in enumerate(self.lanes) if item.id == lane.id), len(self.lanes))
        if index == len(self.lanes):
            self.lanes.append(lane)
        else:
            self.lanes[index] = lane
        self.edit_id = lane.id
        self.refresh_list()
        self.list.setCurrentRow(index)
        return True

    def delete_lane(self):
        row = self.list.currentRow()
        if row >= 0:
            self.lanes.pop(row)
            self.refresh_list()
            self.new_lane()

    def finish(self):
        # Apply visible draft so edits are not silently discarded by the OK button.
        if self.canvas.draft.get("polygon") and not self.apply_lane():
            return
        if not self.lanes:
            QMessageBox.warning(self, "没有车道", "请先绘制并应用至少一条车道")
            return
        LaneManager(self.lanes)
        self.accept()
