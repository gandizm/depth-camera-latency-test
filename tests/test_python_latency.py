"""Regressions for the failed Python port; no camera/window required."""
import multiprocessing as mp
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import python_latency_test as lab
from latency_capture import SharedFrame, CameraSource


class CircleProtocolTest(unittest.TestCase):
    def test_refresh_presets_and_custom_rate(self):
        for hz in (60, 120, 165, 240, 360, 500):
            budget = lab.refresh_budget(hz)
            self.assertAlmostEqual(budget['period_ms'], 1000/hz)
            self.assertAlmostEqual(budget['ideal_uniform_phase_mean_ms'], 500/hz)
        for hz in (0, -60, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                lab.refresh_budget(hz)

    def test_every_code_with_missing_zero_circles(self):
        # Reference positions follow the C++ 1280-wide display: 18 slots, 64 px apart.
        for value in range(lab.MODULUS):
            binary = [bool(value & (1 << i)) for i in range(13, -1, -1)]
            count = sum(binary)
            bits = [bool(count & 1), bool(count & 2)] + binary
            self.assertEqual(lab.pack_value(value), bits)
            row = [[76, 96, 26]]
            row += [[76 + (i+1)*64, 96, 26] for i, bit in enumerate(bits) if bit]
            row += [[76+17*64, 96, 26]]
            self.assertEqual(lab.decode_row(row), value, value)

    def test_bad_checksum_rejected(self):
        bits = lab.pack_value(1234)
        bits[0] = not bits[0]
        self.assertIsNone(lab.unpack_value(bits))

    def test_full_hough_path_on_rendered_sparse_patterns(self):
        cv2.setNumThreads(1)
        for value in (0, 1, 2, 513, 4321, 16383):
            image = np.zeros((720, 1280, 3), np.uint8)
            lab.draw_pattern(image, value)
            decoded, circles, preview = lab.detect(image)
            self.assertEqual(decoded, value, (value, circles))
            self.assertEqual(preview.shape, (350, 600, 3))
            decoded, _, _ = lab.detect(cv2.rotate(image, cv2.ROTATE_180), rotate=True)
            self.assertEqual(decoded, value)

    def test_selects_row_anywhere_in_frame(self):
        circles = [[x, 370, 13] for x in (10, 60, 210, 410)] + [[70, 40, 12], [90, 90, 10]]
        self.assertEqual(len(lab.select_circle_row(circles, 480)), 4)


class CaptureLifecycleTest(unittest.TestCase):
    def test_latest_slot_retains_callback_timestamp_before_copy(self):
        slot = SharedFrame(mp.get_context('spawn'))
        first = np.full((40, 64, 3), 11, np.uint8)
        last = np.full((40, 64, 3), 42, np.uint8)
        slot.publish(first, 1000, 1, 123, 'test-clock')
        slot.publish(last, 2000, 2, 456, 'test-clock')
        last[:] = 99
        frame = slot.take()
        self.assertTrue(np.all(frame['image'] == 42))
        self.assertEqual(frame['arrival_ns'], 2000)
        self.assertEqual(frame['frame_number'], 2)
        self.assertEqual(frame['skipped'], 1)
        self.assertEqual(frame['timestamp_domain'], 'test-clock')
        self.assertIsNone(slot.take())

    def test_close_stops_only_its_blocked_worker(self):
        ctx = mp.get_context('spawn')
        source = CameraSource.__new__(CameraSource)
        source.stop = ctx.Event()
        source.messages, writer = ctx.Pipe(duplex=False)
        source.process = ctx.Process(target=time.sleep, args=(60,), daemon=True)
        source.process.start()
        writer.close()
        before = time.monotonic()
        source.close()
        self.assertLess(time.monotonic()-before, 6)
        self.assertTrue(source.stop.is_set())

    def test_gui_x_checked_before_showing_another_frame(self):
        # No SDK and no real window; exercises actual GUI loop close handling.
        class Slot:
            meta = [1]
            def take(self):
                return None
        class Process:
            exitcode = 0
            def is_alive(self):
                return True
        class Source:
            slot, process = Slot(), Process()
            closed = False
            def __init__(self, args):
                pass
            def status(self):
                return []
            def close(self):
                Source.closed = True
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(lab, 'CameraSource', Source), \
                 patch.object(cv2, 'namedWindow'), patch.object(cv2, 'resizeWindow'), \
                 patch.object(cv2, 'destroyAllWindows'), \
                 patch.object(cv2, 'getWindowProperty', return_value=0), \
                 patch.object(cv2, 'imshow') as show:
                code = lab.main(['--csv', folder+'/test.csv'])
                self.assertEqual(code, 0)
                show.assert_not_called()
                self.assertTrue(Source.closed)

    def test_old_frame_cannot_become_valid_after_clock_wrap(self):
        from types import SimpleNamespace
        slot = SharedFrame(mp.get_context('spawn'))
        args = lab.parser().parse_args([])
        args.warmup = 0
        detector = lab.Detector(SimpleNamespace(slot=slot), args)
        try:
            with detector.lock:
                detector.current = 42
                detector.new_value = False
                detector.pattern_ns = detector.start_ns
            image = np.zeros((720, 1280, 3), np.uint8)
            lab.draw_pattern(image, 42)
            # After 16.384 seconds the naive modulo calculation would report ~42 ms.
            slot.publish(image, detector.start_ns + (lab.MODULUS+42)*1_000_000,
                         7, 0, 'test-clock')
            deadline = time.monotonic()+2
            while detector.frames == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(detector.frames, 1)
            self.assertEqual(detector.samples, [])
        finally:
            detector.close()


if __name__ == '__main__':
    unittest.main()
