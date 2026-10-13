# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Traffic workstation: lane editing, sequential analysis, overlays and CSV export."""

import csv
import json
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QSlider, QStyle,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.analysis_worker import AnalysisWorker
from core.traffic_analysis import VEHICLE_CLASSES
from core.video_player import VideoPlayer
from detect.lane_manager import LaneManager, validate_analysis_settings
from gui.lane_editor import LaneEditor
from gui.video_canvas import VideoCanvas

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATUS_COLORS = {"畅通": "#18794E", "拥堵": "#C03535", "分析中": "#64748B", "数据不足": "#64748B"}


class Traffic_monitor(QWidget):
    request = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("交通监控")
        self.resize(1380, 860)
        self.player = VideoPlayer()
        self.video_path = None
        self.model_path = None
        self.lanes = []
        self.camera = ""
        self.config_revision = 0
        self.analysis_settings = validate_analysis_settings()
        self.generation = 0
        self.speed = 1.0
        self.busy = False
        self.busy_kind = None
        self.pending_action = None
        self.raw_frame = None
        self.result = None
        self.cache = None
        self.snapshots, self.events = [], []
        self.last_record = -1.0
        self.is_seeking = False
        self.was_playing_before_seek = False
        self.closing = False
        self.full_running = False
        self.last_panel_time = -1.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self._setup_ui()
        self._connect_signals()
        self.thread = QThread(self)
        self.worker = AnalysisWorker()
        self.worker.moveToThread(self.thread)
        self.request.connect(self.worker.execute)
        self.worker.completed.connect(self.on_completed)
        self.worker.progress.connect(self.on_full_progress)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finish_close)
        self.thread.start()
        self.update_statistics()

    def _setup_ui(self):
        palette = QPalette()
        for role, color in ((QPalette.ColorRole.Window, "#FFFFFF"),
                            (QPalette.ColorRole.Base, "#FFFFFF"),
                            (QPalette.ColorRole.AlternateBase, "#F8FAFC"),
                            (QPalette.ColorRole.WindowText, "#243244"),
                            (QPalette.ColorRole.Text, "#243244"),
                            (QPalette.ColorRole.Button, "#FFFFFF"),
                            (QPalette.ColorRole.ButtonText, "#243244"),
                            (QPalette.ColorRole.Highlight, "#2563EB"),
                            (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
                            (QPalette.ColorRole.ToolTipBase, "#FFFFFF"),
                            (QPalette.ColorRole.ToolTipText, "#243244")):
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#94A3B8"))
        self.setPalette(palette)
        self.setStyleSheet("""
            QWidget { background: #FFFFFF; color: #243244; font-size: 13px; }
            QPushButton { background: #FFFFFF; border: 1px solid #DCE3EB; border-radius: 6px; padding: 7px 10px; }
            QPushButton:hover { background: #EFF6FF; border-color: #93B4F5; }
            QPushButton:pressed { background: #DBEAFE; }
            QPushButton:focus { border-color: #2563EB; }
            QPushButton:disabled { color: #94A3B8; background: #F8FAFC; border-color: #E8EDF3; }
            QGroupBox { border: 1px solid #E2E8F0; border-radius: 8px; margin-top: 14px; padding: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; }
            QTableWidget, QListWidget { background: #FFFFFF; alternate-background-color: #F8FAFC;
                                       gridline-color: #EDF1F5; border: 1px solid #E2E8F0; border-radius: 6px; }
            QHeaderView::section { background: #F8FAFC; color: #526174; padding: 7px; border: none; }
            QLineEdit, QDoubleSpinBox, QComboBox { background: #FFFFFF; border: 1px solid #DCE3EB;
                                                border-radius: 5px; padding: 5px; }
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #2563EB; }
            QComboBox QAbstractItemView { background: #FFFFFF; selection-background-color: #DBEAFE;
                                        selection-color: #243244; }
            QListWidget::item:selected { background: #DBEAFE; color: #243244; }
            QSlider::groove:horizontal { height: 4px; background: #E2E8F0; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #2563EB; border-radius: 2px; }
            QSlider::handle:horizontal { background: #2563EB; width: 12px; margin: -4px 0; border-radius: 6px; }
            QSlider::handle:horizontal:disabled, QSlider::sub-page:horizontal:disabled { background: #CBD5E1; }
            QToolTip { background: #FFFFFF; color: #243244; border: 1px solid #DCE3EB; padding: 6px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        title = QLabel("交通监控")
        title.setStyleSheet("font-size: 22px; font-weight: bold; padding: 6px;")
        root.addWidget(title)
        body = QHBoxLayout()
        self.video_label = VideoCanvas()
        body.addWidget(self.video_label, 3)
        side = QVBoxLayout()
        self.statistics_group = QGroupBox("车辆 · 本段")
        grid = QGridLayout(self.statistics_group)
        self.current_count_label = QLabel("0")
        self.passed_count_label = QLabel("0")
        grid.addWidget(QLabel("当前"), 0, 0)
        grid.addWidget(self.current_count_label, 0, 1)
        grid.addWidget(QLabel("累计通过"), 1, 0)
        grid.addWidget(self.passed_count_label, 1, 1)
        for col, text in enumerate(("车型", "当前", "通过")):
            grid.addWidget(QLabel(text), 2, col)
        self.class_labels = {}
        for row, name in enumerate(VEHICLE_CLASSES, 3):
            labels = (QLabel(name), QLabel("0"), QLabel("0"))
            self.class_labels[name] = labels
            for column, label in enumerate(labels):
                grid.addWidget(label, row, column)
        side.addWidget(self.statistics_group)
        self.lane_table = QTableWidget(0, 6)
        self.lane_table.setHorizontalHeaderLabels(["车道", "当前", "通过", "近60秒", "指数", "状态"])
        self.lane_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lane_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lane_table.setAlternatingRowColors(True)
        self.lane_table.verticalHeader().hide()
        self.lane_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.lane_table.horizontalHeader().setStretchLastSection(True)
        side.addWidget(self.lane_table, 1)
        self.road_label = QLabel("待分析")
        self.road_label.setWordWrap(True)
        side.addWidget(self.road_label)
        self.config_label = QLabel("未配置车道")
        self.config_label.setStyleSheet("color: #64748B;")
        self.config_label.setWordWrap(True)
        side.addWidget(self.config_label)
        info = self._button("", "指标说明", QStyle.StandardPixmap.SP_MessageBoxInformation)
        info.setToolTip("绿色：畅通；红色：拥堵；灰色：分析中或数据不足。\n"
                        "指数 = 100 × 聚集程度 × 低速比例，需采集完整窗口。\n"
                        "低速为相对运动，需按机位校准；红灯排队可能显示拥堵。")
        info.clicked.connect(lambda: QMessageBox.information(self, "指标说明", info.toolTip()))
        side.addWidget(info, 0, Qt.AlignmentFlag.AlignRight)
        body.addLayout(side, 2)
        root.addLayout(body, 1)

        display = QHBoxLayout()
        self.display_checks = {}
        for key, text, checked in (("fill", "着色", True), ("boxes", "检测框", True),
                                   ("ids", "ID", False), ("lines", "计数线", True)):
            check = QCheckBox(text)
            check.setChecked(checked)
            check.toggled.connect(lambda value, option=key: self.set_display(option, value))
            self.display_checks[key] = check
            display.addWidget(check)
        display.addWidget(QLabel("透明度"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 40)
        self.opacity.setValue(18)
        self.opacity.setMaximumWidth(150)
        self.opacity.valueChanged.connect(lambda value: self.set_display("opacity", value / 100))
        display.addWidget(self.opacity)
        display.addStretch()
        root.addLayout(display)

        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 0)
        timeline = QHBoxLayout()
        timeline.addWidget(self.progress_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color: #64748B;")
        timeline.addWidget(self.time_label)
        root.addLayout(timeline)
        controls = QHBoxLayout()
        self.open_button = self._button("打开", "打开视频", QStyle.StandardPixmap.SP_DialogOpenButton)
        self.play_button = self._button("", "播放", QStyle.StandardPixmap.SP_MediaPlay)
        self.pause_button = self._button("", "暂停", QStyle.StandardPixmap.SP_MediaPause)
        self.stop_button = self._button("", "停止并回到开头", QStyle.StandardPixmap.SP_MediaStop)
        self.model_button = self._button("模型", "加载 YOLO 模型", QStyle.StandardPixmap.SP_FileIcon)
        self.exit_button = self._button("", "退出", QStyle.StandardPixmap.SP_DialogCloseButton)
        for button in (self.open_button, self.model_button, self.play_button, self.pause_button, self.stop_button):
            controls.addWidget(button)
        self.back_button = self._button("", "后退 5 秒", QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.forward_button = self._button("", "前进 5 秒", QStyle.StandardPixmap.SP_MediaSeekForward)
        controls.addWidget(self.back_button)
        controls.addWidget(self.forward_button)
        controls.addSpacing(12)
        for text, speed in (("0.5×", 0.5), ("1×", 1), ("2×", 2), ("4×", 4)):
            button = QPushButton(text)
            button.setToolTip(f"以 {text} 速度播放")
            button.clicked.connect(lambda checked=False, value=speed: self.set_speed(value))
            controls.addWidget(button)
        self.speed_label = QLabel("1×")
        self.speed_label.setToolTip("当前播放速度")
        controls.addWidget(self.speed_label)
        controls.addStretch()
        controls.addWidget(self.exit_button)
        root.addLayout(controls)
        tools = QHBoxLayout()
        self.lane_button = self._button("车道", "配置车道", QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self.save_button = self._button("", "保存车道配置", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.config_button = self._button("", "加载车道配置", QStyle.StandardPixmap.SP_DirOpenIcon)
        self.full_button = self._button("分析", "完整分析视频", QStyle.StandardPixmap.SP_MediaPlay)
        self.parameters_button = self._button("参数", "分析参数", QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.cancel_button = self._button("", "取消完整分析", QStyle.StandardPixmap.SP_DialogCancelButton)
        self.cancel_button.setEnabled(False)
        self.export_button = self._button("导出", "导出统计 CSV", QStyle.StandardPixmap.SP_ArrowDown)
        for button in (self.lane_button, self.save_button, self.config_button, self.parameters_button,
                       self.full_button, self.cancel_button, self.export_button):
            tools.addWidget(button)
        tools.addStretch()
        root.addLayout(tools)
        self.status_label = QLabel("请打开视频")
        self.status_label.setStyleSheet("color: #64748B; font-size: 12px;")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _button(self, text, tooltip, icon):
        button = QPushButton(text)
        button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        if not text:
            button.setFixedWidth(38)
        return button

    def _connect_signals(self):
        for button, slot in ((self.open_button, self.open_video), (self.play_button, self.play_video),
                             (self.pause_button, self.pause_video), (self.stop_button, self.stop_video),
                             (self.model_button, self.load_model), (self.exit_button, self.close),
                             (self.lane_button, self.edit_lanes), (self.save_button, self.save_config),
                             (self.config_button, self.load_config), (self.full_button, self.full_analysis),
                             (self.parameters_button, self.edit_parameters),
                             (self.cancel_button, self.cancel_full), (self.export_button, self.export_statistics)):
            button.clicked.connect(slot)
        self.back_button.clicked.connect(lambda: self.jump_seconds(-5))
        self.forward_button.clicked.connect(lambda: self.jump_seconds(5))
        self.progress_slider.sliderPressed.connect(self.begin_seek)
        self.progress_slider.sliderReleased.connect(self.end_seek)

    def set_display(self, key, value):
        self.video_label.options[key] = value
        self.video_label.update()

    def when_idle(self, callback):
        self.timer.stop()
        if self.full_running:
            return
        if self.busy:
            self.pending_action = callback
        else:
            callback()

    def submit(self, kind, **payload):
        self.busy, self.busy_kind = True, kind
        self.request.emit({"kind": kind, "generation": self.generation, **payload})

    def reset_detection(self, clear_cache=True):
        self.generation += 1
        self.result = None
        self.last_panel_time = -1
        if clear_cache:
            self.cache = None
            self.snapshots, self.events = [], []
            self.last_record = -1
        self.video_label.result = None
        self.video_label.options["cached"] = self.cache is not None
        self.request.emit({"kind": "reset", "generation": self.generation, "lanes": deepcopy(self.lanes),
                           "settings": dict(self.analysis_settings)})
        self.update_statistics()
        self.video_label.update()

    def open_video(self):
        self.when_idle(self._open_video)

    def _open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择交通视频", str(PROJECT_ROOT / "video"), "视频 (*.mp4 *.avi *.mov *.mkv)")
        if not path:
            return
        self.is_seeking = False
        self.was_playing_before_seek = False
        self.raw_frame = None
        self.video_path = None
        self.lanes = []
        self.video_label.lanes = []
        self.config_revision += 1
        self.reset_detection()
        if not self.player.open_video(path):
            self.video_label.set_frame(None)
            self.progress_slider.setRange(0, 0)
            self.time_label.setText("00:00 / 00:00")
            self.config_label.setText("未配置车道")
            QMessageBox.warning(self, "视频打开失败", path)
            return
        self.video_path = path
        self.camera = Path(path).stem
        self.speed = 1.0
        self.speed_label.setText("1×")
        self.progress_slider.setRange(0, max(0, self.player.get_frame() - 1))
        self.config_label.setText("未配置车道")
        self.config_label.setToolTip("配置当前机位的车道，或加载对应配置")
        self.status_label.setText("视频已打开 · 请配置车道")
        self.next_frame()

    def load_model(self):
        self.when_idle(self._load_model)

    def _load_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 YOLO 权重", str(PROJECT_ROOT / "models"), "模型 (*.pt)")
        if path:
            self.status_label.setText("加载模型…")
            self.model_button.setEnabled(False)
            self.submit("load", path=path)

    def edit_lanes(self):
        self.when_idle(self._edit_lanes)

    def _edit_lanes(self):
        if self.raw_frame is None:
            QMessageBox.information(self, "配置车道", "请先打开视频")
            return
        editor = LaneEditor(self.raw_frame, self.lanes, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.set_lanes(editor.lanes)

    def set_lanes(self, lanes):
        LaneManager(lanes)
        self.lanes = deepcopy(lanes)
        self.video_label.lanes = self.lanes
        self.config_revision += 1
        self.reset_detection()
        self.config_label.setText(f"{len(lanes)} 条车道")
        self.config_label.setToolTip(f"机位：{self.camera}\n配置版本：{self.config_revision}")
        self.status_label.setText("车道已更新 · 统计已重置")
        self.preview_current()

    def save_config(self):
        if not self.lanes:
            QMessageBox.information(self, "保存配置", "请先配置车道")
            return
        directory = PROJECT_ROOT / "config" / "lanes"
        directory.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "保存车道配置", str(directory / f"{self.camera}.json"), "JSON (*.json)")
        if path:
            try:
                LaneManager(self.lanes).save(path, self.camera, self.video_label.frame_size, self.analysis_settings)
                self.status_label.setText("配置已保存")
                self.save_button.setToolTip(f"保存车道配置\n上次保存：{path}")
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))

    def load_config(self):
        self.when_idle(self._load_config)

    def _load_config(self):
        if self.raw_frame is None:
            QMessageBox.information(self, "加载配置", "请先打开视频")
            return
        path, _ = QFileDialog.getOpenFileName(self, "加载对应机位的配置", str(PROJECT_ROOT / "config" / "lanes"), "JSON (*.json)")
        if not path:
            return
        try:
            manager, data = LaneManager.load(path)
            self.camera = data.get("camera") or self.camera
            self.analysis_settings = data["analysis"]
            self.set_lanes(manager.lanes)
            self.status_label.setText("配置已加载 · 请核对车道")
        except Exception as exc:
            QMessageBox.warning(self, "配置加载失败", str(exc))

    def edit_parameters(self):
        self.when_idle(self._edit_parameters)

    def _edit_parameters(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("分析参数")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        inputs = {}
        for key, title, low, high in (("window", "窗口（秒）", 1, 120),
                                      ("hold", "确认时长（秒）", .1, 60),
                                      ("enter", "进入阈值", 0, 100), ("exit", "退出阈值", 0, 100)):
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setValue(self.analysis_settings[key])
            form.addRow(title, spin)
            inputs[key] = spin
        layout.addLayout(form)
        hint = QLabel("进入阈值 > 退出阈值")
        hint.setToolTip("按机位校准。修改后重置分析；这些阈值不是交通行业标准。")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")

        def accept():
            try:
                validate_analysis_settings({key: spin.value() for key, spin in inputs.items()})
            except ValueError as exc:
                QMessageBox.warning(dialog, "参数无效", str(exc))
                return
            dialog.accept()

        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.analysis_settings = validate_analysis_settings({key: spin.value() for key, spin in inputs.items()})
            self.config_revision += 1
            self.reset_detection()
            self.status_label.setText("参数已更新 · 统计已重置")
            self.preview_current()

    def start_timer(self):
        if (self.player.cap is not None and not self.is_seeking and not self.full_running
                and not self.closing and self.pending_action is None and self.busy_kind != "load"):
            self.timer.start(max(1, round(1000 / (self.player.fps * self.speed))))

    def play_video(self):
        if self.full_running or self.player.cap is None:
            return
        if self.player.get_current_frame() >= self.player.get_frame():
            self.when_idle(lambda: self._seek(0, True))
        else:
            self.start_timer()

    def pause_video(self):
        self.timer.stop()
        self.was_playing_before_seek = False

    def stop_video(self):
        if self.player.cap is None:
            return
        self.speed = 1.0
        self.speed_label.setText("1×")
        self.when_idle(lambda: self._seek(0, False))

    def set_speed(self, speed):
        self.speed = speed
        self.speed_label.setText(f"{speed:g}×")
        if self.timer.isActive():
            self.start_timer()

    def jump_seconds(self, seconds):
        if self.player.cap is not None:
            # The currently displayed frame is one behind the capture read position.
            target = max(0, self.player.get_current_frame() - 1) + round(seconds * self.player.fps)
            self.seek_to_frame(target)

    def begin_seek(self):
        self.was_playing_before_seek = self.timer.isActive()
        self.is_seeking = True
        self.timer.stop()

    def end_seek(self):
        resume = self.was_playing_before_seek
        self.is_seeking = False
        self.was_playing_before_seek = False
        self.seek_to_frame(self.progress_slider.value(), resume)

    def seek_to_frame(self, target, resume=None):
        if self.player.cap is None or self.full_running:
            return
        if resume is None:
            resume = self.timer.isActive()
        self.when_idle(lambda: self._seek(target, resume))

    def _seek(self, target, resume):
        total = self.player.get_frame()
        if total <= 0:
            return
        target = max(0, min(int(target), total - 1))
        if self.player.seek_frame(target):
            self.reset_detection(clear_cache=self.cache is None)
            self.next_frame()
        if resume:
            self.start_timer()

    def preview_current(self):
        if self.raw_frame is None or self.busy:
            return
        index = max(0, self.player.get_current_frame() - 1)
        self.submit("frame", frame=self.raw_frame.copy(), frame_index=index, timestamp=index / self.player.fps)

    def next_frame(self):
        if self.busy or self.is_seeking or self.full_running or self.closing:
            return
        ok, frame = self.player.read_frame()
        if not ok:
            self.timer.stop()
            return
        index = max(0, self.player.get_current_frame() - 1)
        if self.cache is not None:
            if index < len(self.cache):
                self.display_result(frame, index, self.cache[index], record=False)
            else:
                self.timer.stop()
                self.status_label.setText("超出分析范围 · 请重新分析")
        else:
            self.submit("frame", frame=frame, frame_index=index, timestamp=index / self.player.fps)

    def on_completed(self, output):
        self.busy, self.busy_kind = False, None
        if self.closing:
            self.thread.quit()
            return
        if output["generation"] != self.generation:
            return
        kind = output["kind"]
        if kind == "full":
            self.set_full_controls(False)
        if "error" in output:
            self.timer.stop()
            self.model_button.setEnabled(True)
            if kind == "frame":
                self.reset_detection()
                self.status_label.setText("检测失败 · 请检查模型")
            elif kind == "full":
                self.reset_detection()
                self.status_label.setText("分析失败 · 统计已重置")
            QMessageBox.warning(self, "分析失败", output["error"])
        elif kind == "load":
            self.model_path = output["path"]
            self.model_button.setText("模型")
            self.model_button.setToolTip(self.model_path)
            self.model_button.setEnabled(True)
            self.reset_detection()
            self.model_button.setToolTip(f"更换模型：{Path(self.model_path).name}")
            self.status_label.setText("模型已加载")
            self.preview_current()
        elif kind == "frame":
            self.display_result(output["frame"], output["frame_index"], output["result"])
        elif kind == "full":
            if output.get("cancelled"):
                self.reset_detection()
                self.status_label.setText("分析已取消")
                # Full-analysis progress frames came from a separate capture, so reload
                # the original playback position rather than reusing its latest pixels.
                self.player.seek_frame(max(0, self.player.get_current_frame() - 1))
                self.next_frame()
            else:
                self.cache = output["cache"]
                self.snapshots, self.events = output["snapshots"], output["events"]
                self.video_label.options["cached"] = True
                self.status_label.setText(f"分析完成 · {len(self.cache)} 帧 · {len(self.events)} 次通过")
                self.player.seek_frame(0)
                self.next_frame()
        if self.pending_action is not None and not self.busy:
            callback, self.pending_action = self.pending_action, None
            callback()

    def display_result(self, frame, index, result, record=True):
        self.raw_frame = frame
        self.result = result
        self.video_label.result = result
        self.video_label.set_frame(frame)
        if record:
            self.events.extend(result["events"])
            if result["timestamp"] - self.last_record >= 1:
                self.snapshots.append(result)
                self.last_record = result["timestamp"]
        if not self.is_seeking:
            self.progress_slider.setValue(index)
        self.time_label.setText(f"{self.format_time(result['timestamp'])} / {self.format_time(self.player.get_frame() / self.player.fps)}")
        if (not self.timer.isActive() or result["timestamp"] - self.last_panel_time >= 0.2
                or result["timestamp"] < self.last_panel_time):
            self.update_statistics()
            self.last_panel_time = result["timestamp"]

    def update_statistics(self):
        rows = (self.result or {}).get("lanes", [])
        self.statistics_group.setTitle("车辆 · " + ("全片" if self.cache is not None else "本段"))
        self.statistics_group.setToolTip("全片累计至当前时间" if self.cache is not None else "本段累计；跳转后重置")
        self.current_count_label.setText(str(sum(row["current"] for row in rows)))
        self.passed_count_label.setText(str(sum(row["passed"] for row in rows)))
        for name, (_, current, passed) in self.class_labels.items():
            current.setText(str(sum(row["classes_current"].get(name, 0) for row in rows)))
            passed.setText(str(sum(row["classes_passed"].get(name, 0) for row in rows)))
        self.lane_table.setRowCount(len(self.lanes))
        lookup = {row["lane_id"]: row for row in rows}
        for index, lane in enumerate(self.lanes):
            row = lookup.get(lane.id, {})
            score = row.get("score")
            state = row.get("state", "分析中")
            values = (lane.name, str(row.get("current", 0)), str(row.get("passed", 0)), str(row.get("recent", 0)),
                      "—" if score is None else f"{score:.0f}", state)
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 5:
                    item.setForeground(QColor(STATUS_COLORS.get(state, "#64748B")))
                item.setToolTip(f"聚集程度：{row.get('density', 0):.2f}\n低速比例："
                                + ("数据不足" if row.get("low_speed") is None else f"{row['low_speed']:.0%}"))
                self.lane_table.setItem(index, column, item)
        groups = (self.result or {}).get("groups", {})
        self.road_label.setText("；".join(f"{key} {value}" for key, value in groups.items()) or "待分析")

    def full_analysis(self):
        self.when_idle(self._full_analysis)

    def _full_analysis(self):
        if not self.video_path or not self.model_path or not self.lanes:
            QMessageBox.information(self, "完整分析", "请先打开视频、配置车道并加载模型")
            return
        self.reset_detection()
        self.worker.cancel.clear()
        self.set_full_controls(True)
        self.status_label.setText("分析中…")
        self.submit("full", path=self.video_path, fps=self.player.fps, lanes=deepcopy(self.lanes), settings=dict(self.analysis_settings))

    def set_full_controls(self, running):
        self.full_running = running
        for widget in (self.open_button, self.play_button, self.pause_button, self.stop_button,
                       self.model_button, self.lane_button, self.config_button, self.full_button,
                       self.parameters_button,
                       self.progress_slider, self.back_button, self.forward_button, self.export_button):
            widget.setEnabled(not running)
        self.cancel_button.setEnabled(running)

    def cancel_full(self):
        self.worker.cancel.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("取消中…")

    def on_full_progress(self, output):
        if self.closing or output["generation"] != self.generation:
            return
        self.display_result(output["frame"], output["frame_index"], output["result"], record=False)
        self.status_label.setText(f"分析 {output['frame_index'] + 1} / {output['total']} 帧")

    def export_statistics(self):
        self.when_idle(self._export_statistics)

    def _export_statistics(self):
        if not self.snapshots:
            QMessageBox.information(self, "导出统计", "尚无分析结果")
            return
        directory = PROJECT_ROOT / "outputs"
        directory.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "保存车道统计", str(directory / f"{self.camera}_lanes.csv"), "CSV (*.csv)")
        if not path:
            return
        try:
            self.write_exports(path)
            self.status_label.setText("统计已导出")
            self.export_button.setToolTip(f"导出统计 CSV\n上次导出：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))

    def write_exports(self, path):
        path = Path(path)
        fields = ["video", "segment_id", "config_revision", "frame_index", "video_seconds", "lane_id", "name", "group",
                  "current", "passed", "recent", "density", "low_speed", "score", "state", "valid"]
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for snapshot in self.snapshots:
                for row in snapshot["lanes"]:
                    record = {key: row.get(key) for key in fields}
                    record.update(video=self.video_path, segment_id=snapshot["segment_id"], config_revision=self.config_revision,
                                  frame_index=round(snapshot["timestamp"] * self.player.fps), video_seconds=snapshot["timestamp"])
                    writer.writerow(record)
        with path.with_name(path.stem + "_events.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["video", "segment_id", "config_revision", "timestamp", "track_id", "lane_id", "class_name"])
            writer.writeheader()
            segment = self.snapshots[0]["segment_id"]
            for event in self.events:
                writer.writerow({**event, "video": self.video_path, "segment_id": segment, "config_revision": self.config_revision})
        metadata = {"video": self.video_path, "model": self.model_path, "camera": self.camera,
                    "config_revision": self.config_revision, "full_video": self.cache is not None,
                    "fps": self.player.fps, "frame_size": list(self.video_label.frame_size),
                    "parameters": dict(self.analysis_settings),
                    "formula": "100 * D * L", "relative_speed_unit": "box_heights_per_second"}
        from dataclasses import asdict

        metadata["lanes"] = [asdict(lane) for lane in self.lanes]
        path.with_name(path.stem + "_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def format_time(seconds):
        minutes, remainder = divmod(max(0, int(seconds)), 60)
        return f"{minutes:02}:{remainder:02}"

    def closeEvent(self, event):
        if not self.thread.isRunning():
            self.player.release()
            event.accept()
            return
        self.timer.stop()
        self.closing = True
        self.worker.cancel.set()
        self.pending_action = None
        self.setEnabled(False)
        self.status_label.setText("关闭中…")
        self.thread.quit()
        event.ignore()

    def finish_close(self):
        if self.closing:
            self.close()
