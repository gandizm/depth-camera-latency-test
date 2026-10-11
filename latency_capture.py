"""Camera adapters. Native SDKs are isolated so closing the GUI always works."""
import ctypes
import multiprocessing as mp
import os
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np


class SharedFrame:
    """One overwriteable frame, timestamped at callback entry before copying."""

    def __init__(self, ctx):
        self.pixels = ctx.RawArray(ctypes.c_ubyte, 1920 * 1080 * 3)
        self.meta = ctx.RawArray(ctypes.c_int64, 7)
        self.domain = ctx.RawArray(ctypes.c_char, 64)
        self.lock = ctx.Lock()
        self.sequence = 0
        self.read_sequence = 0

    def publish(self, image, arrival_ns, number, timestamp_us, domain):
        self.sequence += 1
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError('Capture adapter must produce uint8 BGR')
        if image.size > len(self.pixels):
            raise ValueError('Select a profile no larger than 1920x1080')
        if not self.lock.acquire(False):
            return  # Never hold up a sensor callback waiting for detection.
        try:
            np.frombuffer(self.pixels, np.uint8)[:image.size] = image.reshape(-1)
            self.meta[:] = (self.sequence, image.shape[0], image.shape[1],
                            arrival_ns, number, round(timestamp_us), time.time_ns())
            self.domain.value = domain.encode('ascii', errors='replace')[:63]
        finally:
            self.lock.release()

    def take(self):
        if not self.lock.acquire(False):
            return None
        try:
            seq, h, w, arrival, number, timestamp, host_time = self.meta[:]
            if not seq or seq == self.read_sequence:
                return None
            missed = seq - self.read_sequence - 1
            self.read_sequence = seq
            image = np.frombuffer(self.pixels, np.uint8)[:h * w * 3].reshape(h, w, 3).copy()
            return dict(image=image, arrival_ns=arrival, frame_number=number,
                        device_timestamp_us=timestamp, timestamp_domain=self.domain.value.decode(),
                        host_time_ns=host_time, sequence=seq, skipped=missed)
        finally:
            self.lock.release()


def run_p100r(args, slot, stop, report):
    root = Path(args.berxel_root).resolve()
    driver = root / 'BerxelSdkDriver'
    if not (driver / 'BerxelHawkContext.py').is_file():
        raise RuntimeError('BerxelSdkDriver not found; use --berxel-root PATH: ' + str(root))
    sys.path[:0] = [str(driver), str(root)]  # Official wrapper's absolute imports.
    dll_directory = None
    if os.name == 'nt':
        dll_directory = os.add_dll_directory(str(driver / 'libs' / 'windows'))
    try:
        from BerxelHawkContext import BerxelHawkContext
        from BerxelHawkDefines import BerxelNewFrameCallback
        from BerxelHawkFrame import BerxelHawkFrame
    except Exception as exc:
        raise RuntimeError('Cannot load official Berxel SDK; check matching DLL/SO architecture: ' + str(exc)) from exc

    context = BerxelHawkContext()
    device = None
    context.initCamera()
    try:
        devices = context.getDeviceList()
        if args.serial:
            devices = [d for d in devices if d.serialNumber.decode() == args.serial]
        if len(devices) != 1:
            raise RuntimeError('Expected one Berxel camera; found %d. Use --serial for multiple cameras.' % len(devices))
        serial = devices[0].serialNumber.decode()
        device = context.openDevice(devices[0])
        if device is None:
            raise RuntimeError('Berxel openDevice failed')
        color = 1
        mode = device.getCurrentFrameMode(color)
        if mode is None:
            raise RuntimeError('No color profile reported by SDK')
        if args.stream_mode == 'single':
            # Same documented setting used by the vendor's C++ HawkColor sample.
            if device.setStreamFlagMode(1) != 0:
                raise RuntimeError('Berxel single-stream mode was rejected')
        if any(v is not None for v in (args.width, args.height, args.fps)):
            modes = device.getSupportFrameModes(color)
            matches = [m for m in modes
                       if (args.width is None or m.resolutionX == args.width)
                       and (args.height is None or m.resolutionY == args.height)
                       and (args.fps is None or m.framerate == args.fps)]
            if not matches:
                profiles = ', '.join('%dx%d@%d' % (m.resolutionX, m.resolutionY, m.framerate) for m in modes)
                raise RuntimeError('Requested profile unavailable. Supported: ' + profiles)
            mode = min(matches, key=lambda m: (-m.framerate, abs(m.resolutionX*m.resolutionY-640*400)))
        if args.stream_mode == 'single' or any(v is not None for v in (args.width, args.height, args.fps)):
            # Switching to single mode otherwise changes the SDK default to 1080p.
            if device.setFrameMode(color, mode) != 0:
                raise RuntimeError('Berxel rejected selected color profile')
        report('info', 'P100R %s: color %dx%d @ %d fps (%s, callback)' %
               (serial, mode.resolutionX, mode.resolutionY, mode.framerate, args.stream_mode))

        def on_frame(stream, handle, user):
            arrival = time.perf_counter_ns()
            frame = BerxelHawkFrame(handle)
            try:
                if stop.is_set():
                    return
                w, h = frame.getWidth(), frame.getHeight()
                if frame.getPixelType() != 0 or frame.getDataSize() != w * h * 3:
                    raise RuntimeError('Expected RGB24 from Berxel color stream')
                rgb = np.ctypeslib.as_array(frame.getDataAsUint8()).reshape(h, w, 3)
                slot.publish(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), arrival,
                             frame.getFrameIndex(), frame.getTimeStamp(), 'berxel_device_unspecified')
            except Exception as exc:
                report('error', str(exc))
                stop.set()
            finally:
                device.releaseFrame(frame)

        callback = BerxelNewFrameCallback(on_frame)  # Keep native callback alive until stop.
        if device.startStreams(color, callback) != 0:
            raise RuntimeError('Berxel color stream failed to start; see SDK log')
        report('ready', 'Color stream started')
        stop.wait()
    finally:
        if device is not None:
            device.stopStream(1)
            context.closeDevice(device)
        context.destroyCamera()
        if dll_directory is not None:
            dll_directory.close()


def run_rs(args, slot, stop, report):
    import pyrealsense2 as rs
    context = rs.context()
    devices = list(context.query_devices())
    if args.serial:
        devices = [d for d in devices if d.get_info(rs.camera_info.serial_number) == args.serial]
    if len(devices) != 1:
        raise RuntimeError('Expected one RealSense camera; use --serial for multiple cameras')
    # Same low-latency color preference as the C++ entry. No model-name branches.
    formats = [rs.format.yuyv, rs.format.y8, rs.format.bgr8, rs.format.rgb8]
    candidates = []
    for sensor in devices[0].query_sensors():
        for profile in sensor.get_stream_profiles():
            if profile.stream_type() != rs.stream.color or profile.format() not in formats:
                continue
            video = profile.as_video_stream_profile()
            if ((args.width is not None and video.width() != args.width)
                    or (args.height is not None and video.height() != args.height)
                    or (args.fps is not None and video.fps() != args.fps)):
                continue
            if video.width() * video.height() <= 1920 * 1080:
                candidates.append((sensor, video))
    if not candidates:
        raise RuntimeError('No supported RealSense color profile')
    sensor, profile = min(candidates, key=lambda p: (
        -p[1].fps(), abs(p[1].width() * p[1].height() - 640 * 480),
        formats.index(p[1].format())))
    report('info', '%s: color %dx%d @ %d %s (sensor callback)' % (
        devices[0].get_info(rs.camera_info.name), profile.width(), profile.height(),
        profile.fps(), profile.format()))

    def on_frame(frame):
        arrival = time.perf_counter_ns()
        try:
            if stop.is_set():
                return
            data = np.asanyarray(frame.get_data())
            fmt = frame.get_profile().format()
            if fmt == rs.format.yuyv:
                data = cv2.cvtColor(data, cv2.COLOR_YUV2BGR_YUY2)
            elif fmt == rs.format.rgb8:
                data = cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
            elif fmt == rs.format.y8:
                data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
            slot.publish(data, arrival, frame.get_frame_number(), frame.get_timestamp() * 1000,
                         str(frame.get_frame_timestamp_domain()))
        except Exception as exc:
            report('error', str(exc))
            stop.set()

    sensor.open(profile)
    started = False
    try:
        sensor.start(on_frame)
        started = True
        report('ready', 'Color stream started')
        stop.wait()
    finally:
        if started:
            sensor.stop()
        sensor.close()


def capture_worker(args, slot, stop, messages):
    # Serialise status writes from native callback threads. No per-frame messages.
    mutex = threading.Lock()

    def report(kind, text):
        with mutex:
            messages.send((kind, text))
    try:
        cv2.setNumThreads(1)
        if args.backend == 'p100r':
            run_p100r(args, slot, stop, report)
        else:
            run_rs(args, slot, stop, report)
    except Exception as exc:
        report('error', '%s: %s' % (type(exc).__name__, exc))
    finally:
        messages.close()


class CameraSource:
    def __init__(self, args):
        ctx = mp.get_context('spawn')
        self.slot = SharedFrame(ctx)
        self.stop = ctx.Event()
        self.messages, writer = ctx.Pipe(duplex=False)
        self.process = ctx.Process(target=capture_worker, args=(args, self.slot, self.stop, writer), daemon=True)
        # Linux resolves dependencies at process startup, before importing the vendor wrapper.
        old_path = os.environ.get('LD_LIBRARY_PATH')
        if os.name != 'nt' and args.backend == 'p100r':
            lib = str(Path(args.berxel_root).resolve() / 'BerxelSdkDriver' / 'libs' / 'linux')
            os.environ['LD_LIBRARY_PATH'] = lib + (':' + old_path if old_path else '')
        try:
            self.process.start()
        finally:
            if old_path is None:
                os.environ.pop('LD_LIBRARY_PATH', None)
            else:
                os.environ['LD_LIBRARY_PATH'] = old_path
            writer.close()

    def status(self):
        result = []
        try:
            while self.messages.poll():
                result.append(self.messages.recv())
        except EOFError:
            pass
        return result

    def close(self):
        self.stop.set()
        self.process.join(2)
        if self.process.is_alive():
            print('SDK cleanup timed out; stopping this capture worker only.', flush=True)
            self.process.terminate()
            self.process.join(2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(2)
        self.messages.close()
        self.process.close()
