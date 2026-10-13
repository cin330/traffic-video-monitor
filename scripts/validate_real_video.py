# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

"""Run an offscreen Qt/real-YOLO end-to-end check and export reviewable evidence."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from detect.lane_manager import LaneManager
from gui.gui import Traffic_monitor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default="video/car_stream.mp4")
    parser.add_argument("--model", default="models/best.pt")
    parser.add_argument("--config", default="config/lanes/car_stream_example.json")
    parser.add_argument("--output", default="outputs/real_video_validation")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    window = Traffic_monitor()
    window.show()
    window.video_path = str(Path(args.video).resolve())
    assert window.player.open_video(window.video_path), "Video did not open"
    window.progress_slider.setRange(0, window.player.get_frame() - 1)
    manager, config = LaneManager.load(args.config)
    window.camera = config["camera"]
    window.analysis_settings = config["analysis"]
    window.set_lanes(manager.lanes)
    started = time.monotonic()
    heartbeat = [0]
    status = {"success": False}
    pulse = QTimer()
    pulse.timeout.connect(lambda: heartbeat.__setitem__(0, heartbeat[0] + 1))
    pulse.start(100)

    def progress(payload):
        if payload["frame_index"] % max(1, round(window.player.fps * 5)) == 0:
            print(f"Analyzed {payload['frame_index'] + 1}/{payload['total']} frames; GUI pulses {heartbeat[0]}", flush=True)

    def completed(payload):
        if "error" in payload:
            status["error"] = payload["error"]
            window.close()
        elif payload["kind"] == "load":
            window._full_analysis()
        elif payload["kind"] == "full" and not payload.get("cancelled"):
            assert len(window.cache) == window.player.get_frame()
            final = window.cache[-1]
            window.seek_to_frame(len(window.cache) - 1, resume=False)
            window.write_exports(output / "lanes.csv")
            window.grab().save(str(output / "preview.png"))
            report = {
                "success": True, "video": window.video_path, "model": str(Path(args.model).resolve()),
                "frames": len(window.cache), "fps": window.player.fps,
                "elapsed_seconds": round(time.monotonic() - started, 3), "gui_heartbeat_count": heartbeat[0],
                "events": len(window.events), "snapshots": len(window.snapshots),
                "lanes_final": final["lanes"], "groups_final": final["groups"],
                "accuracy_verified_against_manual_labels": False,
                "notes": "Example lane boundaries and relative-motion thresholds require camera-specific calibration.",
            }
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: report[key] for key in ("success", "frames", "elapsed_seconds", "gui_heartbeat_count", "events")}), flush=True)
            status["success"] = True
            window.close()

    window.worker.completed.connect(completed)
    window.worker.progress.connect(progress)

    def timeout():
        status["error"] = "Timed out after 10 minutes"
        window.worker.cancel.set()
        window.close()

    QTimer.singleShot(600000, timeout)
    QTimer.singleShot(0, lambda: window.submit("load", path=str(Path(args.model).resolve())))
    app.exec()
    if not status["success"]:
        raise RuntimeError(status.get("error", "Validation did not complete"))


if __name__ == "__main__":
    main()
