# Depth Camera Latency Test

一个基于 Intel RealSense 官方 `rs-latency-tool` 的设备无关视觉延迟 Demo。
它让摄像头回拍屏幕上的二进制圆点时钟，从而估算“屏幕事件发生 → 帧到达应用”
的端到端视觉延迟，同时记录应用收到帧时可用的时间戳域和
`TIME_OF_ARRIVAL` 到 callback 的主机侧延迟。

当前基线是 librealsense 2.51.1、Ubuntu 22.04 和 OpenCV 4。代码按设备能力
枚举 profile，不按产品名分支，因此可用于 R200，并为后续 SR300、D400 等
RealSense 设备保留同一入口。

> 这仍是计算机视觉估算，不替代高速相机、光电二极管或示波器等专用延迟测试。

## 极简 Python 入口（RealSense / Berxel P100R）

`python_latency_test.py` 从本仓库已经验证的 C++ 版本移植编码和识别，不改动
`src/`：16 个编码位置（含两个校验位）、两侧定位圆、全帧 Hough 行选择、
半个间距修正后的位映射，以及原来的延迟计算。位为 0 时不画圆，不能要求
18 个圆同时出现。默认 1280×720 普通窗口，包含彩色预览、绿色检测框和统计。

P100R 使用官方 `Python/BerxelSdkDriver` 的 `startStreams(..., callback)`，
RealSense 使用 `sensor.start(callback)`；回调入口先记录主机单调时间，再复制
帧到容量为 1 的最新帧槽。原生 SDK 在独立采集进程内，Hough 在检测线程内，
GUI 不等待取帧。Q/Esc、窗口 X 和限时退出都会释放相机；SDK 退出阻塞时只
终止当前采集子进程。程序默认 100 个样本、3 秒预热、最多 60 秒。

```bash
python -m pip install -r requirements-latency.txt
```

```bash
# RealSense
python3 python_latency_test.py --backend rs --samples 100

# P100R；SDK 默认从脚本位置的相邻目录 ../Python 查找
python3 python_latency_test.py --backend p100r --display-hz 165 --rotate 180

# 显式使用本机实测较低延迟的档位
python3 python_latency_test.py --backend p100r --stream-mode single --width 640 --height 400 --fps 30 --display-hz 165 --rotate 180

# 不开窗口，检查官方 SDK 能否返回一帧
python3 python_latency_test.py --backend p100r --probe
```

Windows 可双击 `run_p100r.cmd`，或使用 `run_p100r.cmd --display-hz 240`。
SDK 不随仓库分发；`--berxel-root` 指向包含 `BerxelSdkDriver` 的目录。相机型号、
平台、架构必须与官方 DLL/SO 匹配。Windows x64 + P100R 已实机验证；Ubuntu/ARM
仍需要相应官方库，当前没有完成这些平台的真机验证。SR300/D435i 的 Python
适配按枚举能力选择 profile，本次没有在这些型号上验证。

输出默认保存到 `results/p100r-python-latest.csv` 及同名 JSON，可用 `--csv` 指定
路径。CSV 分别保存原始视觉间隔、平均渲染调用耗时、手动面板修正、最终估计
值和设备时间戳域；JSON 保存帧率、样本数、标准差、分位数、覆盖帧数和设置。
这里测的是彩色屏幕事件到 SDK 回调，不能作为深度流曝光或 ROS/DDS 延迟。

### 显示刷新率与误差

`--display-hz` 接受 60、120、165、240 或任意正数（例如 360）。它记录当前
显示器设置并计算刷新周期，不修改也不自动确认操作系统实际刷新率。

| 显示刷新率 | 一个刷新周期 | 理想随机相位等待均值 |
| --- | --- | --- |
| 60 Hz | 16.667 ms | 8.333 ms |
| 120 Hz | 8.333 ms | 4.167 ms |
| 165 Hz | 6.061 ms | 3.030 ms |
| 240 Hz | 4.167 ms | 2.083 ms |

上表只是单次刷新、均匀随机相位的模型；合成器排队、扫描位置、面板响应、
滚动快门和曝光还有额外误差。不能自动把一帧周期或半帧周期当作物理面板延迟
扣掉。`--panel-ms` 默认为 0，只在明确填写时扣除，并在结果中保留该值。
原算法减去的 `render_ms` 是绘制/`imshow`/`waitKey` 的软件耗时，也不是实测
面板延迟，所以同时保留未修正的 `raw_visual_latency_ms`。

`--phase-jitter` 可在下一次图案更新前加入 0～1 个刷新周期的随机等待，采样
更多相机/显示相位；它不改变识别逻辑，也不创建硬件同步。默认关闭以保留原
更新节奏。已添加重复帧过滤、旧图案超时重发和 16.384 秒时钟回绕保护。

### 2026-10-11 P100R 实测

本机 Windows x64，官方 Python SDK 2.0.182，FW 25.9.1105-a6.14.08.05，
用户报告屏幕设置为 165 Hz；手动面板修正 0 ms。以下均为原算法视觉估计，
不是曝光到主机的绝对延迟，也不是经过多轮稳定条件复测的规格。

| 配置 | 样本数 | 中位数 | P95 | 标准差 |
| --- | --- | --- | --- | --- |
| SDK 默认流模式，640×400@30 | 100 | 99.29 ms | 112.48 ms | 7.65 ms |
| 同配置，显示更新随机错相 | 143 | 99.41 ms | 130.14 ms | 14.47 ms |
| SDK 默认流模式，关闭按钮验证轮 | 128 | 97.54 ms | 119.37 ms | 10.29 ms |
| 单流，1920×1080@30 | 67 | 117.91 ms | 163.11 ms | 27.36 ms |
| 单流，640×400@30 | 100 | 77.97 ms | 102.21 ms | 12.39 ms |

这轮单流低分辨率比默认模式低约 21 ms；不能由此推断 SDK 恰好少缓存一帧。
切换到单流时 SDK 会默认改用 1080p，因此程序保留切换前的 profile，或者使用
显式 `--width/--height/--fps` 请求。当前相机枚举的彩色档位最高为 30 fps，
没有强行设置 60/90 fps。Python 接口未发现可公开配置的帧队列长度。

单流 VGA 原始间隔中位数为 83.0 ms，软件渲染耗时约 4.9 ms；最终估计的
P5/P95 为 66.05/102.21 ms，最小 63.09 ms、最大 131.89 ms。固定减去
77.97 ms 后，90% 样本残差仍约为 -12～+24 ms。首半/后半样本中位数为
82.82/75.04 ms，因此这次短测不能提供稳定的精确同步偏移或证明 40 ms 以下。

验证：全部 16384 个编码位映射、合成图像 Hough 解码、校验错误拒绝、
最新帧槽、时钟回绕和采集进程关闭测试；P100R 实际取帧/采样，限时退出和
真实窗口 X 退出通过。C++ 构建检查受当前环境缺少 librealsense2 开发包限制；
原 C++ 源文件保持未改动。

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
