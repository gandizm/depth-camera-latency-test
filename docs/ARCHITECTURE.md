# 架构与数据路径

## 目标

本项目的视觉延迟只由一个被选中的可见光或红外流解码；默认优先同时请求
640×480@90 Z16 depth 作为组合负载，`--no-depth` 用于单流基线。它不是 ROS
节点，也不在测量路径里启用
depth alignment、colorizer、pointcloud、同步器或多帧队列，以免把这些额外
处理的等待时间混进相机基础延迟。

## 数据路径

```text
RealSense sensor
    │ sensor.start(callback)
    ▼
最小 callback
    ├─ 记录 host callback 时刻、frame number、timestamp/domain
    └─ 覆盖 capacity=1 的 latest-frame slot
               │
               ▼
后台检测线程
    ├─ YUYV/RGB/BGR/Y8 → 灰度
    ├─ 可选 180° 旋转
    ├─ 低于 VGA 时仅将检测工作图等比放大到至少 640×480
    ├─ 全帧 Hough circles
    ├─ 选择横向跨度最大的一排
    └─ 校验 2-bit checksum 并解码屏幕时钟

GUI 主线程
    ├─ 生成下一组二进制圆点
    ├─ 等比 letterbox 显示检测预览和统计
    └─ 记录 imshow/waitKey 渲染调用耗时
```

辅助 depth callback 只计数并立即释放帧，不做深度处理。请求 profile 的 FPS 与
实测 callback FPS 分开报告。若视觉流与 depth 位于
同一 physical sensor，程序一次 `open()` 两个 profile 并用 stream type 路由；
若位于不同 sensor，则先全部 open 再 start，退出时反序 stop/close。

采集 callback 不执行 OpenCV 检测。检测慢于输入 FPS 时，新帧覆盖尚未处理的旧
帧；这会增加 `overwritten_frames`，但不会让延迟随队列长度持续增长。该选择
符合“VSLAM 更重视最新状态”的目标，但不适合要求零丢帧的录制任务。

## Profile 选择

`--policy low-latency` 的排序顺序为：

1. color 优先于 infrared；
2. FPS 更高优先；
3. 分辨率接近 640×480 优先；
4. 原生 YUYV/Y8 优先于 SDK 生成的 BGR8/RGB8；
5. 最后比较像素数。

`--policy quality` 则在 stream 类型之后优先像素数，再比较 FPS。任意显式
`--width/--height/--fps/--format` 都先作为硬过滤条件；没有匹配项时失败并要求
用户运行 `--list`，不会静默改用另一个 profile。

## 多设备边界

“多设备适配”指同一可执行文件能枚举并选择不同型号/序列号设备。每个测量进程
只打开一台相机的一个流，因为屏幕回拍结果必须对应唯一相机和 profile。需要
比较多台设备时分别运行并保存独立 CSV；未来若做同步测量，应建立单独模式，
不能把多个 callback 的时钟混在当前统计中。
