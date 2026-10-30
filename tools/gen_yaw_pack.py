#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_yaw_pack.py —— 生成扭头帧包，供 Fabric 模组内置使用

输出单个二进制文件 yaw_pack.bin（放进模组 resources）：
    magic "YAW1" (4B)
    count  (1B)
    step   (1B)   角度步长
    minYaw (2B, int16)
    w, h   (2B each)
    每帧: len(2B) + RLE 数据

模组读取后，按 (yaw-minYaw)/step 取帧，直接用 C/0/1/2 协议推给板子。
这样不需要任何 PC 端 Python 进程，Minecraft 启动即可用。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

import gltf_render as G
import mcstream

MODEL = "D:/axolotl/packages/assets/models/slim-player.gltf"
YAW_MIN, YAW_MAX, YAW_STEP = -60, 60, 5
W, H = 126, 160

# 输出到模组资源目录
OUT = r"D:\modbuild\mcserial\src\main\resources\yaw_pack.bin"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    skin = Image.open(os.path.join(here, "..", "skin_user.png")).convert("RGBA")
    model = G.GltfModel(MODEL)
    base_pose = {"Right_Arm": {"rx": -10}, "Left_Arm": {"rx": 10}}

    angles = list(range(YAW_MIN, YAW_MAX + 1, YAW_STEP))
    frames = []

    print(f"渲染 {len(angles)} 个角度 ...")
    for yaw in angles:
        pose = dict(base_pose)
        pose["Head"] = {"ry": float(yaw)}
        img = G.render(model.build(pose), skin, W, H)

        px = []
        p = img.load()
        for y in range(H):
            for x in range(W):
                r, g, b, a = p[x, y]
                px.append(0xF81F if a < 128 else
                          (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
        enc = mcstream.rle_encode(px)
        frames.append(enc)
        print(f"  {yaw:+4d}°  {len(enc):5d}B")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(b"YAW1")
        f.write(struct.pack("<BBhHH", len(frames), YAW_STEP, YAW_MIN, W, H))
        for enc in frames:
            f.write(struct.pack("<H", len(enc)))
            f.write(enc)

    total = os.path.getsize(OUT)
    print(f"\n生成 {OUT}")
    print(f"  {len(frames)} 帧, {total/1024:.0f} KB")


if __name__ == "__main__":
    main()
