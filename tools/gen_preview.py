#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_preview.py —— 从固件里真实的帧数据生成 README 用的预览图

为什么不重新渲染：预览图要和板子上看到的一致，所以直接从
skin_anim.c（身体层）和 skin_head.c（头部层）解析 RLE 数据，
按固件 blit_head() 同样的叠加算法合成，底板也用屏幕实际背景色。
换皮肤后重跑一遍即可更新：

    python tools/gen_anim_c.py     # 先重新生成帧
    python tools/gen_preview.py    # 再出预览图

输出：
    docs/preview_hero.png    正面 / 转头 / 低头
    docs/preview_states.png  8 个状态
    docs/preview_head.png    左右 13 档 / 俯仰 5 档
"""
import os
import re

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN_DIR = os.path.normpath(os.path.join(HERE, "..", "例程_ST7735", "示例代码", "BSP", "SKIN"))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "docs"))

W, H = 126, 160          # 屏幕（也是帧）尺寸
TRANS = 0xF81F           # 透明色
FRAMES = 8
BG_COLOR = 0x3A2C        # 与 main.c 里的 BG_COLOR 一致

STATE_ORDER = ["IDLE", "WALK", "RUN", "ATTACK", "JUMP", "SNEAK", "SLEEP"]


def rgb565(c):
    return (((c >> 11) & 0x1F) * 255 // 31,
            ((c >> 5) & 0x3F) * 255 // 63,
            (c & 0x1F) * 255 // 31)


def parse_c(path):
    """解析 skin_anim.c / skin_head.c 里的 static const uint8_t xxx[N] = {...}"""
    text = open(path, encoding="utf-8").read()
    blobs = {}
    for m in re.finditer(r"static const uint8_t\s+(\w+)\[(\d+)\]\s*=\s*\{(.*?)\};",
                         text, re.S):
        blobs[m.group(1)] = bytes(int(x, 16)
                                  for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(3)))
    return blobs, text


def parse_tables(c_anim, c_head):
    """取出 g_anim / g_anim_layered / g_head / g_head_off"""
    anim, ta = parse_c(os.path.join(SKIN_DIR, "skin_anim.c"))
    head, th = parse_c(os.path.join(SKIN_DIR, "skin_head.c"))

    body = ta[ta.index("g_anim[ANIM_STATES][ANIM_FRAMES] ="):]
    parts = re.split(r"/\*\s*(\w+)", body)[1:]
    table = {}
    for k in range(0, len(parts), 2):
        table[parts[k]] = [(n, int(c)) for n, c in
                           re.findall(r"\{\s*(anim_\w+)\s*,\s*(\d+)\s*\}", parts[k + 1])]

    layered = [int(x) for x in re.findall(
        r"\d", re.search(r"g_anim_layered\[ANIM_STATES\]\s*=\s*\{([^}]*)\}", ta, re.S).group(1))]

    hbody = th[th.index("g_head[HEAD_YAW_COUNT][HEAD_TILT_COUNT]"):]
    rows = re.split(r"/\*\s*yaw\s*([+-]?\d+)\s*\*/", hbody)[1:]
    htab = {}
    for k in range(0, len(rows), 2):
        htab[int(rows[k])] = {
            int(t): n for n, t in
            re.findall(r"\{\s*(head_\d+_\d+)\s*,\s*\d+\s*\},\s*/\*\s*tilt\s*([+-]?\d+)",
                       rows[k + 1])}

    off_raw = re.search(
        r"g_head_off\[ANIM_STATES\]\[ANIM_FRAMES\]\[2\]\s*=\s*\{(.*)\};", th, re.S).group(1)
    pairs = [(int(a), int(b)) for a, b in
             re.findall(r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}", off_raw)]
    offs = {STATE_ORDER[k]: pairs[k * FRAMES:(k + 1) * FRAMES]
            for k in range(len(STATE_ORDER))}

    return anim, head, table, layered, htab, offs


def rle_decode(rle):
    px = [TRANS] * (W * H)
    n = i = 0
    while i + 2 < len(rle) and n < W * H:
        run = rle[i]
        col = rle[i + 1] | (rle[i + 2] << 8)
        i += 3
        if run == 0:
            break
        for _ in range(run):
            if n >= W * H:
                break
            px[n] = col
            n += 1
    return px


def blit(dst, rle, dx, dy):
    """与固件 bsp_skin.c 的 blit_head() 等价：透明像素跳过"""
    n = sx = sy = i = 0
    while i + 2 < len(rle) and n < W * H:
        run = rle[i]
        col = rle[i + 1] | (rle[i + 2] << 8)
        i += 3
        if run == 0:
            break
        if col == TRANS:
            adv = min(run, W * H - n)
            n += adv
            sy += (sx + adv) // W
            sx = (sx + adv) % W
            continue
        for _ in range(run):
            if n >= W * H:
                break
            X, Y = sx + dx, sy + dy
            if 0 <= X < W and 0 <= Y < H:
                dst[Y * W + X] = col
            n += 1
            sx += 1
            if sx >= W:
                sx = 0
                sy += 1


def render(state, fi, yaw=0, tilt=0, tint=None, data=None):
    anim, head, table, layered, htab, offs = data
    si = STATE_ORDER.index(state)
    px = rle_decode(anim[table[state][fi][0]])
    if layered[si]:
        blit(px, head[htab[yaw][tilt]], *offs[state][fi])
    img = Image.new("RGB", (W, H), rgb565(BG_COLOR))
    d = img.load()
    for y in range(H):
        for x in range(W):
            c = px[y * W + x]
            if c == TRANS:
                continue
            if tint:
                c = tint(c)
            d[x, y] = rgb565(c)
    return img


def tint_hurt(c):
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    r = (r * 2 + 31 * 3) // 5
    g = (g * 2) // 5
    b = (b * 2) // 5
    return (r << 11) | (g << 5) | b


def labelled(img, text, scale=2, pad=18):
    im = img.resize((W * scale, H * scale), Image.NEAREST)
    out = Image.new("RGB", (im.width, im.height + pad), (22, 24, 30))
    out.paste(im, (0, pad))
    ImageDraw.Draw(out).text((4, 3), text, fill=(225, 228, 235))
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    data = parse_tables(None, None)

    # ---------- 主图 ----------
    hero = [("front", render("WALK", 2, data=data)),
            ("yaw +40", render("WALK", 2, yaw=40, data=data)),
            ("tilt -30 (look down)", render("WALK", 2, tilt=-30, data=data))]
    tiles = [labelled(im, txt, scale=3) for txt, im in hero]
    sheet = Image.new("RGB", (len(tiles) * (tiles[0].width + 8) + 8, tiles[0].height + 12),
                      (14, 15, 19))
    for k, t in enumerate(tiles):
        sheet.paste(t, (8 + k * (t.width + 8), 6))
    sheet.save(os.path.join(OUT_DIR, "preview_hero.png"))
    print("docs/preview_hero.png", sheet.size)

    # ---------- 8 个状态（各挑最能体现动作的一帧）+ HURT ----------
    pick = {"IDLE": 0, "WALK": 2, "RUN": 2, "ATTACK": 3,
            "JUMP": 4, "SNEAK": 0, "SLEEP": 0}
    tiles = [labelled(render(st, pick[st], data=data), st) for st in STATE_ORDER]
    tiles.append(labelled(render("IDLE", 0, tint=tint_hurt, data=data), "HURT"))
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    cw, ch = tiles[0].width, tiles[0].height
    sheet = Image.new("RGB", (cols * (cw + 6) + 6, rows * (ch + 6) + 6), (14, 15, 19))
    for k, t in enumerate(tiles):
        sheet.paste(t, (6 + (k % cols) * (cw + 6), 6 + (k // cols) * (ch + 6)))
    sheet.save(os.path.join(OUT_DIR, "preview_states.png"))
    print("docs/preview_states.png", sheet.size)

    # ---------- 头部姿态：两行居中 ----------
    r1 = [labelled(render("IDLE", 0, yaw=y, data=data), "yaw %+d" % y)
          for y in (-60, -40, -20, 0, 20, 40, 60)]
    r2 = [labelled(render("IDLE", 0, tilt=t, data=data), "tilt %+d" % t)
          for t in (-30, -15, 0, 15, 30)]
    w1, h1 = r1[0].width, r1[0].height
    w2, h2 = r2[0].width, r2[0].height
    W1 = len(r1) * (w1 + 6) - 6
    W2 = len(r2) * (w2 + 6) - 6
    WT = max(W1, W2)
    sheet = Image.new("RGB", (WT + 12, h1 + h2 + 18), (14, 15, 19))
    x0 = (WT - W1) // 2
    for k, t in enumerate(r1):
        sheet.paste(t, (6 + x0 + k * (w1 + 6), 6))
    x0 = (WT - W2) // 2
    for k, t in enumerate(r2):
        sheet.paste(t, (6 + x0 + k * (w2 + 6), 6 + h1 + 6))
    sheet.save(os.path.join(OUT_DIR, "preview_head.png"))
    print("docs/preview_head.png", sheet.size)


if __name__ == "__main__":
    main()
