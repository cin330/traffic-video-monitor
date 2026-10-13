# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Pure sequential analysis shared by live playback and whole-video analysis."""

from collections import Counter
from uuid import uuid4

from detect.congestion_analyzer import CongestionAnalyzer
from detect.lane_manager import LaneManager, contains, validate_analysis_settings
from detect.motion_analyzer import MotionAnalyzer
from detect.vec_count import LaneVehicleCounter

VEHICLE_CLASSES = ("car", "bus", "truck", "van")


class TrafficAnalysis:
    def __init__(self, lanes, settings=None):
        self.manager = LaneManager(lanes)
        self.counter = LaneVehicleCounter(self.manager.lanes)
        self.motion = MotionAnalyzer()
        self.settings = validate_analysis_settings(settings)
        self.congestion = CongestionAnalyzer(**self.settings)
        self.segment_id = uuid4().hex[:12]
        self.last_time = None
        self.previous_counts = {}

    def update(self, detections, timestamp, frame_size):
        if self.last_time is not None and timestamp <= self.last_time:
            raise ValueError("分析时间必须递增；跳转后需要重置分析")
        dt = timestamp - self.last_time if self.last_time is not None else 0
        if dt > 1:
            # Source discontinuity: preserve passed events, invalidate rolling state and tracks.
            self.motion = MotionAnalyzer()
            self.congestion = CongestionAnalyzer(**self.settings)
            self.manager.assignments.clear()
            self.counter.anchors.clear()
            self.previous_counts.clear()
            dt = 0
        width, height = frame_size
        vehicles, seen = [], set()
        current = {lane.id: Counter() for lane in self.manager.lanes}
        valid = Counter()
        slow = Counter()
        for detection in detections:
            name = str(detection["class_name"]).strip().lower()
            track_id = detection["id"]
            if name not in VEHICLE_CLASSES or track_id in seen:
                continue
            seen.add(track_id)
            vehicle = {**detection, "class_name": name}
            point = (vehicle["center"][0] / width, vehicle["center"][1] / height)
            lane_id = self.manager.assign(track_id, point, timestamp)
            speed = self.motion.update(vehicle, timestamp)
            vehicle.update(lane_id=lane_id, relative_speed=speed)
            vehicles.append(vehicle)
            for lane in self.manager.lanes:
                if lane.id == lane_id and contains(lane.monitoring_polygon, point):
                    current[lane.id][name] += 1
                    if speed is not None:
                        valid[lane.id] += 1
                        if speed <= lane.slow_threshold:
                            slow[lane.id] += 1
                    break
        event_start = len(self.counter.events)
        self.counter.update(vehicles, timestamp, frame_size, self.manager)
        rows = []
        for lane in self.manager.lanes:
            count = sum(current[lane.id].values())
            metrics = self.congestion.update(lane, timestamp, dt, count, valid[lane.id], slow[lane.id],
                                             self.previous_counts.get(lane.id, count))
            rows.append({"lane_id": lane.id, "name": lane.name, "group": lane.group,
                         "current": count, "passed": sum(self.counter.passed[lane.id].values()),
                         "recent": self.counter.recent_count(lane.id, timestamp),
                         "classes_current": dict(current[lane.id]),
                         "classes_passed": dict(self.counter.passed[lane.id]), **metrics})
            self.previous_counts[lane.id] = count
        self.last_time = timestamp
        self.manager.prune(timestamp)
        self.motion.prune(timestamp)
        groups = {}
        for group in dict.fromkeys(lane.group for lane in self.manager.lanes):
            states = [row["state"] for row in rows if row["group"] == group]
            blocked = states.count("拥堵")
            if any(state not in ("拥堵", "畅通") for state in states):
                groups[group] = "结果不完整"
            elif blocked * 2 >= len(states):
                groups[group] = "拥堵"
            elif blocked:
                groups[group] = "局部拥堵"
            else:
                groups[group] = "畅通"
        return {"timestamp": timestamp, "segment_id": self.segment_id, "vehicles": vehicles,
                "lanes": rows, "groups": groups, "events": self.counter.events[event_start:]}
