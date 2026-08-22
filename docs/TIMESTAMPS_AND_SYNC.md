# 时间戳、同步与 VSLAM 注意事项

## 先区分四件事

1. **视觉事件延迟**：屏幕变化到应用拿到包含变化的帧。本 Demo 的圆点时钟测
   的是它。
2. **frame timestamp**：`frame.get_timestamp()`，含义取决于
   `frame.get_frame_timestamp_domain()`。
3. **backend arrival time**：帧进入后端/驱动附近的主机时刻；只有 metadata
   支持时才能读取。
4. **多传感器同步误差**：RGB、depth、左右 IR、陀螺仪是否对应同一物理时刻。

这四项不能互相替代。尤其不能因为两个 timestamp 数值接近就宣称曝光同步。

## librealsense 官方原则

- sensor callback 由底层 IO 线程尽快调用，是最低延迟 API 路径；耗时工作应移
  出 callback。
- frame queue 越深越不容易丢帧，但旧帧排队会增加延迟。官方缓冲说明建议低
  延迟场景把 capacity 控制在 1（仅 depth）或 2（depth+color）。本项目只有
  单流，因此固定为 1。
- `syncer` 会等待可组成帧组的数据；官方文档明确说一般情况下不保证时间同步
  质量，只有设备提供硬件时间戳/硬件同步时才可能利用。
- Global Time 是硬件时钟到主机时间域的估计/校正机制，不等于零误差曝光时刻。

## 当前 R200

当前社区 R200 RS2 2.51.1 移植报告 `RS2_TIMESTAMP_DOMAIN_SYSTEM_TIME`。
R200 固件传输行中有 frame counter，但没有已证明可用于 RS2 的真实硬件曝光
时钟；旧 RS1 按 FPS 合成时间线不能作为硬件时钟证据。因此：

- 圆点视觉延迟可用于比较 R200 的 profile；
- frame timestamp 可用于主机侧排序和诊断；
- 不能把它直接当成精确曝光时间；
- 后续与外置陀螺仪做 VSLAM，必须实测相机与 IMU 的时间偏移、漂移和抖动。

## SR300

librealsense 官方 support matrix 标明 SR300 不支持 Global Timestamp。SR300
接入后必须运行实际 metadata/domain 记录，不能套用 D400 的 global-time 假设。
屏幕延迟测试应优先 color；官方 `rs-latency-tool` 文档指出 SR300 IR 通常无法
可靠看到显示器图案。

## 后续 VSLAM 的最低门禁

在把 RGB/depth/gyro 输入定位算法前，至少完成：

- 逐流记录 timestamp domain、frame number、backend arrival 和 callback time；
- 测量 RGB↔depth、RGB↔gyro 的固定 offset、短期 jitter 和 30 分钟 drift；
- 分开报告采集延迟、ROS/DDS 延迟、视觉推理延迟和状态估计延迟；
- 检查丢帧后同步器行为，不能用“最近一帧”掩盖大时间差；
- 若陀螺仪使用不同 USB 设备/时钟，采用可估计 offset/drift 的时间模型；
- 对无硬件同步的设备明确写出同步精度上限，不宣传微秒级同步。

高 FPS 只缩短采样周期，不会自动修正时钟域、曝光中点定义或跨设备漂移。
