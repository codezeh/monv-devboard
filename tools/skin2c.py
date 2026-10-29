#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skin2c.py —— Minecraft 皮肤 → STM32 用的半身像 C 数组

【重要认知】
    MC 皮肤 PNG 是 64x64 的【纹理图集】，平铺着头/身/四肢 6 个面的贴图，
    它本身**不是 3D 数据**。立体效果必须靠软件"搭盒模型 + 相机投影 + 光栅化"算出来。

    本项目把这套 3D 运算放在 PC 端（tools/mcskin3d.py，真正的透视相机 +
    z-buffer + 透视校正纹理 + N·L 光照），渲染成一张小尺寸精灵，
    固件只负责整数倍放大、染色、位移 —— 这样 MCU 端零 3D 数学，Flash 和 CPU 都省。

用法：
    # 3/4 斜视角（默认），自动识别粗细手臂
    python skin2c.py my_skin.png -o ../示例代码/BSP/SKIN/skin_bust.c

    # 调角度
    python skin2c.py my_skin.png --yaw 28 --pitch -12 -o ...

    # 苗条手臂（Alex 模型，3px）
    python skin2c.py my_skin.png --arms slim -o ...

    # 老的正视图（无透视）
    python skin2c.py my_skin.png --view front -o ...

    # 内置 Steve 占位小人
    python skin2c.py --make-default -o ...
"""

import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow：pip install Pillow")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcskin3d

TRANSPARENT_KEY = 0xF81F
OUTLINE_RGBA = (10, 12, 18, 255)

# 皮肤部位（正视图用）
HEAD_FRONT = (8, 8, 8, 8)
BODY_FRONT = (20, 20, 8, 12)
ARM_R_FRONT = (44, 20, 4, 12)
ARM_L_FRONT = (36, 52, 4, 12)


# ------------------------------------------------------------------ 基础工具
def load_skin(path):
    im = Image.open(path).convert("RGBA")
    if im.size not in ((64, 64), (64, 32)):
        print(f"⚠️  尺寸 {im.size} 不是 64x64 / 64x32，可能不是 MC 皮肤")
    return im


def detect_arms(skin):
    """判断经典(4px)还是苗条(3px)手臂。

    苗条皮肤的判定依据（任一成立即认为 slim）：
      1) 手臂正面第 4 列(x=47)整列透明 —— 模型用不到这一列
      2) 第 4 列与第 3 列在 12 行中 >=8 行完全相同 —— 是复制填充的
    否则认为是经典 4px（第 4 列有独立内容）。

    高清皮肤按比例换算列坐标。
    """
    try:
        k = max(1, skin.width // 64)
        x3, x4, y0 = 46 * k, 47 * k, 20 * k

        col4 = [skin.getpixel((x4, y0 + i * k)) for i in range(12)]
        col3 = [skin.getpixel((x3, y0 + i * k)) for i in range(12)]

        # 1) 第 4 列整列透明 → 苗条
        if all(c[3] < 16 for c in col4):
            return "slim"

        # 2) 第 4 列基本是复制第 3 列 → 苗条
        same = sum(1 for a, b in zip(col3, col4) if a == b)
        if same >= 8:
            return "slim"

        return "classic"
    except (IndexError, TypeError):
        return "classic"


def crop_to_content(img):
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def apply_outline(img):
    """给不透明像素的 1 像素外圈描深色边，把人物从卡片底色里分出来"""
    img = img.copy()          # fromarray/resize 出来的图可能是只读的
    w, h = img.size
    px = img.load()
    todo = []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] >= 128:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny][3] < 128:
                        todo.append((nx, ny))
    for (x, y) in todo:
        px[x, y] = OUTLINE_RGBA
    return img


def img_to_vals(img):
    vals = []
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a < 128:
                vals.append(TRANSPARENT_KEY)
            else:
                vals.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return vals


# ------------------------------------------------------------------ 渲染入口
def render_3d(skin, arms, sprite_w, ss, yaw, pitch, cut=0.0):
    """真透视渲染 → 裁边 → 裁掉底部一截 → 缩到 sprite_w 宽 → 描边"""
    aw = 3 if arms == "slim" else 4

    hi = mcskin3d.render(skin, aw, sprite_w * ss, int(sprite_w * ss * 1.30),
                         yaw=yaw, pitch=pitch, ss=1)
    hi = crop_to_content(hi)

    # 半身像在胸口截断，避免整个人太长（cut=0.18 表示砍掉底部 18%）
    if cut > 0:
        keep = max(2, int(round(hi.height * (1.0 - cut))))
        hi = hi.crop((0, 0, hi.width, keep))

    ratio = sprite_w / hi.width
    out_h = max(1, round(hi.height * ratio))
    img = hi.resize((sprite_w, out_h), Image.BOX)
    img = apply_outline(img)
    return img, img.width, img.height


def render_front(skin, arms):
    """正交正视图（无透视），作为对比保留"""
    aw = 3 if arms == "slim" else 4
    W, H = aw * 2 + 8, 20
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def paste(box, dx, dy):
        x, y, w, h = box
        if x + w > skin.width or y + h > skin.height:
            return
        img.paste(skin.crop((x, y, x + w, y + h)), (dx, dy))

    paste(HEAD_FRONT, aw, 0)
    paste(BODY_FRONT, aw, 8)
    paste((ARM_R_FRONT[0], ARM_R_FRONT[1], aw, 12), aw + 8, 8)
    paste((ARM_L_FRONT[0], ARM_L_FRONT[1], aw, 12), 0, 8)
    return crop_to_content(img), img.width, img.height


# ------------------------------------------------------------------ 输出 C
def write_c(out_c, w, h, vals, view, arms):
    out_h = os.path.splitext(out_c)[0] + ".h"
    os.makedirs(os.path.dirname(os.path.abspath(out_c)), exist_ok=True)

    with open(out_h, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join([
            "/**====================================================================",
            " ** 自动生成，请勿手改 —— 由 tools/skin2c.py 生成",
            f" ** 视图：{view}  |  手臂：{arms}",
            f" ** 尺寸：{w}x{h} texel，RGB565，{w*h*2} 字节 Flash",
            f" ** 透明色：0x{TRANSPARENT_KEY:04X}（渲染时被背景/卡片色替换）",
            "====================================================================*/",
            "#ifndef __SKIN_BUST_H",
            "#define __SKIN_BUST_H",
            "",
            "#include <stdint.h>",
            "",
            f"#define SKIN_TEX_W   {w}",
            f"#define SKIN_TEX_H   {h}",
            "",
            f"extern const uint16_t g_skin_bust[{w * h}];",
            "",
            "#endif",
            "",
        ]))

    lines = [
        "/**====================================================================",
        f" ** 自动生成，请勿手改 —— {view} / {arms} / {w}x{h} / {w*h*2} 字节",
        "====================================================================*/",
        '#include "skin_bust.h"',
        "",
        f"const uint16_t g_skin_bust[{w * h}] = {{",
    ]
    for row in range(h):
        chunk = vals[row * w:(row + 1) * w]
        lines.append("    " + ", ".join(f"0x{v:04X}" for v in chunk) + f",  /* {row:2d} */")
    lines += ["};", ""]

    with open(out_c, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return out_h


def write_preview(img, outdir, scale, name="preview_bust.png"):
    big = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
    bg = Image.new("RGBA", big.size, (58, 70, 104, 255))
    bg.alpha_composite(big)
    p = os.path.join(outdir, name)
    bg.convert("RGB").save(p)
    return p


# ------------------------------------------------------------------ 内置占位 Steve
def make_default_skin():
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = im.load()

    def fill(box, color):
        x0, y0, w, h = box
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if 0 <= x < 64 and 0 <= y < 64:
                    d[x, y] = color

    HAIR = (58, 40, 24, 255); SKIN = (198, 155, 110, 255)
    SKIN_D = (176, 134, 92, 255); EYE_W = (250, 250, 250, 255)
    MOUTH = (108, 74, 52, 255); SHIRT = (0, 170, 170, 255)
    SHIRT_D = (0, 142, 142, 255); PANTS = (72, 62, 140, 255)

    fill((0, 8, 8, 8), HAIR); fill((8, 8, 8, 8), SKIN)
    fill((16, 8, 8, 8), HAIR); fill((24, 8, 8, 8), HAIR)
    fill((8, 0, 8, 8), HAIR); fill((16, 0, 8, 8), HAIR)
    fill((8, 8, 8, 1), HAIR); fill((8, 9, 1, 3), HAIR); fill((15, 9, 1, 3), HAIR)
    fill((9, 11, 1, 1), EYE_W); fill((10, 11, 1, 1), EYE_W)
    fill((13, 11, 1, 1), EYE_W); fill((14, 11, 1, 1), EYE_W)
    fill((11, 13, 1, 1), SKIN_D); fill((10, 14, 4, 1), MOUTH)
    fill((8, 13, 1, 2), SKIN_D); fill((15, 13, 1, 2), SKIN_D)
    fill((16, 20, 4, 12), SHIRT_D); fill((20, 20, 8, 12), SHIRT)
    fill((28, 20, 4, 12), SHIRT_D); fill((32, 20, 8, 12), SHIRT_D)
    fill((20, 16, 8, 4), SHIRT_D); fill((28, 16, 8, 4), SHIRT_D)
    fill((20, 30, 8, 2), PANTS)
    for ax in (40, 44, 48, 52):
        fill((ax, 20, 4, 12), SHIRT if ax == 44 else SHIRT_D)
    for ax in (32, 36, 40, 44):
        fill((ax, 52, 4, 12), SHIRT if ax == 36 else SHIRT_D)
    fill((44, 16, 4, 4), SHIRT_D); fill((48, 16, 4, 4), SHIRT_D)
    fill((36, 48, 4, 4), SHIRT_D); fill((40, 48, 4, 4), SHIRT_D)
    fill((44, 24, 4, 8), SKIN); fill((36, 56, 4, 8), SKIN)
    return im


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="MC 皮肤 → STM32 半身像")
    ap.add_argument("skin", nargs="?", help="皮肤 PNG")
    ap.add_argument("-o", "--out", default="skin_bust.c")
    ap.add_argument("--make-default", action="store_true")
    ap.add_argument("--view", choices=["3d", "front"], default="3d")
    ap.add_argument("--arms", choices=["auto", "classic", "slim"], default="auto")
    ap.add_argument("--yaw", type=float, default=26.0, help="偏航角（度），默认 26")
    ap.add_argument("--pitch", type=float, default=-11.0, help="俯仰角（度），默认 -11")
    ap.add_argument("--sprite-w", type=int, default=22, help="输出精灵宽度（texel），默认 22")
    ap.add_argument("--cut", type=float, default=0.15, help="底部裁掉比例，做半身像截断，默认 0.15")
    ap.add_argument("--ss", type=int, default=6, help="渲染超采样倍数，默认 6")
    ap.add_argument("--scale", type=int, default=4, help="预览放大倍数（=固件 SKIN_SCALE）")
    args = ap.parse_args()

    if args.make_default or not args.skin:
        print("→ 内置 Steve 占位小人")
        skin, arms = make_default_skin(), "classic"
    else:
        skin = load_skin(args.skin)
        print(f"→ 载入 {args.skin}  {skin.size}")
        arms = detect_arms(skin) if args.arms == "auto" else args.arms
        print(f"→ 手臂类型：{arms}（{4 if arms == 'classic' else 3}px 宽）")

    if args.view == "3d":
        print(f"→ 透视渲染 yaw={args.yaw}° pitch={args.pitch}° 超采样={args.ss}x 底部裁{args.cut*100:.0f}%")
        img, w, h = render_3d(skin, arms, args.sprite_w, args.ss, args.yaw, args.pitch, args.cut)
    else:
        img, w, h = render_front(skin, arms)

    vals = img_to_vals(img)
    hdr = write_c(args.out, w, h, vals, args.view, arms)
    pv = write_preview(img, os.path.dirname(os.path.abspath(args.out)), args.scale)

    print(f"✅ {args.out}  ({w}x{h} texel, {w*h*2} 字节 Flash)")
    print(f"✅ {hdr}")
    print(f"✅ {pv}")
    print(f"   固件显示 @SKIN_SCALE={args.scale}: {w*args.scale} x {h*args.scale} px")


if __name__ == "__main__":
    main()
