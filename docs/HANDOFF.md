# 维护与 AI 交接

## 项目目的

用同一可执行文件比较 RealSense 不同设备和 profile 的屏幕回拍视觉延迟，为
后续 R200/SR300 + 外置陀螺仪 VSLAM 选择采集参数。当前阶段不实现 VSLAM，也
不修改 ROS API。

## 当前实现状态

- 基于 librealsense 2.51.1 和 Intel 官方 `rs-latency-tool` 算法；
- R200 自动枚举、640×480@60 YUYV 拉流、Ubuntu Wayland 窗口已验证；
- 180° 旋转、全帧圆点排选择、CSV 输出已实现；
- `--with-depth` 组合负载、8 组 × 多轮矩阵脚本和 CSV 汇总器已实现；
- SR300 硬件、完整 R200 延迟样本矩阵和跨传感器同步尚未验收；
- GitHub CLI 的既有登录在创建本仓库时已失效，公开远端需要重新登录后创建。

## 接手顺序

1. 阅读 `AGENTS.md`、本文件、`TIMESTAMPS_AND_SYNC.md`；
2. 设置 `RS2_PREFIX` 并运行 `scripts/build.sh`；
3. `scripts/run.sh --list` 保存设备/profile 清单；
4. 让相机对准整排圆点，先用默认窗口确认 `circles` 与 `samples` 增长；
5. 按 `EXPERIMENT_PLAN.md` 跑 R200 四组 profile；
6. SR300 接入后先验证 color，记录 timestamp domain，再跑相同矩阵；
7. 只有上述基线固定后，才增加 depth/gyro/ROS/VSLAM 负载。

## 已知边界

- 圆点法包含显示器扫描/刷新和相机拍屏几何误差，不是实验室仪器；
- GUI 渲染时间只是 `imshow/waitKey` 主机调用耗时，不代表像素真正发光时刻；
- `TIME_OF_ARRIVAL` metadata 不是所有设备都提供；缺失时 CSV 写 `-1`；
- 单进程只测一台设备的一个流；这是有意设计，不是多相机同步器；
- 旋转在检测线程执行，会增加少量 CPU，但不会阻塞采集 callback。

## 禁止事项

不要从本项目刷固件、USB reset、写未知 XU 控件或伪造硬件时间戳。设备恢复与
固件实验不属于延迟测量范围。
