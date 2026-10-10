#!/usr/bin/env python3
"""Intel rs-latency-tool style visual latency test.

The display protocol and detector follow the original Intel sample: two anchor
circles, a 16-circle encoded row, two parity bits, Hough circle detection, and
latest-frame latency accounting. Only the frame source is selectable.
"""
import argparse
import importlib
import os
import statistics
import sys
import threading
import time

import cv2
import numpy as np


DIGITS = 16
MODULUS = 1 << (DIGITS - 2)


def pack_value(value):
    bits = [False] * DIGITS
    for index in range(DIGITS - 1, 1, -1):
        bits[index] = bool(value & 1)
        value >>= 1
    on_bits = sum(bits[2:])
    bits[0] = (on_bits % 2) == 1
    bits[1] = ((on_bits // 2) % 2) == 1
    return bits


def unpack_value(bits):
    on_bits = sum(bits[2:])
    if ((on_bits % 2) == 1) != bits[0]:
        return None
    if (((on_bits // 2) % 2) == 1) != bits[1]:
        return None
    value = 0
    for bit in bits[2:]:
        value = value * 2 + int(bit)
    return value


def select_circle_row(circles, height):
    selected = []
    best_score = -1.0
    tolerance = max(20.0, height * 0.10)
    for anchor in circles:
        row = [candidate for candidate in circles
               if abs(float(candidate[1]) - float(anchor[1])) <= tolerance]
        if len(row) < 2:
            continue
        span = max(float(c[0]) for c in row) - min(float(c[0]) for c in row)
        score = len(row) * 10000.0 + span
        if score > best_score:
            best_score = score
            selected = row
    return sorted(selected, key=lambda c: c[0])


def decode_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detection = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(
        detection, cv2.HOUGH_GRADIENT, 1, 10,
        param1=100, param2=30, minRadius=1, maxRadius=100)
    if circles is None:
        return None, 0
    row = select_circle_row(circles[0], detection.shape[0])
    if len(row) < DIGITS + 2:
        return None, len(row)
    left = float(row[0][0])
    right = float(row[-1][0])
    if right <= left:
        return None, len(row)
    bits = [False] * DIGITS
    for circle in row[1:-1]:
        bit = int(DIGITS * (float(circle[0]) - left) / (right - left))
        if 0 <= bit < DIGITS:
            bits[bit] = True
    return unpack_value(bits), len(row)


def rs_frames():
    rs = importlib.import_module("pyrealsense2")
    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color)
    pipeline.start(config)
    try:
        while True:
            frameset = pipeline.wait_for_frames()
            frame = frameset.get_color_frame()
            if frame:
                yield np.asanyarray(frame.get_data()).copy(), time.perf_counter(), frame.get_timestamp()
    finally:
        pipeline.stop()


def p100r_frames(root):
    root = os.path.abspath(root)
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "BerxelSdkDriver"))
    from BerxelHawkContext import BerxelHawkContext
    from BerxelHawkDefines import BerxelHawkStreamType

    context = BerxelHawkContext()
    context.initCamera()
    devices = context.getDeviceList()
    if not devices:
        raise RuntimeError("No Berxel device found")
    device = context.openDevice(devices[0])
    if device is None:
        raise RuntimeError("Could not open Berxel device")
    color = BerxelHawkStreamType.forward_dict["BERXEL_HAWK_COLOR_STREAM"]
    if device.startStreams(color) != 0:
        context.closeDevice(device)
        context.destroyCamera()


class LatestFrameSource:
    """Keep capture off the GUI loop, matching the original latest-frame path."""

    def __init__(self, source):
        self.source = source
        self.latest = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            for item in self.source:
                if self.stop_event.is_set():
                    break
                with self.lock:
                    self.latest = item
        except Exception as error:
            with self.lock:
                self.latest = error

    def take(self):
        with self.lock:
            item, self.latest = self.latest, None
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=1.0)
        try:
            self.source.close()
        except Exception:
            pass
        raise RuntimeError("Could not start Berxel color stream")
    try:
        while True:
            frame = device.readColorFrame(100)
            if frame is None:
                continue
            width, height = frame.getWidth(), frame.getHeight()
            data = np.ctypeslib.as_array(frame.getDataAsUint8())
            image = data.reshape((height, width, 3)).copy()
            yield image, time.perf_counter(), frame.getTimeStamp()
            device.releaseFrame(frame)
    finally:
        device.stopStream(color)
        context.closeDevice(device)
        context.destroyCamera()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rs", "p100r"), required=True)
    parser.add_argument("--berxel-root", default=os.path.join("..", "Python"))
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--screen-width", type=int, default=1920)
    parser.add_argument("--screen-height", type=int, default=1080)
    parser.add_argument("--panel-ms", type=float, default=0.0)
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()

    source = LatestFrameSource(
        rs_frames() if args.backend == "rs" else p100r_frames(args.berxel_root))
    window = "Intel RS2 latency pattern"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    if not args.windowed:
        cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    source.start()

    start = time.perf_counter()
    current = max(1, int((time.perf_counter() - start) * 1000) % MODULUS)
    samples = []
    pending_new_value = False
    print("WINDOW_READY: Intel circle pattern is visible")
    print("Aim the selected camera at the complete circle row. Press Q or Esc to stop.")

    try:
        while len(samples) < args.samples:
            if pending_new_value:
                current = max(1, int((time.perf_counter() - start) * 1000) % MODULUS)
                pending_new_value = False

            display = np.zeros((args.screen_height, args.screen_width, 3), np.uint8)
            bits = pack_value(current)
            circle_width = (args.screen_width - 120) // (DIGITS + 2)
            radius = circle_width // 2 - 6
            for index in range(DIGITS + 2):
                if index == 0 or index == DIGITS + 1 or bits[index - 1]:
                    center = (50 + circle_width * index + radius, 70 + radius)
                    cv2.circle(display, center, radius, (255, 255, 255), -1, cv2.LINE_AA)

            render_start = time.perf_counter()
            cv2.imshow(window, display)
            cv2.waitKey(1)
            render_ms = (time.perf_counter() - render_start) * 1000.0

            packet = source.take()
            if packet is None:
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    break
                continue
            frame, arrival, _ = packet
            decoded, circle_count = decode_frame(frame)
            if decoded == current:
                callback_clock = int((arrival - start) * 1000) % MODULUS
                latency = (callback_clock - decoded + MODULUS) % MODULUS
                latency -= render_ms + args.panel_ms
                if 0.0 <= latency < 2000.0:
                    samples.append(latency)
                    print("%3d %.3f ms circles=%d" % (len(samples), latency, circle_count))
                pending_new_value = True

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
    finally:
        cv2.destroyAllWindows()
        source.close()

    if samples:
        print("count=%d median=%.3f mean=%.3f p95=%.3f ms" % (
            len(samples), statistics.median(samples), statistics.mean(samples),
            np.percentile(samples, 95)))
    else:
        print("No decoded samples")


if __name__ == "__main__":
    main()
