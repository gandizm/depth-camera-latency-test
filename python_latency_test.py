#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Encoding/detection ported from src/main.cpp and src/latency_detector.cpp.
# Derived from Intel rs-latency-tool, Copyright(c) 2017 Intel Corporation.
"""The existing C++ circle test with a Berxel Python SDK capture adapter."""
import argparse
import csv
import json
import math
from pathlib import Path
import random
import signal
import sys
import threading
import time

import cv2
import numpy as np

from latency_capture import CameraSource

DIGITS = 16
MODULUS = 1 << (DIGITS - 2)
WINDOW = "Depth camera latency - Intel circle test"
CSV_FIELDS = ["sample", "frame_number", "device_timestamp_us", "timestamp_domain",
              "host_callback_ns", "pattern_value", "raw_visual_latency_ms",
              "render_ms", "panel_ms", "visual_latency_ms", "display_hz", "display_period_ms"]


def refresh_budget(hz):
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError("display-hz must be a finite positive refresh rate")
    period = 1000.0 / hz
    return dict(configured_hz=hz, period_ms=period,
                ideal_uniform_phase_mean_ms=period/2,
                ideal_uniform_phase_std_ms=period/math.sqrt(12),
                note="Ideal single-refresh phase only, not a measured error bound. "
                     "Compositor queue, scanout position, panel response and exposure add uncertainty. "
                     "This setting does not change or verify the OS refresh rate.")


def pack_value(value):
    bits = [False] * DIGITS
    for index in range(DIGITS - 1, 1, -1):
        bits[index] = bool(value & 1)
        value >>= 1
    count = sum(bits[2:])
    bits[0] = count % 2 == 1
    bits[1] = (count // 2) % 2 == 1
    return bits


def unpack_value(bits):
    count = sum(bits[2:])
    if (count % 2 == 1) != bits[0] or ((count // 2) % 2 == 1) != bits[1]:
        return None
    value = 0
    for bit in bits[2:]:
        value = value * 2 + int(bit)
    return value


def draw_pattern(display, value):
    # Exact geometry used in src/main.cpp (1280x720 by default).
    bits = pack_value(value)
    width = (display.shape[1] - 120) // (DIGITS + 2)
    radius = width // 2 - 6
    for index in range(DIGITS + 2):
        if index == 0 or index == DIGITS + 1 or bits[index - 1]:
            cv2.circle(display, (50 + width * index + radius, 70 + radius),
                       radius, (255, 255, 255), -1, cv2.LINE_AA)


def select_circle_row(circles, height):
    # Same full-frame row selection as the user's working C++ fork.
    selected, score = [], -1.0
    tolerance = max(20.0, height * 0.10)
    for anchor in circles:
        row = [c for c in circles if abs(float(c[1]) - float(anchor[1])) <= tolerance]
        if len(row) < 2:
            continue
        span = max(float(c[0]) for c in row) - min(float(c[0]) for c in row)
        candidate = len(row) * 10000.0 + span
        if candidate > score:
            selected, score = row, candidate
    return sorted(selected, key=lambda c: c[0])


def decode_row(row):
    # Zero bits are absent circles. Two anchors alone are valid encoded zero.
    if len(row) < 2:
        return None
    left, right = int(row[0][0]), int(row[-1][0])
    spacing = (right - left) // (DIGITS + 1)
    left += spacing // 2
    right -= spacing // 2
    if right <= left:
        return None
    bits = [False] * DIGITS
    for circle in row[1:-1]:
        bit = int(DIGITS * ((int(circle[0]) - left) / (right - left)))
        if 0 <= bit < DIGITS:
            bits[bit] = True
    return unpack_value(bits)


def detect(frame, rotate=False):
    if rotate:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    scale = max(1.0, 640.0 / gray.shape[1], 480.0 / gray.shape[0])
    if scale > 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
    detection = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(detection, cv2.HOUGH_GRADIENT, 1, 10,
                              param1=100, param2=30, minRadius=1, maxRadius=100)
    row = select_circle_row(circles[0], detection.shape[0]) if circles is not None else []
    annotated = frame.copy()
    for x, y, r in row:
        x, y, r = int(x), int(y), int(r)
        cv2.rectangle(annotated, (x-r-5, y-r-5), (x+r+5, y+r+5), (0, 255, 0), 2, cv2.LINE_AA)
    scale = min(600 / annotated.shape[1], 350 / annotated.shape[0])
    small = cv2.resize(annotated, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    preview = np.zeros((350, 600, 3), np.uint8)
    y, x = (350-small.shape[0])//2, (600-small.shape[1])//2
    preview[y:y+small.shape[0], x:x+small.shape[1]] = small
    return decode_row(row), len(row), preview


class Detector:
    def __init__(self, source, args):
        self.source, self.args = source, args
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.start_ns = time.perf_counter_ns()
        self.current, self.new_value = 0, True
        self.pattern_ns = self.start_ns
        self.render_sum, self.render_count = 0.0, 0
        self.preview = np.zeros((350, 600, 3), np.uint8)
        self.samples = []
        self.circles, self.frames, self.skipped = 0, 0, 0
        self.last_frame_ns = 0
        self.rotate = args.rotate == 180
        self.error = None
        self.first_frame_ns, self.first_sequence, self.last_sequence = 0, 0, 0
        self.last_number = None
        self.duplicates = 0
        self.update_after_ns = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.wait(0.001):
                packet = self.source.slot.take()
                if packet is None:
                    continue
                if packet["frame_number"] == self.last_number:
                    self.duplicates += 1
                    continue
                self.last_number = packet["frame_number"]
                decoded, circles, preview = detect(packet["image"], self.rotate)
                with self.lock:
                    self.frames += 1
                    self.skipped += packet["skipped"]
                    self.last_frame_ns = packet["arrival_ns"]
                    if not self.first_frame_ns:
                        self.first_frame_ns = packet["arrival_ns"]
                        self.first_sequence = packet["sequence"]
                    self.last_sequence = packet["sequence"]
                    self.preview, self.circles = preview, circles
                    # Preserve C++ update rules: keep valid older patterns in flight;
                    # request a new value after a match or failed decoding.
                    if self.new_value:
                        continue
                    if decoded == self.current:
                        age_ms = (packet["arrival_ns"] - self.pattern_ns) / 1e6
                        # Guard stale startup frames and clock-modulus wraparound.
                        if 0 <= age_ms < 2000:
                            callback = (packet["arrival_ns"] - self.start_ns) // 1_000_000
                            raw = (callback - decoded + MODULUS) % MODULUS
                            render = self.render_sum / max(1, self.render_count)
                            latency = raw - render - self.args.panel_ms
                            elapsed = (packet["arrival_ns"] - self.start_ns) / 1e9
                            if 0 <= latency < 2000 and elapsed >= self.args.warmup:
                                self.samples.append(dict(
                                    sample=len(self.samples)+1, frame_number=packet["frame_number"],
                                    device_timestamp_us=packet["device_timestamp_us"],
                                    timestamp_domain=packet["timestamp_domain"],
                                    host_callback_ns=packet["arrival_ns"], pattern_value=decoded,
                                    raw_visual_latency_ms=raw, render_ms=render,
                                    panel_ms=self.args.panel_ms, visual_latency_ms=latency,
                                    display_hz=self.args.display_hz, display_period_ms=1000/self.args.display_hz))
                        self.new_value = True
                    elif decoded is None:
                        self.new_value = True
        except Exception as exc:
            self.error = str(exc)

    def display(self, description):
        display = np.zeros((720, 1280, 3), np.uint8)
        now = time.perf_counter_ns()
        with self.lock:
            # Keep a changing test pattern visible while camera initialization is pending.
            expired = now-self.pattern_ns > (2_000_000_000 if self.frames else 250_000_000)
            if (self.new_value or expired) and self.update_after_ns is None:
                # Optional display-only dither avoids always sampling one camera/display phase.
                delay = random.random()*1e9/self.args.display_hz if self.args.phase_jitter else 0
                self.update_after_ns = now + int(delay)
            if self.update_after_ns is not None and now >= self.update_after_ns:
                value = int((now-self.start_ns)//1_000_000 % MODULUS)
                if value == self.current:
                    value = (value+1) % MODULUS
                self.current, self.pattern_ns, self.new_value = value, now, False
                self.update_after_ns = None
            value, preview = self.current, self.preview
            values = [s["visual_latency_ms"] for s in self.samples]
            count, circles, frames, skipped = len(values), self.circles, self.frames, self.skipped
        draw_pattern(display, value)
        display[200:550, 340:940] = preview
        if not frames:
            cv2.putText(display, "Waiting for P100R/RS frames...", (380, 380),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        text = [
            description[:112],
            "Display %.3g Hz: %.3f ms/refresh (setting only; not a measured panel delay)" %
            (self.args.display_hz, 1000/self.args.display_hz),
            "Aim at the whole row. Q/Esc or X closes; R rotates; F toggles fullscreen.",
            ("samples=%d  median=%.2f ms  p95=%.2f ms" %
             (count, np.median(values), np.percentile(values, 95))) if values else
            "samples=0  No valid latency yet - check the live camera preview.",
            "frames=%d  circles=%d  overwritten=%d  panel subtraction=%.2f ms" %
            (frames, circles, skipped, self.args.panel_ms),
        ]
        for i, line in enumerate(text):
            cv2.putText(display, line, (30, 567+i*32), cv2.FONT_HERSHEY_SIMPLEX,
                        0.60, (255, 255, 255), 1, cv2.LINE_AA)
        return display, count

    def close(self):
        self.stop.set()
        self.thread.join(2)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", choices=("p100r", "berxel", "rs"), default="p100r")
    p.add_argument("--berxel-root", default=str(Path(__file__).resolve().parent.parent / "Python"))
    p.add_argument("--serial")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=int, help="select an enumerated camera frame rate; no forced unsupported rate")
    p.add_argument("--stream-mode", choices=("default", "single"), default="single",
                   help="Berxel SDK default versus documented single-stream mode")
    p.add_argument("--samples", type=int, default=100)
    p.add_argument("--duration", type=float, default=60, help="maximum run time, seconds (default 60)")
    p.add_argument("--warmup", type=float, default=3)
    p.add_argument("--panel-ms", type=float, default=0.0, help="explicit measured/assumed display correction")
    p.add_argument("--display-hz", type=float, default=165,
                   help="display refresh rate: 60/120/165/240 or any positive value; does not change OS settings")
    p.add_argument("--phase-jitter", action="store_true",
                   help="optionally dither pattern updates by 0..1 refresh to sample different phases")
    p.add_argument("--rotate", type=int, choices=(0, 180), default=0)
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--windowed", action="store_true", help="default; overrides --fullscreen")
    p.add_argument("--csv", default="results/p100r-python-latest.csv")
    p.add_argument("--probe", action="store_true", help="verify one SDK frame, no GUI")
    p.add_argument("--snapshot", help="save a camera frame during --probe for alignment diagnostics")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    budget = refresh_budget(args.display_hz)
    if args.duration <= 0 or args.samples <= 0 or args.panel_ms < 0 or args.warmup < 0:
        raise ValueError("duration/samples must be positive; panel-ms/warmup must be nonnegative")
    if args.backend == "berxel":
        args.backend = "p100r"
    # Validate the output location before taking ownership of any camera.
    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    source, detector = None, None
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    status, result = "Opening " + args.backend + " SDK...", 0
    created = False
    cv2.setNumThreads(1)
    started = time.perf_counter()
    last_report = started
    if sys.platform == 'win32':
        import ctypes
        # Do not inherit the launching editor's taskbar/window identity.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('gandizm.DepthCameraLatencyTest')
    print(status, flush=True)
    print("DISPLAY %.3g Hz: period=%.3f ms; nominal uniform-phase mean=%.3f ms. "
          "Not auto-subtracted; panel correction=%.3f ms; phase-jitter=%s" %
          (args.display_hz, budget["period_ms"], budget["ideal_uniform_phase_mean_ms"],
           args.panel_ms, args.phase_jitter), flush=True)
    try:
        source = CameraSource(args)
        if not args.probe:
            detector = Detector(source, args)
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            created = True
            cv2.resizeWindow(WINDOW, 1280, 720)
            try:
                cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
            except cv2.error:
                pass
            fullscreen = args.fullscreen and not args.windowed
            if fullscreen:
                cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        while not stop.is_set():
            for kind, message in source.status():
                print(kind.upper() + ": " + message, flush=True)
                if kind == "error":
                    raise RuntimeError(message)
                if kind == "info":
                    status = message
            if not source.process.is_alive():
                raise RuntimeError("Capture worker exited (code %s)" % source.process.exitcode)
            if args.probe:
                packet = source.slot.take()
                if packet:
                    if args.snapshot:
                        if not cv2.imwrite(args.snapshot, packet["image"]):
                            raise RuntimeError("Could not save camera snapshot")
                    print("FRAME_OK %s #%s %s us domain=%s" %
                          (packet["image"].shape, packet["frame_number"],
                           packet["device_timestamp_us"], packet["timestamp_domain"]), flush=True)
                    break
                time.sleep(0.01)
            else:
                # X must be checked BEFORE imshow, which would recreate a closed window.
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    print("EXIT: window closed", flush=True)
                    break
                render_start = time.perf_counter()
                display, count = detector.display(status)
                cv2.imshow(WINDOW, display)
                key = cv2.waitKey(1) & 0xff  # exactly one key read per refresh
                with detector.lock:
                    detector.render_sum += (time.perf_counter()-render_start)*1000
                    detector.render_count += 1
                if key in (ord("q"), ord("Q"), 27):
                    print("EXIT: Q/Esc", flush=True)
                    break
                if key in (ord("r"), ord("R")):
                    detector.rotate = not detector.rotate
                if key in (ord("f"), ord("F")):
                    fullscreen = not fullscreen
                    cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN,
                                          cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                if detector.error:
                    raise RuntimeError(detector.error)
                if count >= args.samples:
                    break
            now = time.perf_counter()
            if now-started >= args.duration:
                print("EXIT: duration limit", flush=True)
                if args.probe:
                    raise RuntimeError("Probe timed out without a frame")
                break
            if now-started > 15 and source.slot.meta[0] == 0:
                raise RuntimeError("No SDK frame within 15 seconds")
            if detector and now-last_report > 2:
                print("frames=%d circles=%d samples=%d" %
                      (detector.frames, detector.circles, len(detector.samples)), flush=True)
                last_report = now
    except Exception as exc:
        print("ERROR: " + str(exc), file=sys.stderr, flush=True)
        result = 1
    finally:
        if created:
            cv2.destroyAllWindows()
        if detector:
            detector.close()
        if source:
            source.close()
        if detector:
            with out.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, CSV_FIELDS)
                writer.writeheader()
                writer.writerows(detector.samples)
            values = [s["visual_latency_ms"] for s in detector.samples]
            dt = (detector.last_frame_ns-detector.first_frame_ns)/1e9
            fps = (detector.last_sequence-detector.first_sequence)/dt if dt > 0 else 0
            summary = dict(valid_measurement=bool(values), backend=args.backend,
                           stream_mode=args.stream_mode,
                           source=status, display=budget, panel_correction_ms=args.panel_ms,
                           phase_jitter=args.phase_jitter, capture_fps=fps,
                           decoded_samples=len(values), processed_frames=detector.frames,
                           overwritten=detector.skipped, duplicate_frames=detector.duplicates,
                           warmup_seconds=args.warmup,
                           measurement="Visual screen-to-SDK-callback latency; RGB only. "
                           "Original estimator = raw interval - mean rendering call time - panel-ms. "
                           "Rendering call time is not physical display latency. "
                           "No inference about depth exposure timing or hardware synchronization.")
            if values:
                summary["latency_ms"] = dict(median=float(np.median(values)),
                    mean=float(np.mean(values)), std=float(np.std(values)),
                    p5=float(np.percentile(values, 5)), p95=float(np.percentile(values, 95)))
                print("RESULT count=%d median=%.3f mean=%.3f p95=%.3f ms; CSV=%s" %
                      (len(values), np.median(values), np.mean(values), np.percentile(values, 95), out),
                      flush=True)
            else:
                print("NO_MEASUREMENT: no decoded samples; CSV contains header only.", flush=True)
            out.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Camera worker stopped; test exited.", flush=True)
    return result


if __name__ == "__main__":
    sys.exit(main())
