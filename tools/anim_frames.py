#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anim_frames.py —— 方案 C：把 8 个状态的完整动画帧全部在 PC 端渲染好

每帧都是【完整人物图】（头+身+双臂），所以固件只需要"解压某一帧 → 显示"，
不存在对齐/合成问题。手臂是 3D 绕肩旋转渲染的，是真正的旋转。

输出：
    tools/anim_preview.png   各状态帧预览
    BSP/SKIN/skin_anim.c     帧数据（RLE，编译进固件 Flash）
    BSP/SKIN/skin_anim.h     帧表尺寸
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

import arm_frames as AF
import mcstream

NL = chr(10)

def _skin_path(default_rel):
    """皮肤文件路径。优先环境变量 SKIN_PATH，否则用默认相对路径。
    仓库不附带皮肤（版权原因），需要自备一张 64x64 的 Minecraft 皮肤。"""
    p = os.environ.get("SKIN_PATH") or os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), default_rel))
    if not os.path.exists(p):
        raise SystemExit(
            "找不到皮肤文件: %s\n"
            "仓库不附带皮肤图（版权原因）。请自备一张 Minecraft 皮肤，然后：\n"
            "    set SKIN_PATH=D:\\path\\to\\your_skin.png\n"
            "或把皮肤放到上面这个默认位置。" % p)
    return p
   # 避免转义问题

# ---------------- 输出规格（与现有风格一致） ----------------
OUT_W = 126          # 屏幕像素宽（<=126 防 ST7735 列地址越界）
OUT_H = 160          # 屏幕像素高
FRAMES = 8           # 每状态帧数


# ==============================================================
#  渲染一帧完整图：头 + 身 + 双臂（指定角度）
# ==============================================================
# Steve 用的是 classic（4px 手臂）模型；Alex 那种细手臂才是 slim（3px）
MODEL_PATH = os.environ.get(
    "AXOLOTL_MODEL_DIR", "D:/axolotl/packages/assets/models").replace("\\", "/") \
    + "/classic-player.gltf"


def load_model(pose=None):
    """加载 Axolotl 官方 glTF 玩家模型（带姿态）"""
    import gltf_render as GR
    return GR.GltfModel(MODEL_PATH).build(pose)


def render_full(skin, aw, pose=None, crop_box=None, yaw=160.0, pitch=-6.0):
    """用官方 glTF 模型渲染一帧（骨骼真旋转 + 身体位移）"""
    import gltf_render as GR
    m = GR.GltfModel(MODEL_PATH).build(pose or {})
    return GR.render(m, skin, 126, 160, yaw=yaw, pitch=pitch)


# ==============================================================
#  各状态的手臂角度序列（度）
#     左臂与右臂反相（MC 原版：cos(limbSwing + PI) vs cos(limbSwing)）
# ==============================================================
def pose_seq(state, i, n=FRAMES):
    """返回该帧完整骨骼姿态（Axolotl 官方 glTF 节点名）

    rx/ry: 度   ty: 模型单位（模型总高 2.0）
    ★ Body.rx 负值 = 前倾（正值会往后倒，已实测确认）
    """
    t = i / float(n)
    a = 2 * math.pi * t
    REST_R, REST_L = -10.0, 10.0      # 抵消模型自带 ±10°，得到垂直下垂

    # ---------------- 待机：双臂垂直，只有极轻呼吸 ----------------
    if state == "IDLE":
        return {
            "Body":      {"ty": math.sin(a) * 0.004},
            "Right_Arm": {"rx": REST_R},
            "Left_Arm":  {"rx": REST_L},
        }

    # ---------------- 走路：手臂前后反相摆 ±30° + 身体起伏 ----------------
    if state == "WALK":
        sw = math.sin(a) * 30
        return {
            "Body":      {"ty": abs(math.sin(a * 2)) * 0.018},
            "Right_Arm": {"rx": REST_R + sw},
            "Left_Arm":  {"rx": REST_L - sw},
        }

    # ---------------- 疾走：摆幅 ±55° + 身体前倾 8° + 起伏更大 ----------------
    if state == "RUN":
        sw = math.sin(a) * 55
        return {
            "Body":      {"ty": abs(math.sin(a * 2)) * 0.040, "rx": -8},
            "Head":      {"rx": -3},
            "Right_Arm": {"rx": REST_R + sw},
            "Left_Arm":  {"rx": REST_L - sw},
        }

    # ---------------- 攻击：右臂【向前】抬起到 +110°，再劈回 ----------------
    # ★ 实测：Right_Arm 的 rx 正值 = 向前抬，负值 = 向后收。
    #   之前用 -100 导致手臂往后摆，方向错了。
    if state == "ATTACK":
        if t < 0.42:
            k = t / 0.42
            arm = REST_R + 120 * k        # -10 → +110（向前抬起）
            brx = 5 * k                    # 略微后仰蓄力
        else:
            k = (t - 0.42) / 0.58
            arm = 110 - 120 * k            # +110 → -10（向前劈下）
            brx = 5 - 13 * k               # 前倾
        return {
            "Body":      {"rx": brx},
            "Head":      {"rx": brx * 0.5},
            "Right_Arm": {"rx": arm},
            "Left_Arm":  {"rx": REST_L},
        }

    # ---------------- 跳跃：整体上移（幅度适中，不飘出画面）----------------
    if state == "JUMP":
        up = math.sin(math.pi * t)           # 0→1→0
        return {
            "Body":      {"ty": up * 0.12},  # 收紧取景后只需小幅度
            "Right_Arm": {"rx": REST_R - up * 55},
            "Left_Arm":  {"rx": REST_L - up * 55},
        }

    # ---------------- 潜行：身体前倾 + 整体下沉 + 头低 ----------------
    if state == "SNEAK":
        return {
            "Body":      {"ty": -0.22 + math.sin(a) * 0.005, "rx": -6},
            "Head":      {"rx": -6},
            "Right_Arm": {"rx": REST_R + 16},
            "Left_Arm":  {"rx": REST_L + 16},
        }

    # ---------------- 睡觉：下沉 + 头垂 ----------------
    if state == "SLEEP":
        return {
            "Body":      {"ty": -0.10 + math.sin(a) * 0.004, "rx": -4},
            "Head":      {"rx": -14},
            "Right_Arm": {"rx": REST_R + 6},
            "Left_Arm":  {"rx": REST_L + 6},
        }

    return {"Right_Arm": {"rx": REST_R}, "Left_Arm": {"rx": REST_L}}


# ==============================================================
#  生成所有帧
# ==============================================================
def build_frames(skin_path=None, out_w=OUT_W):
    HERE = os.path.dirname(os.path.abspath(__file__))
    if skin_path is None:
        skin_path = _skin_path("../skins/steve.png")
    skin = Image.open(skin_path).convert("RGBA")
    aw = 3


    # 统一缩放到 OUT_W×OUT_H（保持比例，多余留白）
    tw, th = OUT_W, OUT_H     # glTF 渲染已直接输出目标尺寸

    import skin2c

    # HURT 复用 IDLE 帧（运行时染色），省 56KB Flash
    states = ["IDLE", "WALK", "RUN", "ATTACK", "JUMP", "SNEAK", "SLEEP"]
    result = {}
    for st in states:
        frames = []
        for i in range(FRAMES):
            pose = pose_seq(st, i)
            img = render_full(skin, aw, pose=pose)
            frames.append(img)
        result[st] = frames
    return result, (tw, th)


def to565(img):
    px = []
    pix = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pix[x, y]
            px.append(0xF81F if a < 128 else
                      (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
    return px


def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    frames, (fw, fh) = build_frames()
    print(f"帧尺寸: {fw}x{fh}")

    # ---- 预览 ----
    from PIL import ImageDraw
    states = list(frames.keys())
    Z = 1
    cell_w, cell_h = fw + 6, fh + 18
    sheet = Image.new("RGB", (FRAMES * cell_w + 10, len(states) * cell_h + 10),
                      (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    total_rle = 0
    for r, st in enumerate(states):
        d.text((6, 4 + r * cell_h), f"{st}", fill=(235, 235, 235))
        for c, img in enumerate(frames[st]):
            bg = Image.new("RGBA", img.size, (58, 70, 104, 255))
            bg.alpha_composite(img, (0, 0))
            sheet.paste(bg.convert("RGB"), (6 + c * cell_w, 4 + r * cell_h + 14))
            total_rle += len(mcstream.rle_encode(to565(img)))
    p = os.path.join(HERE, "anim_preview.png")
    sheet.save(p)
    print(f"预览: {p} ({sheet.width}x{sheet.height})")
    print(f"总 RLE 大小: {total_rle/1024:.0f} KB  (Flash 512KB)")


if __name__ == "__main__":
    import sys
    HERE = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) > 1 and sys.argv[1] == "gen":
        out = os.path.join(HERE, "..", "例程_ST7735", "示例代码", "BSP", "SKIN")
        gen_c(out)
    else:
        main()


