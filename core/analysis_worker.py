# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Single-owner YOLO worker; all requests run sequentially off the GUI thread."""

from threading import Event

import cv2
from PySide6.QtCore import QObject, Signal, Slot

from core.traffic_analysis import TrafficAnalysis


class AnalysisWorker(QObject):
    completed = Signal(object)
    progress = Signal(object)

    def __init__(self):
        super().__init__()
        self.detector = None
        self.engine = TrafficAnalysis([])
        self.cancel = Event()

    @Slot(object)
    def execute(self, job):
        kind, generation = job["kind"], job["generation"]
        try:
            if kind == "load":
                from detect.yolo_detector import YOLODetector

                detector = YOLODetector(job["path"])
                self.detector = detector
                output = {"kind": kind, "generation": generation, "path": job["path"]}
            elif kind == "reset":
                self.engine = TrafficAnalysis(job["lanes"], job.get("settings"))
                if self.detector is not None:
                    self.detector.reset_tracking()
                return
            elif kind == "frame":
                frame = job["frame"]
                detections = self.detector.detect_and_track(frame) if self.detector is not None else []
                result = self.engine.update(detections, job["timestamp"], (frame.shape[1], frame.shape[0]))
                if self.detector is None:
                    for row in result["lanes"]:
                        row.update(state="数据不足", valid=False, score=None)
                    result["groups"] = {group: "结果不完整" for group in result["groups"]}
                output = {"kind": kind, "generation": generation, "frame": frame,
                          "frame_index": job["frame_index"], "result": result}
            elif kind == "full":
                output = self.analyze_full(job)
            else:
                raise ValueError("未知分析任务")
            self.completed.emit(output)
        except Exception as exc:
            self.completed.emit({"kind": kind, "generation": generation, "error": str(exc)})

    def analyze_full(self, job):
        if self.detector is None:
            raise ValueError("请先加载检测模型")
        cap = cv2.VideoCapture(job["path"])
        try:
            if not cap.isOpened():
                raise ValueError("视频打开失败")
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.detector.reset_tracking()
            engine = TrafficAnalysis(job["lanes"], job.get("settings"))
            cache, snapshots, events = [], [], []
            last_record = -1.0
            index = 0
            while not self.cancel.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                detections = self.detector.detect_and_track(frame)
                result = engine.update(detections, index / job["fps"], (frame.shape[1], frame.shape[0]))
                events.extend(result["events"])
                # Metadata only; cache source frame geometry and per-lane results, not pixels.
                cache.append(result)
                if result["timestamp"] - last_record >= 1:
                    snapshots.append(result)
                    last_record = result["timestamp"]
                if index % max(1, int(job["fps"])) == 0:
                    self.progress.emit({"generation": job["generation"], "frame": frame,
                                        "frame_index": index, "total": total, "result": result})
                index += 1
            if self.cancel.is_set():
                return {"kind": "full", "generation": job["generation"], "cancelled": True}
            if not cache:
                raise ValueError("视频没有可分析的帧")
            return {"kind": "full", "generation": job["generation"], "cache": cache,
                    "snapshots": snapshots, "events": events}
        finally:
            cap.release()
            self.detector.reset_tracking()
