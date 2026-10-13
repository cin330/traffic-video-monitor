# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import csv
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from detect.lane_manager import Lane
from gui.gui import Traffic_monitor
from gui.lane_editor import LaneEditor


class FakeDetector:
    def reset_tracking(self):
        pass

    def detect_and_track(self, frame):
        return [{"id": 1, "class_name": "car", "center": (50, 70), "box": [40, 50, 60, 70]}]


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.avi"
        writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (100, 100))
        self.assertTrue(writer.isOpened())
        for _ in range(170):
            writer.write(np.full((100, 100, 3), 50, dtype=np.uint8))
        writer.release()
        self.window = Traffic_monitor()
        self.window.show()
        self.window.video_path = str(self.path)
        self.window.camera = "测试机位"
        self.assertTrue(self.window.player.open_video(str(self.path)))
        self.window.progress_slider.setRange(0, 169)
        self.window.worker.detector = FakeDetector()
        self.window.model_path = "fake.pt"
        self.window.next_frame()
        self.wait_until(lambda: not self.window.busy)
        self.lane = Lane("a", "车道一", [[.1, .05], [.9, .05], [.9, .95], [.1, .95]],
                         [[.11, .6], [.89, .6]], reference_count=1)
        self.window.set_lanes([self.lane])
        self.wait_until(lambda: not self.window.busy)

    def wait_until(self, predicate, timeout=10):
        start = time.monotonic()
        while not predicate():
            self.app.processEvents()
            if time.monotonic() - start > timeout:
                self.fail("Qt workflow timed out")
            time.sleep(.002)
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.wait_until(lambda: not self.window.thread.isRunning())
        self.app.processEvents()
        self.directory.cleanup()

    def test_background_playback_seek_and_export(self):
        self.window.next_frame()
        self.wait_until(lambda: not self.window.busy)
        self.assertEqual(self.window.result["lanes"][0]["current"], 1)
        segment = self.window.result["segment_id"]
        self.window.set_speed(4)
        self.window.seek_to_frame(50, resume=False)
        self.wait_until(lambda: not self.window.busy)
        self.assertEqual(self.window.result["timestamp"], 5)
        self.assertNotEqual(self.window.result["segment_id"], segment)
        self.assertEqual(self.window.result["lanes"][0]["state"], "分析中")
        path = Path(self.directory.name) / "stats.csv"
        self.window.write_exports(path)
        with path.open(encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["video_seconds"], "5.0")
        self.assertEqual(rows[0]["lane_id"], "a")
        self.assertTrue(path.with_name("stats_events.csv").exists())
        self.assertTrue(path.with_name("stats_metadata.json").exists())

    def test_canvas_coordinates_ignore_letterbox_and_scale(self):
        canvas = self.window.video_label
        rect = canvas.image_rect()
        self.assertEqual(canvas.normalized_point(rect.center()), (.5, .5))
        self.assertIsNone(canvas.normalized_point(QPointF(-1, -1)))
        self.window.resize(1000, 700)
        self.app.processEvents()
        self.assertEqual(canvas.normalized_point(canvas.image_rect().center()), (.5, .5))
        self.window.grab().save("/tmp/traffic-gui-test.png")

    def test_editor_applies_visible_draft(self):
        editor = LaneEditor(self.window.raw_frame, [], self.window)
        editor.canvas.draft = {"polygon": self.lane.polygon, "line": self.lane.line, "monitor": []}
        editor.name.setText("新车道")
        self.assertTrue(editor.apply_lane())
        self.assertEqual(len(editor.lanes), 1)
        self.assertEqual(editor.lanes[0].name, "新车道")
        editor.select_lane(0)
        editor.capacity.setValue(12)
        editor.finish()
        self.assertEqual(editor.lanes[0].reference_count, 12)
        editor.close()

    def test_full_analysis_cache_replay_and_export(self):
        self.window._full_analysis()
        self.wait_until(lambda: not self.window.busy, timeout=20)
        self.assertIsNotNone(self.window.cache)
        self.assertEqual(len(self.window.cache), 170)
        self.assertEqual(self.window.cache[-1]["lanes"][0]["state"], "拥堵")
        segment = self.window.cache[-1]["segment_id"]
        self.window.seek_to_frame(160, resume=False)
        self.assertEqual(self.window.result["segment_id"], segment)
        self.assertEqual(self.window.result["lanes"][0]["state"], "拥堵")
        self.assertIn("全片", self.window.statistics_group.title())
        path = Path(self.directory.name) / "full.csv"
        self.window.write_exports(path)
        self.assertGreater(len(self.window.snapshots), 15)
        self.assertGreater(path.stat().st_size, 1000)

    def test_no_model_never_reports_empty_lane_as_green(self):
        self.window.worker.detector = None
        self.window.reset_detection()
        for _ in range(110):
            self.window.next_frame()
            self.wait_until(lambda: not self.window.busy)
        self.assertEqual(self.window.result["lanes"][0]["state"], "数据不足")
        self.assertIsNone(self.window.result["lanes"][0]["score"])


if __name__ == "__main__":
    unittest.main()
