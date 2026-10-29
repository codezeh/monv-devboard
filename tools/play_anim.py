#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
play_anim.py —— PC 端实时渲染 + 推流播放器

架构（用户提议）：
    PC 负责全部计算（3D 渲染 → RLE 压缩）
    板子只负责"收到就显示"，不存储、不判断、不烧录

好处：
    · 改动作不用烧录，改完直接重跑本脚本
    · 板子变成纯显示器，Flash 限制彻底消失
    · 动画复杂度不受限制

用法：
    python play_anim.py                # 自动循环播放所有状态
    python play_anim.py WALK           # 只播某个状态
    python play_anim.py WALK --fps 15  # 指定帧率
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serial

import anim_frames as A
import mcstream

STATES = ["IDLE", "WALK", "RUN", "ATTACK", "JUMP", "SNEAK", "SLEEP"]


def build_frames_for(state, skin, n=None):
    """渲染某状态的全部帧（内存中）"""
    n = n or A.FRAMES
    out = []
    for i in range(n):
        pose = A.pose_seq(state, i, n)
        img = A.render_full(skin, 3, pose=pose)
        out.append(mcstream.rle_encode(A.to565(img)))
    return out


def send_frame(ser, fw, fh, rle, chunk=250, gap=0.005):
    """发一帧：START + DATA 分块 + END"""
    ser.write(b"C" + bytes([0, 2, fw, fh]))
    for off in range(0, len(rle), chunk):
        blk = rle[off:off + chunk]
        ser.write(b"C" + bytes([1, len(blk)]) + blk)
        time.sleep(gap)
    ser.write(b"C" + bytes([2, 0]))
    ser.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", nargs="?", default=None)
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--loops", type=int, default=0, help="0=无限")
    args = ap.parse_args()

    from PIL import Image
    HERE = os.path.dirname(os.path.abspath(__file__))
    skin = Image.open(os.path.join(HERE, "..", "skin_user.png")).convert("RGBA")

    fw, fh = A.OUT_W, A.OUT_H

    print("预渲染帧 ...")
    cache = {}
    todo = [args.state] if args.state else STATES
    for st in todo:
        t0 = time.time()
        cache[st] = build_frames_for(st, skin)
        sz = sum(len(f) for f in cache[st])
        print(f"  {st:7} {len(cache[st])} 帧  {sz/1024:.1f}KB  ({time.time()-t0:.1f}s)")

    period = 1.0 / args.fps
    print(f"\n推流到 {args.port} @{args.baud}  目标 {args.fps}fps")
    print("Ctrl+C 停止\n")

    with serial.Serial(args.port, args.baud, timeout=0.5) as ser:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.6)
        ser.reset_input_buffer()

        loop = 0
        try:
            while args.loops == 0 or loop < args.loops:
                for st in todo:
                    frames = cache[st]
                    # 每个状态播 2 个循环，方便观察
                    for rep in range(2):
                        for rle in frames:
                            t0 = time.perf_counter()
                            send_frame(ser, fw, fh, rle)
                            dt = time.perf_counter() - t0
                            if dt < period:
                                time.sleep(period - dt)
                loop += 1
                print(f"  完成第 {loop} 轮", flush=True)
        except KeyboardInterrupt:
            print("\n已停止")


if __name__ == "__main__":
    main()
