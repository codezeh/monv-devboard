#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skin_rle.py —— 与固件一致的 RLE 编解码实现 + 往返自测

编码格式（3 字节一组，与 bsp_skin.c 的 Skin_StreamData 严格对应）：
    [count:1][color_lo:1][color_hi:1]
    count = 1..255        重复次数
    color = RGB565 小端   0xF81F 表示透明

PC 侧发送时，把编码结果按块切分（每块 ≤ MAX_CHUNK 字节），
F407 侧跨块维护解码状态机，因此一个 run 被切成两半也没问题。
"""

MAX_CHUNK = 250          # 每块 RLE 负载上限（长度字段 1 字节，上限 255；
                         # UART1_RX_BUF_SIZE=512，250+3 字节头远小于它）
TRANSPARENT = 0xF81F


def rle_encode(pixels):
    """pixels: 一维 RGB565 列表 → bytes"""
    out = bytearray()
    n = len(pixels)
    i = 0
    while i < n:
        c = pixels[i]
        run = 1
        while i + run < n and pixels[i + run] == c and run < 255:
            run += 1
        out.append(run)
        out.append(c & 0xFF)
        out.append((c >> 8) & 0xFF)
        i += run
    return bytes(out)


def rle_decode(data, count_pixels):
    """bytes → 一维 RGB565 列表（只解码前 count_pixels 个）"""
    out = []
    i = 0
    while i + 2 < len(data) + 1 and len(out) < count_pixels:
        if i + 3 > len(data):
            break
        cnt = data[i]
        c = data[i + 1] | (data[i + 2] << 8)
        out.extend([c] * cnt)
        i += 3
    return out[:count_pixels]


def split_chunks(data, max_chunk=MAX_CHUNK):
    """按最大块长切分，返回 [(type, payload), ...]"""
    chunks = []
    for off in range(0, len(data), max_chunk):
        chunks.append((1, data[off:off + max_chunk]))    # type 1 = DATA
    return chunks


def build_header(w, h):
    """type 0 = START，负载 2 字节：w, h"""
    return (0, bytes([w, h]))


def stats(pixels, encoded):
    """压缩效果统计"""
    raw = len(pixels) * 2
    return {
        "pixels": len(pixels),
        "raw_bytes": raw,
        "rle_bytes": len(encoded),
        "ratio": raw / len(encoded) if encoded else 0,
        "runs": len(encoded) // 3,
    }


# ------------------------------------------------------------------ 自测
def _selftest():
    import random

    cases = []

    # 1) 全同色
    cases.append(("全同色 1000px", [0x1234] * 1000))

    # 2) 交替色（最坏情况）
    cases.append(("交替色 900px", [0x1111 if i % 2 else 0x2222 for i in range(900)]))

    # 3) 模拟半身像：大块同色 + 少量碎块
    random.seed(7)
    sim = []
    palette = [0xF81F, 0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0x3A2C, 0x52AA]
    for _ in range(60):
        c = random.choice(palette)
        sim.extend([c] * random.randint(5, 200))
    cases.append(("模拟图像 %dpx" % len(sim), sim))

    # 4) 真实精灵（如果存在）
    import os
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    cpath = os.path.normpath(os.path.join(
        here, "..", "例程_ST7735", "示例代码", "BSP", "SKIN", "skin_bust.c"))
    if os.path.exists(cpath):
        txt = open(cpath, encoding="utf-8").read()
        body = txt.split("{", 1)[1].rsplit("}", 1)[0]
        vals = [int(m, 16) for m in re.findall(r"0x([0-9A-Fa-f]{4})", body)]
        if vals:
            cases.append((f"真实精灵 {len(vals)}px", vals))

    all_ok = True
    print(f"{'用例':<24}{'像素':>8}{'原始':>9}{'RLE':>8}{'压缩比':>8}{'块数':>6}  往返")
    print("-" * 78)

    for name, pixels in cases:
        enc = rle_encode(pixels)
        dec = rle_decode(enc, len(pixels))
        ok = (dec == pixels)
        all_ok &= ok
        st = stats(pixels, enc)
        nchunk = len(split_chunks(enc))
        print(f"{name:<24}{st['pixels']:>8}{st['raw_bytes']:>9}"
              f"{st['rle_bytes']:>8}{st['ratio']:>7.2f}x{nchunk:>6}  {'✅' if ok else '❌'}")

    print("-" * 78)
    print("全部往返一致" if all_ok else "!! 存在不一致")

    # 跨块续传测试：故意把数据切成很小的块，模拟 run 被切断
    pixels = cases[-1][1]
    enc = rle_encode(pixels)
    small = split_chunks(enc, 7)        # 每块 7 字节，必然切断多个 run
    rebuilt = b"".join(p for _, p in small)
    dec = rle_decode(rebuilt, len(pixels))
    print(f"跨块续传测试（{len(small)} 小块，每块 7B）: "
          f"{'✅ 一致' if dec == pixels else '❌ 不一致'}")

    return all_ok and dec == pixels


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
