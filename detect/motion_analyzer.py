# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Relative motion only: normalized box-heights per second, never km/h."""

import math
from collections import deque


class MotionAnalyzer:
    def __init__(self, max_gap=1.0, min_span=0.4):
        self.max_gap, self.min_span = max_gap, min_span
        self.tracks = {}

    def update(self, vehicle, timestamp):
        track_id = vehicle["id"]
        x, y = vehicle["center"]
        box = vehicle["box"]
        height = max(1, box[3] - box[1])
        history = self.tracks.setdefault(track_id, deque())
        if history:
            gap = timestamp - history[-1][0]
            jump = math.hypot(x - history[-1][1], y - history[-1][2]) / max(height, history[-1][3])
            if gap <= 0 or gap > self.max_gap or jump / gap > 12:
                history.clear()
        history.append((timestamp, x, y, height))
        while len(history) > 2 and timestamp - history[1][0] > 0.8:
            history.popleft()
        first = history[0]
        span = timestamp - first[0]
        if span < self.min_span:
            return None
        # Least-squares slope smooths detection jitter without assuming frame rate.
        mean_t = sum(v[0] for v in history) / len(history)
        denominator = sum((v[0] - mean_t) ** 2 for v in history)
        if denominator <= 0:
            return None
        vx = sum((v[0] - mean_t) * v[1] for v in history) / denominator
        vy = sum((v[0] - mean_t) * v[2] for v in history) / denominator
        mean_height = sum(v[3] for v in history) / len(history)
        return math.hypot(vx, vy) / mean_height

    def prune(self, timestamp):
        self.tracks = {key: value for key, value in self.tracks.items() if timestamp - value[-1][0] <= 3}
