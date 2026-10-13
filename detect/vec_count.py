# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

from collections import Counter

from detect.lane_manager import cross, segment_intersection, subtract


class VehicleCounter:
    def __init__(self, line_ratio=0.6, margin=8):
        self.line_ratio = line_ratio
        self.margin = margin
        self.current_counts = Counter()
        self.passed_counts = Counter()
        self.last_sides = {}
        self.counted_id = set()

    def update(self, vehicles, frame_height):
        self.current_counts.clear()
        line_y = int(frame_height * self.line_ratio)

        for vehicle in vehicles:
            trace_id = vehicle['id']
            class_name = vehicle['class_name']
            self.current_counts[class_name] += 1
            y = vehicle['center'][1]

            if y < line_y - self.margin:
                side = -1
            elif y > line_y + self.margin:
                side = 1
            else:
                continue

            old_side = self.last_sides.get(trace_id)
            if (old_side is not None and old_side != side
                    and trace_id not in self.counted_id):
                self.passed_counts[class_name] += 1
                self.counted_id.add(trace_id)

            self.last_sides[trace_id] = side

        current_total = sum(self.current_counts.values())
        pass_total = sum(self.passed_counts.values())
        return current_total, pass_total

    def reset(self):
        self.current_counts.clear()
        self.passed_counts.clear()
        self.last_sides.clear()
        self.counted_id.clear()


class LaneVehicleCounter:
    """One event per tracked vehicle at this road cross-section per analysis segment."""

    def __init__(self, lanes, margin=0.004, max_gap=1.0):
        self.lanes = lanes
        self.margin, self.max_gap = margin, max_gap
        self.anchors = {}
        self.counted_ids = set()
        self.passed = {lane.id: Counter() for lane in lanes}
        self.events = []

    def update(self, vehicles, timestamp, frame_size, manager):
        import math

        width, height = frame_size
        for vehicle in vehicles:
            track_id = vehicle["id"]
            point = (vehicle["center"][0] / width, vehicle["center"][1] / height)
            for lane in self.lanes:
                key = (track_id, lane.id)
                a, b = lane.line
                line_vector = subtract(b, a)
                distance = cross(line_vector, subtract(point, a)) / math.hypot(*line_vector)
                side = 1 if distance > self.margin else (-1 if distance < -self.margin else 0)
                previous = self.anchors.get(key)
                if previous and not 0 < timestamp - previous[2] <= self.max_gap:
                    previous = None
                    self.anchors.pop(key, None)
                if side == 0:
                    if previous:
                        self.anchors[key] = (previous[0], previous[1], timestamp)
                    continue
                if previous and previous[1] != side and track_id not in self.counted_ids:
                    movement = subtract(point, previous[0])
                    intersection = segment_intersection(previous[0], point, a, b)
                    direction_ok = sum(movement[i] * lane.direction[i] for i in (0, 1)) > 0
                    actual_lane = manager.raw_lane(intersection) if intersection else None
                    if direction_ok and actual_lane and actual_lane.id == lane.id:
                        self.counted_ids.add(track_id)
                        self.passed[lane.id][vehicle["class_name"]] += 1
                        self.events.append({"timestamp": timestamp, "track_id": track_id,
                                            "lane_id": lane.id, "class_name": vehicle["class_name"]})
                self.anchors[key] = (point, side, timestamp)
        self.anchors = {key: value for key, value in self.anchors.items() if timestamp - value[2] <= 3}

    def recent_count(self, lane_id, timestamp):
        # Events remain available for export; reverse traversal only scans the last minute.
        count = 0
        for event in reversed(self.events):
            if event["timestamp"] <= timestamp - 60:
                break
            if event["lane_id"] == lane_id:
                count += 1
        return count
