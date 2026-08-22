# FPS、USB 与分辨率延迟实验计划

## 要验证的假设

提高 FPS 会缩短相邻采样间隔：30fps 一帧约 33.3ms，60fps 约 16.7ms，
90fps 约 11.1ms。因此随机事件等待下一次曝光的平均相位等待通常会下降。
但端到端延迟还包含曝光、USB 传输、像素格式转换、驱动/SDK 队列、应用计算和
显示刷新；高 FPS 可能因带宽或 CPU 饱和反而变差，必须测量而不能只看枚举值。

提高 RGB 分辨率同样不是单向收益。它可能改善特征点数量和识别距离，但会增加
每帧字节数、YUYV/RGB 转换、内存带宽、DDS 序列化和推理成本。

## 第一阶段单流矩阵

每个组合预热 10 秒、采样 60 秒、重复至少 3 次；固定显示器刷新率、USB 端口、
曝光模式、场景亮度和相机到屏幕距离。

| 设备 | Stream/profile | 目的 | 状态 |
| --- | --- | --- | --- |
| R200 | Color 640×480@30 YUYV，depth off/on | 30fps 基线与 depth 负载 | R1 完成，待重复 |
| R200 | Color 640×480@60 YUYV，depth off/on | 验证高 FPS 延迟收益 | R1 完成，待重复 |
| R200 | Color 320×240@60 YUYV，depth off/on | 区分 RGB 分辨率与 FPS | R1 完成，待重复 |
| R200 | Color 1920×1080@30 YUYV，depth off/on | 最高 RGB 质量权衡 | R1 完成，待重复 |
| R200 | Color 640×480@60 + Depth 640×480@90 | 最大 VGA depth FPS 负载 | R1 完成，实际约 60fps |
| R200 | Color 640×480@60 + Depth 320×240@90 | 近距 depth 模式与最大 FPS | R1 完成，实际约 60fps |
| SR300 | 自动枚举后的 color 30/60 档 | 跨型号比较 | 待硬件 |

每次保存：

- visual latency median / p95 / average；
- capture callback FPS；
- arrival→callback（若 metadata 可用）；
- overwritten frames、USB/SDK 警告、CPU 和 RSS；
- frame timestamp domain；
- 是否使用自动曝光、曝光值和显示器刷新率。

仓库的 `scripts/run-matrix.sh` 实现上述 10 组，每组默认重复 3 次。运行期间不移动
相机、窗口或显示器；任何 `samples=0` 的轮次都视为无效并重新采样，不能用
`capture_fps` 替代视觉延迟结果。

## 第二阶段组合负载

单流基线完成后，另建模式逐项增加 depth、IR、ROS2、RGB conversion、视觉模型
和点云。每次只增加一个变量，以确定延迟来自 USB、SDK 合成处理、DDS 还是算法。
不要直接拿“全功能 RViz”结果代表相机本体延迟。

## 判定原则

- 以 p95 而不只是平均值决定 VSLAM profile；定位更怕长尾抖动。
- FPS 必须由 callback 实测速率确认。
- 高分辨率只有在视觉精度收益大于延迟/吞吐代价时采用。
- 若 60fps 只降低中位数却显著增加 p95、丢帧或 CPU，应保留 30fps 稳定档。
- 设备/profile/固件/SDK/内核/USB 拓扑变化后结果不可直接沿用。
