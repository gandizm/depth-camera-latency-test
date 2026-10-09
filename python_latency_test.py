#!/usr/bin/env python3
"""Tiny cross-platform visual latency test for RealSense or Berxel/P100R.

Point the selected camera at the full-screen window.  The reported value is
screen flip -> frame returned by the SDK -> center-dot detection.  It is a
visual pipeline measurement, not exposure time.
"""
import argparse, importlib, os, statistics, sys, time
import cv2, numpy as np

def berxel_frames(berxel_root=None):
    root=berxel_root or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Python')
    sys.path.insert(0, os.path.abspath(root))
    from BerxelSdkDriver.BerxelHawkContext import BerxelHawkContext
    from BerxelSdkDriver.BerxelHawkDefines import BerxelHawkStreamType
    ctx=BerxelHawkContext(); ctx.initCamera(); devices=ctx.getDeviceList()
    if not devices: raise RuntimeError('No Berxel device found')
    dev=ctx.openDevice(devices[0]);
    if dev is None: raise RuntimeError('Could not open Berxel device')
    if dev.startStreams(BerxelHawkStreamType.forward_dict['BERXEL_HAWK_COLOR_STREAM']) != 0:
        raise RuntimeError('Could not start Berxel color stream')
    try:
        while True:
            f=dev.readColorFrame(100)
            if f is not None:
                w,h=f.getWidth(),f.getHeight()
                raw=np.ctypeslib.as_array(f.getDataAsUint8()).reshape((h,w,3)).copy()
                yield raw, time.perf_counter(), f.getTimeStamp()
                dev.releaseFrame(f)
    finally:
        dev.stopStream(1); ctx.closeDevice(dev); ctx.destroyCamera()

def rs_frames():
    rs=importlib.import_module('pyrealsense2')
    p=rs.pipeline(); c=rs.config(); c.enable_stream(rs.stream.color)
    p.start(c)
    try:
        while True:
            fs=p.wait_for_frames(); f=fs.get_color_frame()
            if f:
                yield np.asanyarray(f.get_data()).copy(), time.perf_counter(), f.get_timestamp()
    finally: p.stop()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--backend',choices=['auto','berxel','rs'],default='auto')
    ap.add_argument('--samples',type=int,default=100); ap.add_argument('--panel-ms',type=float,default=0)
    ap.add_argument('--berxel-root',default=None, help='directory containing BerxelSdkDriver')
    ap.add_argument('--period-ms',type=float,default=200); a=ap.parse_args()
    backend=a.backend
    if backend=='auto':
        try: importlib.import_module('pyrealsense2'); backend='rs'
        except ImportError: backend='berxel'
    frames=rs_frames() if backend=='rs' else berxel_frames(a.berxel_root)
    W,H=640,480; win='visual-latency'; cv2.namedWindow(win,cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win,cv2.WND_PROP_FULLSCREEN,cv2.WINDOW_FULLSCREEN)
    img=np.zeros((H,W,3),np.uint8); state=False; last=False; pending=None; vals=[]; next_flip=time.perf_counter()+1
    print('backend=',backend,'; aim camera at screen; q quits')
    while len(vals)<a.samples:
        now=time.perf_counter()
        if now>=next_flip:
            state=not state; img[:]=0
            if state: cv2.circle(img,(W//2,H//2),80,(255,255,255),-1)
            cv2.imshow(win,img); cv2.waitKey(1); pending=(state,time.perf_counter()); next_flip=pending[1]+a.period_ms/1000
        try: frame,arrival,_=next(frames)
        except StopIteration: break
        g=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); roi=g[H//2-40:H//2+40,W//2-40:W//2+40]
        seen=float(roi.mean())>100
        if pending and seen!=last and seen==pending[0]:
            ms=(arrival-pending[1])*1000-a.panel_ms
            if 0<ms<1000: vals.append(ms); print('%3d  %.3f ms'%(len(vals),ms))
            pending=None
        last=seen
        if cv2.waitKey(1)&255==ord('q'): break
    if vals: print('median=%.3f mean=%.3f p95=%.3f ms'%(statistics.median(vals),statistics.mean(vals),np.percentile(vals,95)))
    cv2.destroyAllWindows()
if __name__=='__main__': main()
