# 官方资料索引

- [librealsense rs-latency-tool](https://github.com/realsenseai/librealsense/tree/master/wrappers/opencv/latency-tool)：屏幕二进制时钟、Hough circle 与 checksum 方法；官方同时强调这只是估算框架。
- [Frame Buffering Management](https://github.com/realsenseai/librealsense/wiki/Frame-Buffering-Management-in-RealSense-SDK-2.0)：callback/queue 模型、latency 与丢帧权衡、低延迟 queue capacity 建议。
- [Frame Management](https://github.com/realsenseai/librealsense/blob/master/doc/frame_lifetime.md)：callback 线程、frame lifetime、处理超时和 syncer 限制。
- [SDK Supported Features Matrix](https://dev.realsenseai.com/docs/sdk-supported-features-matrix/)：包含 SR300 不支持 Global Timestamp 的官方矩阵。
- [Intel multi-camera white paper](https://www.intel.com/content/dam/support/us/en/documents/emerging-technologies/intel-realsense-technology/RealSense_Multiple_Camera_WhitePaper.pdf)：多设备硬件同步、时钟偏移/漂移与 frame timestamp 背景。
- [Multiple depth cameras configuration](https://dev.realsenseai.com/docs/multiple-depth-cameras-configuration%C2%A0)：D400 多机硬件同步的官方说明；不能据此假设 R200/SR300 具备相同能力。

引用资料用于定义测量边界，不代表其中针对 D400 的硬件能力适用于 R200 或
SR300。每台设备仍以实际 `supports()`、metadata 和真机结果为准。
