# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import json
import tempfile
import unittest
from pathlib import Path

from core.traffic_analysis import TrafficAnalysis
from detect.congestion_analyzer import CongestionAnalyzer
from detect.lane_manager import Lane, LaneManager
from detect.motion_analyzer import MotionAnalyzer


def lane(lane_id="a", left=0.1, right=0.9, direction=None, capacity=1):
    return Lane(lane_id, f"车道 {lane_id}", [[left, .05], [right, .05], [right, .95], [left, .95]],
                [[left + .01, .6], [right - .01, .6]], direction or [0, 1], reference_count=capacity)


def vehicle(track_id=1, x=50, y=50, name="car", height=20):
    return {"id": track_id, "class_name": name, "center": (x, y), "box": [x - 5, y - height, x + 5, y]}


class AnalysisTests(unittest.TestCase):
    def test_finite_directional_line_and_id_deduplication(self):
        engine = TrafficAnalysis([lane()])
        engine.update([vehicle(y=50)], 0, (100, 100))
        result = engine.update([vehicle(y=70), vehicle(y=70)], .1, (100, 100))
        self.assertEqual(result["lanes"][0]["passed"], 1)
        self.assertEqual(result["lanes"][0]["current"], 1)
        self.assertEqual(len(result["events"]), 1)
        engine.update([vehicle(y=50)], .2, (100, 100))
        result = engine.update([vehicle(y=70)], .3, (100, 100))
        self.assertEqual(result["lanes"][0]["passed"], 1)
        reverse = TrafficAnalysis([lane()])
        reverse.update([vehicle(y=70)], 0, (100, 100))
        self.assertEqual(reverse.update([vehicle(y=50)], .1, (100, 100))["lanes"][0]["passed"], 0)
        outside = TrafficAnalysis([lane()])
        outside.update([vehicle(x=95, y=50)], 0, (100, 100))
        self.assertEqual(outside.update([vehicle(x=95, y=70)], .1, (100, 100))["lanes"][0]["passed"], 0)

    def test_tolerance_band_keeps_continuity_during_long_stop(self):
        engine = TrafficAnalysis([lane()])
        engine.update([vehicle(y=59)], 0, (100, 100))
        for index in range(1, 41):
            result = engine.update([vehicle(y=60)], index / 10, (100, 100))
            self.assertEqual(result["lanes"][0]["passed"], 0)
        result = engine.update([vehicle(y=62)], 4.1, (100, 100))
        self.assertEqual(result["lanes"][0]["passed"], 1)

    def test_lane_change_crossing_uses_intersection_lane(self):
        engine = TrafficAnalysis([lane("a", .05, .49), lane("b", .5, .95)])
        engine.update([vehicle(x=40, y=50)], 0, (100, 100))
        result = engine.update([vehicle(x=70, y=70)], .1, (100, 100))
        self.assertEqual([row["passed"] for row in result["lanes"]], [0, 1])
        self.assertEqual(result["events"][0]["lane_id"], "b")

    def test_missing_observations_and_large_gap_do_not_count(self):
        engine = TrafficAnalysis([lane()])
        engine.update([vehicle(y=50)], 0, (100, 100))
        engine.update([], .8, (100, 100))
        result = engine.update([vehicle(y=70)], 1.2, (100, 100))
        self.assertEqual(result["lanes"][0]["passed"], 0)
        result = engine.update([vehicle(y=50)], 5, (100, 100))
        self.assertEqual(result["lanes"][0]["state"], "分析中")

    def test_stationary_queue_becomes_red_and_empty_recovers(self):
        engine = TrafficAnalysis([lane()])
        for index in range(161):
            result = engine.update([vehicle()], index / 10, (100, 100))
        self.assertEqual(result["lanes"][0]["state"], "拥堵")
        self.assertGreater(result["lanes"][0]["score"], 90)
        for index in range(161, 311):
            result = engine.update([], index / 10, (100, 100))
        self.assertEqual(result["lanes"][0]["state"], "畅通")
        self.assertEqual(result["lanes"][0]["score"], 0)

    def test_low_density_stationary_traffic_is_green(self):
        engine = TrafficAnalysis([lane(capacity=10)])
        for index in range(161):
            result = engine.update([vehicle()], index / 10, (100, 100))
        self.assertEqual(result["lanes"][0]["state"], "畅通")
        self.assertLess(result["lanes"][0]["score"], 15)

    def test_no_motion_history_stays_unknown(self):
        engine = TrafficAnalysis([lane()])
        for index in range(161):
            result = engine.update([vehicle(track_id=index)], index / 10, (100, 100))
        self.assertEqual(result["lanes"][0]["state"], "数据不足")
        self.assertIsNone(result["lanes"][0]["score"])

    def test_source_fps_not_wall_clock_controls_windows(self):
        scores = []
        for fps in (10, 25):
            engine = TrafficAnalysis([lane()])
            for index in range(fps * 16 + 1):
                result = engine.update([vehicle()], index / fps, (100, 100))
            scores.append(result["lanes"][0]["score"])
            self.assertEqual(result["lanes"][0]["state"], "拥堵")
        self.assertAlmostEqual(scores[0], scores[1], delta=1)

    def test_rolling_minute_event_expiry_and_class_filter(self):
        engine = TrafficAnalysis([lane()])
        engine.update([vehicle(name="Car"), vehicle(track_id=99, name="person")], 0, (100, 100))
        result = engine.update([vehicle(y=70, name="Car")], .1, (100, 100))
        self.assertEqual(result["lanes"][0]["classes_passed"], {"car": 1})
        result = engine.update([], 61, (100, 100))
        self.assertEqual(result["lanes"][0]["recent"], 0)
        self.assertEqual(result["lanes"][0]["passed"], 1)

    def test_relative_motion_respects_perspective_and_gap(self):
        analyzer = MotionAnalyzer()
        for index in range(11):
            t = index / 10
            near = analyzer.update(vehicle(1, y=50 + t * 10, height=20), t)
            far = analyzer.update(vehicle(2, y=50 + t * 5, height=10), t)
        self.assertAlmostEqual(near, .5)
        self.assertAlmostEqual(far, near)
        self.assertIsNone(analyzer.update(vehicle(1, y=90), 5))

    def test_hysteresis_preserves_state_and_requires_continuous_hold(self):
        analyzer = CongestionAnalyzer(window=1, hold=1)
        test_lane = lane()
        for index in range(31):
            result = analyzer.update(test_lane, index / 10, .1 if index else 0, 1, 1, 1, 1)
        self.assertEqual(result["state"], "拥堵")
        for index in range(31, 51):
            result = analyzer.update(test_lane, index / 10, .1, 1, 1, .55, 1)
        self.assertEqual(result["state"], "拥堵")
        self.assertAlmostEqual(result["score"], 55)

    def test_config_validation_and_round_trip(self):
        manager = LaneManager([lane()])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lanes.json"
            manager.save(path, "固定机位", (1920, 1080))
            loaded, metadata = LaneManager.load(path)
            self.assertEqual(loaded.lanes[0], manager.lanes[0])
            self.assertEqual(metadata["camera"], "固定机位")
            data = json.loads(path.read_text())
            data["lanes"][0]["reference_count"] = 0
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                LaneManager.load(path)
        bad = lane()
        bad.direction = [1, 0]
        with self.assertRaises(ValueError):
            bad.validate()
        with self.assertRaises(ValueError):
            LaneManager([lane(), lane()])

    def test_unknown_direction_prevents_complete_road_claim(self):
        engine = TrafficAnalysis([lane("a", .05, .49), lane("b", .5, .95)])
        result = engine.update([], 0, (100, 100))
        self.assertEqual(result["groups"], {"方向 A": "结果不完整"})


if __name__ == "__main__":
    unittest.main()
