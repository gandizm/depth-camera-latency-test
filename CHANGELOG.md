# Changelog

## 0.1.0 - 2026-08-22

- Derive a multi-device latency lab from Intel's official rs-latency-tool.
- Add device/serial/profile selection and capability listing.
- Add direct sensor callback capture and latest-frame capacity-one policy.
- Add Ubuntu Wayland-friendly window behavior and Q/Esc-only exit.
- Add 180-degree capture/preview/detection rotation.
- Add full-frame horizontal circle-row selection and CSV output.
- Normalize sub-VGA detector input to fix QVGA circle recognition.
- Add simultaneous depth-load mode, repeated experiment matrix and summarizer.
- Default to capability-aware 640x480@90 depth preference with `--no-depth` baselines.
- Show RGB frames in color with green detections and aspect-preserving letterbox.
- Record the first complete ten-case R200 matrix and the IR90 screen limitation.
- Document timestamp domains, SR300 constraints and the FPS/resolution matrix.
