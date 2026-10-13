# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Normalized lane geometry, validated camera configurations and lane assignment."""

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

DEFAULT_ANALYSIS_SETTINGS = {"window": 10.0, "hold": 5.0, "enter": 65.0, "exit": 45.0}


def validate_analysis_settings(settings=None):
    values = dict(DEFAULT_ANALYSIS_SETTINGS)
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - set(values):
            raise ValueError("分析参数字段无效")
        values.update(settings)
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values.values()):
        raise ValueError("分析参数必须是有限数值")
    if not 1 <= values["window"] <= 120 or not .1 <= values["hold"] <= 60:
        raise ValueError("窗口须为 1～120 秒，持续确认时间须为 0.1～60 秒")
    if not 0 <= values["exit"] < values["enter"] <= 100:
        raise ValueError("阈值须满足 0 ≤ 退出阈值 < 进入阈值 ≤ 100")
    return values


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


def segment_intersection(a, b, c, d):
    r, s = subtract(b, a), subtract(d, c)
    denominator = cross(r, s)
    if abs(denominator) < 1e-10:
        return None
    delta = subtract(c, a)
    t, u = cross(delta, s) / denominator, cross(delta, r) / denominator
    if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= u <= 1 + 1e-8:
        return a[0] + t * r[0], a[1] + t * r[1]
    return None


def contains(polygon, point):
    return cv2.pointPolygonTest(np.asarray(polygon, dtype=np.float32), tuple(point), False) >= 0


def validate_polygon(points):
    if len(points) < 3:
        raise ValueError("区域至少需要 3 个点")
    if any(len(p) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p) for p in points):
        raise ValueError("坐标必须是 0～1 范围内的有限数值")
    if len(set(map(tuple, points))) != len(points):
        raise ValueError("区域不能包含重复顶点")
    area = abs(sum(cross(points[i], points[(i + 1) % len(points)]) for i in range(len(points)))) / 2
    if area < 1e-5:
        raise ValueError("区域面积太小")
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if segment_intersection(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]) is not None:
                raise ValueError("区域边界不能交叉")


@dataclass
class Lane:
    id: str
    name: str
    polygon: list
    line: list
    direction: list = field(default_factory=lambda: [0, 1])
    group: str = "方向 A"
    reference_count: float = 10.0
    slow_threshold: float = 0.25
    monitor: list = field(default_factory=list)

    def validate(self):
        if not isinstance(self.id, str) or not self.id or not isinstance(self.name, str) or not self.name:
            raise ValueError("车道编号和名称不能为空")
        if not isinstance(self.group, str) or not self.group.strip():
            raise ValueError("道路方向分组不能为空")
        validate_polygon(self.polygon)
        if len(self.line) != 2:
            raise ValueError("计数线需要两个端点")
        for p in self.line:
            if len(p) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in p):
                raise ValueError("计数线坐标无效")
        delta = subtract(self.line[1], self.line[0])
        if math.hypot(*delta) < 0.01:
            raise ValueError("计数线太短")
        # Check the whole line, including concave boundaries.
        for fraction in np.linspace(0, 1, 101):
            point = [self.line[0][i] + fraction * delta[i] for i in (0, 1)]
            if not contains(self.polygon, point):
                raise ValueError("计数线必须位于车道内部")
        if len(self.direction) != 2 or any(not math.isfinite(v) for v in self.direction):
            raise ValueError("行驶方向无效")
        if abs(cross(delta, self.direction)) < 1e-8:
            raise ValueError("行驶方向不能与计数线平行")
        if not math.isfinite(self.reference_count) or self.reference_count <= 0:
            raise ValueError("参考拥挤车辆数必须大于 0")
        if not math.isfinite(self.slow_threshold) or self.slow_threshold <= 0:
            raise ValueError("低速阈值必须大于 0")
        if self.monitor:
            validate_polygon(self.monitor)
            for i, a in enumerate(self.monitor):
                b = self.monitor[(i + 1) % len(self.monitor)]
                for fraction in np.linspace(0, 1, 101):
                    point = [a[k] + fraction * (b[k] - a[k]) for k in (0, 1)]
                    if not contains(self.polygon, point):
                        raise ValueError("监测区必须位于车道内部")

    @property
    def monitoring_polygon(self):
        return self.monitor or self.polygon


class LaneManager:
    def __init__(self, lanes=(), switch_delay=0.25):
        self.lanes = list(lanes)
        self.switch_delay = switch_delay
        ids = set()
        for lane in self.lanes:
            lane.validate()
            if lane.id in ids:
                raise ValueError("车道编号不能重复")
            ids.add(lane.id)
        self.assignments = {}

    def raw_lane(self, point):
        # Overlaps use explicit configuration order; never count the same point twice.
        return next((lane for lane in self.lanes if contains(lane.polygon, point)), None)

    def assign(self, track_id, point, timestamp):
        raw = self.raw_lane(point)
        raw_id = raw.id if raw else None
        previous = self.assignments.get(track_id)
        if previous is None or timestamp - previous[3] > 1.0:
            state = [raw_id, raw_id, timestamp, timestamp]
        else:
            state = previous
            if state[1] != raw_id:
                state[1], state[2] = raw_id, timestamp
            if timestamp - state[2] >= self.switch_delay:
                state[0] = raw_id
            state[3] = timestamp
        self.assignments[track_id] = state
        # Outside every lane must not inflate monitoring counts.
        return state[0] if raw_id is not None else None

    def prune(self, timestamp):
        self.assignments = {key: value for key, value in self.assignments.items() if timestamp - value[3] <= 3}

    def save(self, path, camera, frame_size, analysis=None):
        data = {"version": 1, "camera": camera, "frame_size": list(frame_size),
                "overlap_rule": "first_lane", "lanes": [asdict(lane) for lane in self.lanes],
                "analysis": validate_analysis_settings(analysis)}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("不支持的车道配置版本")
        lanes = data.get("lanes")
        if not isinstance(lanes, list) or not lanes:
            raise ValueError("配置中没有车道")
        manager = cls([Lane(**item) for item in lanes])
        data["analysis"] = validate_analysis_settings(data.get("analysis"))
        return manager, data
