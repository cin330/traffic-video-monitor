# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Time-weighted rolling windows and hysteresis in source-video seconds."""

from collections import deque


class CongestionAnalyzer:
    def __init__(self, window=10.0, hold=5.0, enter=65.0, exit=45.0):
        self.window, self.hold, self.enter, self.exit = window, hold, enter, exit
        self.histories, self.states, self.pending = {}, {}, {}

    def update(self, lane, timestamp, dt, current, valid, slow, previous_count):
        history = self.histories.setdefault(lane.id, deque())
        if 0 < dt <= 1:
            history.append((timestamp - dt, timestamp, previous_count, valid, slow))
        cutoff = timestamp - self.window
        while history and history[0][1] <= cutoff:
            history.popleft()
        duration = count_time = valid_time = slow_time = occupied_time = 0.0
        for start, end, count, observations, slow_observations in history:
            weight = max(0, end - max(start, cutoff))
            duration += weight
            count_time += count * weight
            valid_time += observations * weight
            slow_time += slow_observations * weight
            occupied_time += count * weight
        density = min(count_time / duration / lane.reference_count, 1) if duration else 0
        low_speed = slow_time / valid_time if valid_time else None
        # Warm up for the full window; require enough tracked motion coverage.
        ready = duration >= self.window - 1e-6
        empty = ready and occupied_time == 0 and current == 0
        sufficient = empty or (valid_time > 0 and valid_time / max(occupied_time, 1e-8) >= 0.5)
        score = 0.0 if empty else (100 * density * low_speed if ready and sufficient else None)
        if not ready or not sufficient:
            self.pending.pop(lane.id, None)
            state = "分析中" if not ready else "数据不足"
        else:
            old_state = self.states.get(lane.id, "分析中")
            target = "拥堵" if score >= self.enter else ("畅通" if score <= self.exit else None)
            if empty:
                self.states[lane.id] = "畅通"
                self.pending.pop(lane.id, None)
            elif target is None or target == old_state:
                self.pending.pop(lane.id, None)
            else:
                old_pending = self.pending.get(lane.id)
                if old_pending is None or old_pending[0] != target:
                    self.pending[lane.id] = (target, timestamp)
                elif timestamp - old_pending[1] >= self.hold - 1e-6:
                    self.states[lane.id] = target
                    self.pending.pop(lane.id, None)
            state = self.states.get(lane.id, "分析中")
        return {"density": density, "low_speed": low_speed, "score": score,
                "state": state, "valid": score is not None, "window_seconds": duration}
