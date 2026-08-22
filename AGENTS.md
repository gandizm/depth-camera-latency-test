# Agent handoff rules

Read `README.md`, `docs/ARCHITECTURE.md`, `docs/TIMESTAMPS_AND_SYNC.md`, and
`docs/EXPERIMENT_PLAN.md` before changing capture or measurement behavior.

Project invariants:

- Keep the executable device-model agnostic. Select by enumerated capability,
  serial, stream, format and profile; do not branch on R200/SR300 product names.
- Default to one camera at a time, one video stream, a sensor callback, and a
  latest-frame slot of capacity one. Any queue increase must be optional and
  justified with latency measurements.
- Never describe `frame.get_timestamp()` as exposure time without device and
  metadata evidence. Always record the timestamp domain.
- Visual latency, host arrival-to-callback time, inter-stream synchronization,
  and ROS/application latency are different metrics; do not merge them.
- Do not update firmware, reset USB devices, write vendor controls, or change
  system configuration from this repository.
- R200 is currently verified. SR300 compatibility is capability-based but must
  remain marked unverified until tested on hardware.
- Preserve Apache-2.0 attribution to Intel's original rs-latency-tool.

Minimum checks before committing:

```bash
scripts/build.sh
build/rs2-latency-lab --help
build/rs2-latency-lab --list
git diff --check
```

For GUI testing on Ubuntu 22.04 GNOME Wayland, confirm the actual XWayland
window exists and remains visible; a running process alone is not GUI evidence.
