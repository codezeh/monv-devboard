#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
head_track.py —— 扭头跟踪（方案 3：细节动作走 PC）

架构：
    游戏模组读出头部角度 → 串口发给 PC → PC 按角度渲染 → 推流给板子显示

为什么扭头走 PC 而不是烧进 Flash：
    · 扭头需要连续角度（不是几档跳变），烧 Flash 要 504 帧 = 3MB，放不下
    · 扭头是慢动作，约 5fps 就够（UART 带宽限制）
    · 不占 Flash，现有 7 状态动画质量不受影响

用法：
    python head_track.py                    # 读取角度流，自动渲染推流
    python head_track.py --demo             # 演示：自动左右转头
    python head_track.py --probe            # 只打印收到的角度，不推流
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serial
from PIL import Image

import gltf_render as G
import mcstream

MODEL = "D:/axolotl/packages/assets/models/slim-player.gltf"

# 角度分档：每 5° 一档，-60~+60
YAW_MIN, YAW_MAX, YAW_STEP = -60, 60, 5


class HeadRenderer:
    def __init__(self, skin, w=126, h=160):
        self.skin = skin
        self.w, self.h = w, h
        self.model = G.GltfModel(MODEL)
        self.cache = {}
        self.base_pose = {"Right_Arm": {"rx": -10}, "Left_Arm": {"rx": 10}}

    def quantize(self, yaw):
        """把连续角度量化到档位"""
        y = max(YAW_MIN, min(YAW_MAX, yaw))
        return int(round(y / YAW_STEP) * YAW_STEP)

    def frame(self, yaw):
        """取该角度的 RLE 帧（带缓存）"""
        q = self.quantize(yaw)
        if q in self.cache:
            return self.cache[q]

        pose = dict(self.base_pose)
        pose["Head"] = {"ry": float(q)}
        m = self.model.build(pose)
        img = G.render(m, self.skin, self.w, self.h)

        px = []
        p = img.load()
        for y in range(self.h):
            for x in range(self.w):
                r, g, b, a = p[x, y]
                px.append(0xF81F if a < 128 else
                          (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
        enc = mcstream.rle_encode(px)
        self.cache[q] = enc
        return enc


def send_frame(ser, fw, fh, rle, chunk=250, gap=0.005):
    ser.write(b"C" + bytes([0, 2, fw, fh]))
    for off in range(0, len(rle), chunk):
        blk = rle[off:off + chunk]
        ser.write(b"C" + bytes([1, len(blk)]) + blk)
        time.sleep(gap)
    ser.write(b"C" + bytes([2, 0]))
    ser.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--demo", action="store_true", help="自动左右转头演示")
    ap.add_argument("--probe", action="store_true", help="只打印角度")
    ap.add_argument("--fps", type=float, default=4.5)
    args = ap.parse_args()

    skin = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "skin_user.png")).convert("RGBA")

    if args.probe:
        # 只监听角度
        with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
            print(f"监听 {args.port} 的角度数据 ... Ctrl+C 停止")
            buf = b""
            try:
                while True:
                    buf += ser.read(256)
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        t = line.decode("ascii", "replace").strip()
                        if t.startswith("HY:"):
                            print("  角度", t[3:])
            except KeyboardInterrupt:
                print("\n停止")
        return

    r = HeadRenderer(skin)
    print("预渲染角度档位 ...")
    t0 = time.time()
    for yaw in range(YAW_MIN, YAW_MAX + 1, YAW_STEP):
        r.frame(yaw)
    print(f"  {len(r.cache)} 档，耗时 {time.time()-t0:.1f}s")

    period = 1.0 / args.fps

    with serial.Serial(args.port, args.baud, timeout=0.3) as ser:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.6)
        ser.reset_input_buffer()

        if args.demo:
            print(f"演示左右转头 @{args.fps}fps ...")
            seq = list(range(-40, 41, 5)) + list(range(40, -41, -5))
            try:
                for rep in range(4):
                    for yaw in seq:
                        t1 = time.perf_counter()
                        send_frame(ser, r.w, r.h, r.frame(yaw))
                        d = time.perf_counter() - t1
                        if d < period:
                            time.sleep(period - d)
                print("演示结束")
            except KeyboardInterrupt:
                print("\n停止")
            return

        # 正常模式：从串口读角度，驱动渲染
        print(f"跟踪模式：读 {args.port} 的 HY:角度 ...")
        buf = b""
        last = None
        try:
            while True:
                buf += ser.read(128)
                changed = False
                yaw = None
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    t = line.decode("ascii", "replace").strip()
                    if t.startswith("HY:"):
                        try:
                            yaw = float(t[3:])
                            changed = True
                        except ValueError:
                            pass
                if changed and yaw is not None:
                    q = r.quantize(yaw)
                    if q != last:
                        last = q
                        t1 = time.perf_counter()
                        send_frame(ser, r.w, r.h, r.frame(q))
                        d = time.perf_counter() - t1
                        if d < period:
                            time.sleep(period - d)
        except KeyboardInterrupt:
            print("\n停止")


if __name__ == "__main__":
    main()
