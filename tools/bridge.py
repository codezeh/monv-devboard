#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bridge.py —— 唯一的串口持有者 + 扭头渲染桥接

## 为什么需要这个

之前 head_track.py 和游戏模组抢同一个 COM5：
  · Python 占着串口 -> 模组打不开 -> 每个 tick 重试 getCommPorts() -> 游戏卡死
  · 模组发不出角度 -> 头不动

## 现在的架构

    游戏模组 --写文件--> %TEMP%\\mcserial_state.txt --读--> bridge.py --串口--> 板子
                (state|yaw)

  串口只有 bridge.py 一个人用，不会抢。

## 两种显示模式自动切换

  |yaw| 小  -> 发状态命令(SI/SW/...)，板子播放 Flash 本地动画（30fps 流畅）
  |yaw| 大  -> PC 按角度渲染并推流（约 4.5fps），转头停下后自动切回 Flash

用法：
    python bridge.py                # 正常桥接
    python bridge.py --demo         # 演示左右转头
    python bridge.py --probe        # 只打印读到的东西
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
import head_track as HT

STATE_CMD = {
    "IDLE": b"SI", "WALK": b"SW", "RUN": b"SR", "HURT": b"SH",
    "JUMP": b"SJ", "ATTACK": b"SA", "SLEEP": b"SZ", "SNEAK": b"SK",
}

YAW_ON = 6          # |yaw| 超过这个角度才进入扭头模式
YAW_SETTLE_MS = 400  # 转头停止多久后切回 Flash


def state_file():
    return os.path.join(os.environ.get("TEMP", "/tmp"), "mcserial_state.txt")


def read_state(path):
    """读 'STATE|yaw'，返回 (state, yaw) 或 None"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            t = f.read().strip()
        if "|" not in t:
            return None
        st, yw = t.split("|", 1)
        return st.strip(), float(yw)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--fps", type=float, default=4.5)
    args = ap.parse_args()

    skin = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "skin_user.png")).convert("RGBA")
    r = HT.HeadRenderer(skin)
    period = 1.0 / args.fps

    if args.probe:
        print(f"读取 {state_file()} ... Ctrl+C 停止")
        try:
            while True:
                v = read_state(state_file())
                if v:
                    print(f"  {v[0]:7} yaw={v[1]:+.0f}")
                time.sleep(0.3)
        except KeyboardInterrupt:
            print("\n停止")
        return

    print("预渲染角度档位 ...")
    t0 = time.time()
    for yaw in range(HT.YAW_MIN, HT.YAW_MAX + 1, HT.YAW_STEP):
        r.frame(yaw)
    print(f"  {len(r.cache)} 档，{time.time()-t0:.1f}s")

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.5)
        ser.reset_input_buffer()

        if args.demo:
            print(f"演示转头 @{args.fps}fps ...")
            for rep in range(3):
                for yaw in list(range(-40, 41, 5)) + list(range(40, -41, -5)):
                    t1 = time.perf_counter()
                    HT.send_frame(ser, r.w, r.h, r.frame(yaw))
                    d = time.perf_counter() - t1
                    if d < period:
                        time.sleep(period - d)
            ser.write(b"SF"); ser.flush()
            print("演示结束（已切回 Flash）")
            return

        print(f"桥接中：{state_file()}  ->  {args.port}")
        print("（|yaw|>6 走 PC 渲染，否则板子播 Flash 动画）\n")

        last_state = None
        last_yaw_frame = None
        streaming = False
        last_move_ms = 0

        try:
            while True:
                v = read_state(state_file())
                if v is None:
                    time.sleep(0.05)
                    continue
                st, yaw = v
                now = time.time() * 1000

                # ---- 状态变化：只在非扭头模式下发给板子 ----
                if st != last_state:
                    last_state = st
                    if not streaming:
                        cmd = STATE_CMD.get(st, b"SI")
                        ser.write(cmd)
                        ser.flush()

                # ---- 扭头：角度够大才渲染 ----
                if abs(yaw) >= YAW_ON:
                    q = r.quantize(yaw)
                    if q != last_yaw_frame:
                        last_yaw_frame = q
                        last_move_ms = now
                        streaming = True
                        t1 = time.perf_counter()
                        HT.send_frame(ser, r.w, r.h, r.frame(q))
                        d = time.perf_counter() - t1
                        if d < period:
                            time.sleep(period - d)
                    elif streaming and (now - last_move_ms) > YAW_SETTLE_MS:
                        # 转头停了：切回 Flash 本地动画
                        ser.write(b"SF")
                        ser.flush()
                        streaming = False
                        last_yaw_frame = None
                        last_state = None       # 强制重发状态
                else:
                    # 回到正前方
                    if streaming and (now - last_move_ms) > YAW_SETTLE_MS:
                        ser.write(b"SF")
                        ser.flush()
                        streaming = False
                        last_yaw_frame = None
                        last_state = None

                time.sleep(0.03)
        except KeyboardInterrupt:
            try:
                ser.write(b"SF")
                ser.flush()
            except Exception:
                pass
            print("\n停止")


if __name__ == "__main__":
    main()
