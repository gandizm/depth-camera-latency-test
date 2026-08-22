# R200 初步真机结果（2026-08-22）

环境：Ubuntu 22.04 GNOME Wayland、librealsense 2.51.1 社区 R200 分支、
OpenCV 4.5.4、R200 官方固件 1.0.72.10。设备序列号不写入仓库。

这些是功能验收和量级检查，不是最终 profile 结论；正式结论仍需按实验矩阵每组
至少 60 秒、重复 3 次，并固定显示器刷新率、曝光和相机几何位置。

后续首轮十项有效数据见 [R200_MATRIX_20260822.md](R200_MATRIX_20260822.md)。

## Color 640×480@60 YUYV，depth 关闭（首次功能验收）

运行 60 秒、采集画面旋转 180°：

| 指标 | 结果 |
| --- | ---: |
| callback 实际 FPS | 60.15 |
| 有效视觉样本 | 27 |
| visual median | 73.41ms |
| visual p95 | 90.36ms |
| visual average | 74.51ms |
| arrival→callback median | 1.93ms |
| timestamp domain | System Time |
| latest-slot overwritten frames | 1183 |

该结果证明圆点编码、180°旋转、全帧圆点排选择、timestamp/domain 和 CSV 路径
可用。`overwritten_frames` 是检测线程主动丢弃旧帧，不是 USB callback 丢帧；
callback FPS 仍达到请求值。

## 同条件 depth off/on 对照（5 秒预热 + 60 秒测量）

2026-08-22 保持 640×480@60 YUYV 和 180° 旋转，按相同预热/测量时长分别测试。
以下延迟来自 CSV 的全程样本；不是预览窗口的滚动 31 样本统计。

| 指标 | Depth 关闭 | Depth 640×480@60 Z16 开启 |
| --- | ---: | ---: |
| Color callback 实际 FPS | 59.88 | 60.61 |
| Depth callback 实际 FPS | — | 60.61 |
| 有效视觉样本 | 131 | 11 |
| visual median | 80.26ms | 83.01ms |
| visual p95 | 99.22ms | 93.02ms |
| visual average | 78.69ms | 81.29ms |
| arrival→callback median | 1.76ms | 1.69ms |
| timestamp domain | System Time | System Time |
| latest-slot overwritten frames | 1168 | 1118 |

两组中位数相差约 2.75ms，但 depth-on 仅有 11 个有效视觉样本，样本量严重不对等，
且圆点识别采样并非每帧一次。因此这只能证明程序能够读取和汇总 depth on/off 结果，
不能据此宣称开启 depth 增加或减少了多少延迟。正式比较须运行完整矩阵、每组至少
重复 3 次，并重跑任何有效样本过少的轮次。

在加入预热功能前还做过一轮组合流冒烟测试：color 60.01fps、depth 60.01fps，
但当时镜头未形成有效圆点解码（`samples=0`），因此不进入延迟比较。

## 8 组矩阵快速链路验收

使用 2 秒预热、10 秒测量、每组 1 次验证批处理，不作为延迟结论。相机当时未
持续拍全圆点排，8 组均为 `samples=0`；因此这里只记录 callback 吞吐，并证明
汇总器会把延迟列标为 `n/a`：

| RGB profile | Depth 关闭 | Depth 开启（RGB / Depth） |
| --- | ---: | ---: |
| 640×480@30 | 30.08fps | 30.01 / 30.01fps |
| 640×480@60 | 59.95fps | 60.04 / 60.01fps |
| 320×240@60 | 59.99fps | 60.72 / 60.68fps |
| 1920×1080@30 | 24.14fps | 16.98 / 30.23fps |

VGA/QVGA 档达到请求帧率；1080p 档在这轮短测中未达到 30fps，叠加 depth 后
下降更明显。这是后续正式长测需要重点复核的信号，不足以单独归因于 USB、SDK、
CPU 或自动曝光。矩阵脚本现会在任一轮 `samples=0` 时生成汇总后返回失败。

## Ubuntu 窗口问题

Intel 官方样例的窗口曾被确认映射到 XWayland，但 GNOME 没有自动激活它，且
官方逻辑按任意键退出。本项目改为普通 1280×720 窗口、可选置顶、只用 Q/Esc
退出，并把 GTK3 返回 `WND_PROP_VISIBLE=-1` 视为“不支持”而不是“已关闭”。
