# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import cv2
import math

class VideoPlayer:
    def __init__(self):

        self.cap = None
        self.fps = 30
        self.frame_count = 0

    def open_video(self,video_path):

        self.release()

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            self.release()
            return False
        
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)

        if not math.isfinite(self.fps) or self.fps <= 0:
            print("无法获取视频帧率，使用默认值30fps")
            self.fps = 30
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        return True
    def read_frame(self):

        if self.cap  is None:      
            return False, None
        ret,frame = self.cap.read()
        return ret, frame

    def get_frame(self):
        return self.frame_count

    def get_current_frame(self):
        if self.cap is None:
            return False
        return int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))

    def seek_frame(self, frame_number):
        if self.cap is None:
            return False
        if frame_number < 0 or frame_number >= self.frame_count:
            return False
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        return True
    

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.frame_count = 0
    

