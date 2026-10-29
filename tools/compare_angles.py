#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比不同相机角度，挑一个最像"魔兽头像"的 3/4 视角"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageDraw

import mcskin3d
import skin2c

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN = os.path.normpath(os.path.join(HERE, "..", "skin_user.png"))

# (标签, yaw, pitch)
ANGLES = [
    ("yaw12 pitch-6",  12, -6),
    ("yaw24 pitch-10", 24, -10),
    ("yaw34 pitch-14", 34, -14),
    ("yaw24 pitch-18", 24, -18),
    ("yaw44 pitch-10", 44, -10),
    ("yaw-24 pitch-10", -24, -10),
]

BG = (58, 70, 104)


def main():
    skin = Image.open(SKIN).convert("RGBA")
    arms = skin2c.detect_arms(skin)
    aw = 3 if arms == "slim" else 4

    cells = []
    for label, yaw, pitch in ANGLES:
        img = mcskin3d.render(skin, aw, 40, 46, yaw=yaw, pitch=pitch, ss=4)
        img = skin2c.crop_to_content(img)
        img = skin2c.apply_outline(img)
        cells.append((label, img))

    Z = 5
    PAD = 10
    LABEL = 15
    cw = max(c[1].width for c in cells) * Z
    ch = max(c[1].height for c in cells) * Z
    cols = 3
    rows = (len(cells) + cols - 1) // cols
    W = cols * (cw + PAD) + PAD
    H = rows * (ch + PAD + LABEL) + PAD

    sheet = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(sheet)

    for i, (label, img) in enumerate(cells):
        cx = PAD + (i % cols) * (cw + PAD)
        cy = PAD + (i // cols) * (ch + PAD + LABEL)
        d.text((cx, cy), label, fill=(230, 230, 230))
        big = img.resize((img.width * Z, img.height * Z), Image.NEAREST)
        panel = Image.new("RGBA", (cw, ch), BG + (255,))
        panel.alpha_composite(big, (0, 0))
        sheet.paste(panel.convert("RGB"), (cx, cy + LABEL))

    out = os.path.join(HERE, "preview_angles.png")
    sheet.save(out)
    print(f"✅ {out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
