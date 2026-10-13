# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

from ultralytics import YOLO


class YOLODetector:
    def __init__(self, model_path):
        self.model = YOLO(model_path)
        self.names = self.model.names

    def reset_tracking(self):
        predictor = getattr(self.model, "predictor", None)
        if predictor is not None:
            for tracker in getattr(predictor, "trackers", ()):
                tracker.reset()

    def detect_and_track(self, frame):
        results = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            conf=0.5,
            verbose=False,
        )
        if not results or results[0].boxes is None or results[0].boxes.id is None:
            return []

        boxes = results[0].boxes
        vehicles = []
        for box, track_id, class_id in zip(
            boxes.xyxy.cpu().numpy(),
            boxes.id.cpu().numpy(),
            boxes.cls.cpu().numpy(),
        ):
            x1, y1, x2, y2 = map(int, box)
            class_id = int(class_id)
            vehicles.append(
                {
                    "id": int(track_id),
                    "class_id": class_id,
                    "class_name": self.names[class_id],
                    "box": [x1, y1, x2, y2],
                    "center": ((x1 + x2) // 2, y2),
                }
            )
        return vehicles
