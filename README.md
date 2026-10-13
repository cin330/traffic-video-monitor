# 交通视频监控系统

基于 PySide6、YOLO 和 ByteTrack 的交通视频分析桌面系统。支持车辆检测与跟踪、图形化车道配置、方向性跨线计数、分车道流量、相对运动与拥堵分析、完整视频后台分析、缓存回放及 CSV/JSON 导出。

## 视频演示

https://github.com/user-attachments/assets/b97ec3a9-dacd-4175-a89a-6a5060686186

时长 60 秒，1920×1080。完整 MP4 保存在 `demo/demo.mp4`。

## 安装与启动

推荐 Python 3.11。进入仓库根目录后执行：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

保留当前程序使用的 Ultralytics 8.4.175 源码及其上游许可证，位于 `ultralytics-src/`。依赖文件通过 editable 安装该目录，`ultralytics` 相对符号链接也与原项目一致。未包含上游 Git 历史、训练数据集、训练过程输出和重复权重。

## 运行示例

1. 打开 `video/car_stream.mp4`。
2. 加载 `models/best.pt`。
3. 加载 `config/lanes/car_stream_example.json`，检查车道、计数线和通行方向。
4. 播放或执行完整视频分析，再导出统计结果。

计数与拥堵阈值使用视频坐标、相对运动及视频时间，需要按实际机位校准；当前结果不提供经过物理标定的车辆速度。

## 验证


```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
# 可选：使用实际 YOLO 权重分析示例视频
QT_QPA_PLATFORM=offscreen python scripts/validate_real_video.py
```

最终版冻结为 `v1.0.0`。18 项现有测试通过，覆盖 GUI 流程、跨线计数、车道配置、缓存回放、拥堵状态和导出。自动化 GUI 测试使用模拟检测结果，不能替代真实检测精度验证。冻结信息及文件校验值见 `FINAL_VERSION.json`。

## 第三方组件

`ultralytics-src/` 来自 Ultralytics，保留 AGPL-3.0 许可证与原有声明。模型和示例视频保留自本地项目；本仓库未替其声明新的许可证。第三方文件信息见 `THIRD_PARTY.md`。

## 版权与项目介绍

Copyright (c) 2026 cin330。原创部分以 [AGPL-3.0](LICENSE) 发布，使用、修改及分发须保留署名并遵守许可。第三方内容保留原有权利。

[三个项目的完整中文介绍](PROJECT_INTRODUCTION.md) · [版权声明](COPYRIGHT.md) · [第三方组件](THIRD_PARTY.md)
