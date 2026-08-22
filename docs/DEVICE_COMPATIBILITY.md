# 设备兼容状态

| 设备 | 枚举 | GUI 拉流 | 圆点解码 | 时间戳说明 | 状态 |
| --- | --- | --- | --- | --- | --- |
| R200 / FW 1.0.72.10 | PASS | PASS：RGB 60fps；RGB+depth 各 60fps | PASS：depth off 131、on 11 个对照样本 | SYSTEM_TIME | PARTIAL：矩阵待重复 |
| SR300 | 能力路径已实现 | 待硬件 | 使用 color，IR 不推荐 | Global Time 官方不支持 | PENDING |
| D400 系列 | 标准 RS2 profile 路径 | 待硬件 | 官方样例支持 color/IR | 按设备与选项实测 | PENDING |

2026-08-22 在 Ubuntu 22.04 GNOME Wayland 上确认：

- Intel 官方原始 `rs-latency-tool` 能打开 R200 1920×1080@30 BGR8；
- GNOME 未自动激活全屏 XWayland 窗口，且官方“任意键退出”容易造成窗口看似
  未出现；本项目改为 1280×720 普通窗口、Q/Esc 退出和可选全屏；
- 本项目自动选择 R200 Color 640×480@60 YUYV，并把 sensor/application queue
  设为 1；
- `--rotate 180` 同时旋转预览和检测，适合 USB 线限制导致的倒装相机。
- 同条件对照中，单 RGB median 80.26ms、RGB+depth median 83.01ms；depth-on
  只有 11 个样本，当前不能推断差异。首次功能验收为 73.41ms；详细口径见
  `R200_INITIAL_RESULTS.md`。

兼容状态只表示表中已列出的证据。没有 SR300 真机时，不得把“代码没有设备名
分支”写成 SR300 已通过。
