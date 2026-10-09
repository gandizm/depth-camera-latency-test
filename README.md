# RS2 Latency Lab

一个基于 Intel RealSense 官方 `rs-latency-tool` 的设备无关视觉延迟 Demo。
它让摄像头回拍屏幕上的二进制圆点时钟，从而估算“屏幕事件发生 → 帧到达应用”
的端到端视觉延迟，同时记录应用收到帧时可用的时间戳域和
`TIME_OF_ARRIVAL` 到 callback 的主机侧延迟。

当前基线是 librealsense 2.51.1、Ubuntu 22.04 和 OpenCV 4。代码按设备能力
枚举 profile，不按产品名分支，因此可用于 R200，并为后续 SR300、D400 等
RealSense 设备保留同一入口。

> 这仍是计算机视觉估算，不替代高速相机、光电二极管或示波器等专用延迟测试。

## 极简 Python 入口（RealSense / Berxel P100R）

`python_latency_test.py` 提供一个不依赖本项目 C++ 构建的快速测试入口。它支持
安装了 `pyrealsense2` 的 R200、SR300、D435i 等设备，也支持 P100R 随官方 Python
SDK 提供的 `BerxelSdkDriver`。程序让相机回拍全屏黑白圆点，输出视觉链路的
median、mean 和 p95 延迟；该值包含显示器、相机、USB/驱动和应用取帧延迟。

```bash
# RealSense
python3 python_latency_test.py --backend rs --samples 100

# P100R；默认从相邻目录 ../Python 查找 BerxelSdkDriver
python3 python_latency_test.py --backend berxel --samples 100
```

Windows、Ubuntu 和 ARM Linux 均使用同一 Python 文件。P100R SDK 的动态库仍需按
官方 SDK 的平台目录准备；`--berxel-root` 可显式指定包含 `BerxelSdkDriver` 的目录。

## 已实现

- 列出所有已连接设备及可用于屏幕测试的 color/infrared profile；
- 使用序列号或设备索引选择相机，避免“永远取第一个设备”；
- 默认低延迟策略：优先 color、最高 FPS、接近 640×480、原生 YUYV；
- 可显式选择分辨率、FPS、格式和 quality 策略；
- 默认同时请求 640×480@90 Z16 depth（不可用时能力降级），并分别统计视觉流和
  depth 实际 FPS；`--no-depth` 提供严格单流对照；
- 直接使用 `sensor.start(callback)`，应用侧只保留最新一帧；
- 检测线程与采集 callback 分离，慢检测不会把旧帧排成长队；
- `--rotate 180` 或运行时 `R` 键旋转采集画面、预览和识别；
- 全帧寻找横向跨度最大的一排圆点，不再限定画面上四分之一；
- 低于 VGA 的检测工作图等比归一到 VGA，预览保持原始宽高比并 letterbox；
- Ubuntu 22.04 GNOME Wayland 下默认使用普通置顶窗口，只用 Q/Esc 退出；
- CSV 保存每个有效视觉延迟样本、frame number、frame timestamp 和 domain。

## 构建

依赖：CMake、C++17、OpenCV 4，以及带目标
`realsense2::realsense2` 的 librealsense2 CMake package。

系统安装 librealsense2 时：

```bash
scripts/build.sh
```

使用自定义安装前缀时：

```bash
export RS2_PREFIX=/path/to/rs2_install
scripts/build.sh
```

Windows（Developer PowerShell）使用同一 CMake 工程，不依赖 Bash 脚本：

```powershell
cmake -S . -B build -Drealsense2_DIR=C:\path\to\librealsense\lib\cmake\realsense2
cmake --build build --config Release
.\build\Release\rs2-latency-lab.exe --list
```

## 运行

先确认设备和真实可用 profile：

```bash
scripts/run.sh --list
```

默认低延迟模式会选指定设备的 color 最高帧率 VGA 附近 profile，并优先同时请求
Depth 640×480@90。profile 写着 90 不代表实际 callback 一定达到 90，最终以
`depth_fps` 为准：

```bash
scripts/run.sh --csv results/run.csv
```

相机因走线倒装时：

```bash
scripts/run.sh --rotate 180 --csv results/run-rotated.csv
```

多台设备同时连接时按序列号选择其中一台：

```bash
scripts/run.sh --serial DEVICE_SERIAL --csv results/device-a.csv
```

显式 profile 对比：

```bash
# 高帧率 VGA
scripts/run.sh --stream color --width 640 --height 480 --fps 60 \
  --format yuyv --no-depth --csv results/color-640x480-60.csv

# 高分辨率 1080p
scripts/run.sh --stream color --width 1920 --height 1080 --fps 30 \
  --format yuyv --no-depth --csv results/color-1920x1080-30.csv

# 自动选择最高分辨率 profile
scripts/run.sh --policy quality --csv results/color-quality.csv

# 同时开启 640x480@60 depth，测试组合负载
scripts/run.sh --width 640 --height 480 --fps 60 --format yuyv \
  --with-depth --depth-width 640 --depth-height 480 --depth-fps 60 \
  --csv results/color-depth-60.csv
```

窗口运行时：`F` 切换全屏，`R` 切换 0°/180°，`Q` 或 Esc 退出。把镜头对准
整排圆点；底部 `circles` 应大于 1，成功解码后 `samples` 会持续增长。

## SR300 使用原则

先运行 `--list`，再优先使用 color stream。Intel 官方原始样例明确指出 SR300
红外流通常无法可靠拍到显示器内容，因此本项目不会因为设备名是 SR300 就默认
选择 IR。SR300 的 global timestamp 也不在官方支持范围内；详细约束见
[时间戳与同步说明](docs/TIMESTAMPS_AND_SYNC.md)。

## 测量口径

- `visual_latency_ms`：圆点时钟显示到该图案进入应用 callback 的估算延迟，已
  减去本程序平均渲染调用时间；这是主要比较指标。
- `arrival_to_callback_ms`：仅在设备/后端提供
  `RS2_FRAME_METADATA_TIME_OF_ARRIVAL` 时记录；不等于曝光到主机的完整延迟。
- `frame_timestamp_ms` 和 `timestamp_domain`：原样保存，绝不跨时钟域直接相减。
- `capture_fps`：callback 实际到达速率，用于判断高 FPS profile 是否真的生效。
- 终端最终 `SUMMARY median_ms`、CSV 汇总中位数和平均值均覆盖整个测量阶段；窗口
  中的 median 为便于实时观察而采用最近 31 个样本的滚动值。

FPS 提高通常会缩短等待下一帧的采样周期，但不保证总延迟必然下降。曝光时间、
USB 带宽、格式转换、驱动队列、检测计算和显示刷新都可能抵消收益。建议按
[实验矩阵](docs/EXPERIMENT_PLAN.md)重复测试，而不是只看枚举出的 FPS 数字。

完整的 10 组矩阵包含 4 个 RGB profile 的 depth 开关，以及 VGA60 RGB 搭配
VGA90/QVGA90 depth；默认每组重复 3 次、每次 60 秒：

```bash
REPEATS=3 WARMUP=10 DURATION=60 ROTATE=180 scripts/run-matrix.sh
```

只补测指定轮次时，用逗号分隔精确 label（不会删除目录内其他结果）：

```bash
ONLY=rgb-qvga-60,rgb-qvga-60-depth REPEATS=1 \
  RESULT_DIR=results/RUN_DIR ROTATE=180 scripts/run-matrix.sh
```

保持相机和屏幕位置不变。脚本为每轮保存 CSV 与控制台日志，并自动生成
`summary.md`/`summary.csv`。任何一轮没有有效圆点样本时，汇总仍会写盘，但矩阵
脚本返回非零状态并要求重新对准/补测，避免把只有 callback FPS 的轮次当作有效
视觉延迟实验。也可随时重新汇总已有目录：

```bash
python3 scripts/summarize.py results/RUN_DIR \
  --markdown results/RUN_DIR/summary.md \
  --csv results/RUN_DIR/summary.csv
```

## 文档入口

- [架构与数据路径](docs/ARCHITECTURE.md)
- [时间戳、同步与 VSLAM 注意事项](docs/TIMESTAMPS_AND_SYNC.md)
- [FPS/分辨率延迟实验计划](docs/EXPERIMENT_PLAN.md)
- [设备兼容状态](docs/DEVICE_COMPATIBILITY.md)
- [R200 初步真机结果](docs/R200_INITIAL_RESULTS.md)
- [R200 十项矩阵（2026-08-22/23）](docs/R200_MATRIX_20260822.md)
- [后续 AI/维护者交接](docs/HANDOFF.md)
- [官方资料索引](docs/REFERENCES.md)

## 许可证与来源

Apache-2.0。视觉时钟和圆点解码方法派生自 Intel RealSense 官方
`rs-latency-tool`；参见 `NOTICE`。本项目是社区工具，不代表 Intel 或
RealSense 官方验证结果。
