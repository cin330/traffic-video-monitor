# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import numpy as np

def process_video_frame(frame, contrast = 1.0, brightness = 0):

    frame = frame.astype(np.float32)  # 将帧转换为浮点数类型，以便进行处理

    frame = frame* contrast + brightness  # 调整对比度和亮度

    frame = np.clip(frame, 0, 255)  # 将像素值限制在 0 到 255 之间，防止溢出
    frame = frame.astype(np.uint8)  # 将帧转换回 uint8 类型
    return frame
