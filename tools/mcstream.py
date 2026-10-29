#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcstream.py —— PC 端渲染 Minecraft 半身像并通过串口推送到 STM32

【为什么渲染放 PC】
    板载 Flash 只有 32KB，存不下高分辨率精灵；
    但 PC 有 CPU 和内存，可以渲染任意 texel 密度。
    固件只负责"接收 → 1:1 显示 → 本地动画"，不做任何 3D 数学。

【三个预设，取景完全一致，只改 texel 密度】
    hd    : 64x80  texel  ×2 = 128x160   像素块 2px（**当前选定**）
    pixel : 32x40 texel  ×4 = 128x160   像素块 4px（更粗的 MC 味，已存档）
    full  : 128x160 texel ×1 = 128x160   1:1 原生（最清晰）

    三者都从同一张高分辨率母图降采样而来，构图/角度/裁切完全一致，
    只有细节量不同 —— 这样才能公平对比。

【渲染 recipe 的教训（别再犯）】
    · 不给精灵强加宽高 —— 会压扁（曾用 25x32，自然比例 25x35，垂直压 9%）
    · 必须超采样（ss>=2）—— ss=1 会让颜色发灰发脏
    · 取景画布比例固定 40:46（验收版用的比例）

【用法】
    python mcstream.py --list                                  # 列串口
    python mcstream.py skin.png -p COM5                        # 默认 pixel 预设
    python mcstream.py skin.png -p COM5 --preset hd            # 高分辨率
    python mcstream.py skin.png -p COM5 --preset full          # 1:1 原生
    python mcstream.py skin.png -o out.bin --preview-only      # 只出预览
"""

import argparse
import os
import sys
import time

try:
    from PIL import Image
except ImportError:
    sys.exit("需要 Pillow：pip install pillow")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcskin3d
import skin2c
from skin_rle import (TRANSPARENT, build_header, rle_encode, split_chunks,
                      stats)

MAX_CHUNK = 150          # 长度字段 1 字节上限 255；UART1_RX_BUF_SIZE=512 足够

# 验收版使用的渲染画布比例（40:46），保证构图不变
CANVAS_ASPECT = 40.0 / 46.0

# 头肩特写：保留上部 40/45（验收版的裁切值）
KEEP_FRAC = 40.0 / 45.0

# 三个预设：texel 尺寸 + 放大倍数
PRESETS = {
    "pixel": dict(target_w=32,  scale=4, outline=True),
    "hd":    dict(target_w=64,  scale=2, outline=True),
    "full":  dict(target_w=128, scale=1, outline=True),
}


# ------------------------------------------------------------------ 渲染
def framed_canvas(skin, aw, yaw, pitch, canvas_w=160):
    """渲染一张高分辨率母图，并统一裁成头肩特写。

    取景与最终 texel 密度无关 —— 三个预设都从这张母图降采样，
    所以构图完全一致。canvas_w=160 时母图约 128x180（裁后约 128x160）。
    """
    canvas_h = int(round(canvas_w / CANVAS_ASPECT))       # 160 -> 184

    # ss=2 超采样：先按 2 倍渲染再下采样，边缘干净不脏
    img = mcskin3d.render(skin, aw, canvas_w, canvas_h,
                          yaw=yaw, pitch=pitch, ss=2)
    img = skin2c.crop_to_content(img)

    # 头肩特写裁切（切在胸口，不切身体中段）
    h = max(2, int(round(img.height * KEEP_FRAC)))
    return img.crop((0, 0, img.width, h))


def render_preset(skin_path, preset="hd", yaw=24.0, pitch=-10.0,
                  arms="auto", outline=None):
    """按预设产出最终屏幕尺寸的图像"""
    cfg = PRESETS[preset]
    tw, sc = cfg["target_w"], cfg["scale"]
    use_outline = cfg["outline"] if outline is None else outline

    skin = Image.open(skin_path).convert("RGBA")
    arm = skin2c.detect_arms(skin) if arms == "auto" else arms
    aw = 3 if arm == "slim" else 4

    canvas = framed_canvas(skin, aw, yaw, pitch)

    # 母图 → 目标 texel 尺寸（等比，BOX 降采样）
    # 若按宽度算出的高度超出屏幕（细胳膊模型更窄，会出现这种），
    # 就改成按高度反推宽度，保证不出屏。
    th = max(1, round(tw * canvas.height / canvas.width))
    if th * sc > 160:
        th = 160 // sc
        tw = max(1, round(th * canvas.width / canvas.height))

    # ⚠️ 宽度必须 <= 126，不能正好 128。
    # 驱动里 LCD_Image 调 setCursor(x, y, x+width, y+height)，
    # 宽度=128 时列地址算出 128，超出 ST7735 的 0~127 范围，
    # 实测会让控制器异常、板子复位（表现为串口回到开机横幅）。
    if tw * sc > 126:
        tw = 126 // sc
        th = max(1, round(tw * canvas.height / canvas.width))

    small = canvas.resize((tw, th), Image.BOX)

    # 在低分辨率上描边（放大后描边也跟着变粗，才有像素感）
    if use_outline:
        small = skin2c.apply_outline(small)

    # NEAREST 放大到屏幕像素
    if sc > 1:
        small = small.resize((tw * sc, th * sc), Image.NEAREST)

    return small, arm, (tw, th)


# ------------------------------------------------------------------ 打包
def to_pixels(img):
    """RGBA Image → RGB565 列表（透明用 0xF81F）"""
    out = []
    pix = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pix[x, y]
            if a < 128:
                out.append(TRANSPARENT)
            else:
                out.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return out


def pack_frame(w, h, pixels, max_chunk=MAX_CHUNK):
    """生成按块切分的字节流：每块 = 'C' + type + len + payload"""
    enc = rle_encode(pixels)
    chunks = ([build_header(w, h)]
              + split_chunks(enc, max_chunk)
              + [(2, b"")])

    out = bytearray()
    for ctype, payload in chunks:
        if len(payload) > 255:
            raise ValueError(f"块负载 {len(payload)} 超过 255")
        out += b"C"
        out.append(ctype)
        out.append(len(payload))
        out += payload
    return bytes(out), enc, len(chunks)



# ------------------------------------------------------------------ 部位图
def pack_parts(pm_bytes, tw, th, max_chunk=MAX_CHUNK):
    """部位图拆成独立帧列表：[(type3, payload), (type4, payload), ...]

    ★ 必须返回帧列表、逐帧发送。若拼成一整串再按字节切片，
      切片会切断帧头，固件收到半截帧(buf[0]!='C')直接丢弃，
      症状就是只看到 PM START、永远没有 PM DONE。
    """
    if tw > 255 or th > 255:
        raise ValueError("部位图尺寸超过 255")
    frames = [(3, bytes([tw, th]))]
    for off in range(0, len(pm_bytes), max_chunk):
        frames.append((4, pm_bytes[off:off + max_chunk]))
    return frames


def send_frames(ser, frames, gap=0.080):
    """逐帧发送，帧间留间隔（固件靠 UART 空闲中断分帧）"""
    for ctype, payload in frames:
        ser.write(b"C" + bytes([ctype, len(payload)]) + payload)
        ser.flush()
        time.sleep(gap)


# ------------------------------------------------------------------ 手臂多帧动画推流
def push_animation(port, baud, skin_path, verbose=True):
    """推底图 + 双臂各 4 帧（方案 B）。

    帧序列：底图(type0/1/2) → 每个手臂帧(type5/6 + type2)
    """
    import arm_frames

    d = arm_frames.export_all(skin_path)
    fw, fh, base_px = d["base"]
    arms = d["arms"]
    texel = d["texel"]

    # 底图帧
    enc = rle_encode(base_px)
    base_frames = ([build_header(fw, fh)]
                   + split_chunks(enc, 150)
                   + [(2, b"")])

    import serial
    with serial.Serial(port, baud, timeout=3) as ser:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.6)
        ser.reset_input_buffer()

        send_frames(ser, base_frames)
        time.sleep(1.2)
        r = ""
        try:
            r = ser.readline().decode("ascii", "replace").strip()
        except Exception:
            pass
        if verbose:
            print(f"→ 底图 {fw}x{fh}（{len(enc)}B）  {r}")

        ok = 0
        for (arm, frame, x, y, w, h, px) in arms:
            if not px or w == 0:
                continue
            e = rle_encode(px)
            frames = ([(5, bytes([arm, frame, x, y, w, h]))]
                      + split_chunks(e, 150)
                      + [(2, b"")])
            send_frames(ser, frames)
            time.sleep(0.35)
            ok += 1
            if verbose:
                print(f"   臂{arm} 帧{frame}: {w}x{h} @({x},{y})  {len(e)}B")
        time.sleep(0.5)

    if verbose:
        print(f"✅ 共推送 {ok} 个手臂帧（texel {texel[0]}x{texel[1]}）")
    return fw, fh


def push_frame_with_parts(port, baud, skin_path, preset="hd", arms="slim",
                          yaw=24.0, pitch=-10.0, verbose=True):
    """推图像 + 逐像素部位图（逐帧发送，与固件分帧严格对应）"""
    import part_regions

    fw, fh, px, pm, texel = part_regions.export_frame(
        skin_path, preset=preset, arms=arms, yaw=yaw, pitch=pitch)

    enc = rle_encode(px)
    img_frames = ([build_header(fw, fh)]
                  + split_chunks(enc, 150)
                  + [(2, b"")])
    pm_frames = pack_parts(pm, texel[0], texel[1])

    import serial
    with serial.Serial(port, baud, timeout=3) as ser:
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.6)
        ser.reset_input_buffer()

        send_frames(ser, img_frames)
        time.sleep(1.2)
        r1 = ""
        try:
            r1 = ser.readline().decode("ascii", "replace").strip()
        except Exception:
            pass

        send_frames(ser, pm_frames)
        time.sleep(1.2)
        r2 = ""
        try:
            r2 = ser.readline().decode("ascii", "replace").strip()
            r3 = ser.readline().decode("ascii", "replace").strip()
            r2 = (r2 + " " + r3).strip()
        except Exception:
            pass

    if verbose:
        print(f"→ 图像 {fw}x{fh}（{len(enc)}B）已推送  {r1}")
        print(f"→ 部位图 {texel[0]}x{texel[1]}（{len(pm)}B）已推送  {r2}")
        if "PM DONE" not in r2:
            print("⚠️ 没看到 PM DONE —— 部位图可能没传完，动画会失效")
    return fw, fh


# ------------------------------------------------------------------ 发送
def auto_port():
    """没指定串口时，自动找可用端口（只有一个就直接用）"""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        sys.exit("需要 pyserial：pip install pyserial")
    ports = [p.device for p in lp.comports()]
    if not ports:
        sys.exit("没找到任何串口。板子插好了吗？驱动装了吗？")
    if len(ports) > 1:
        print(f"→ 检测到多个串口：{', '.join(ports)}，用第一个 {ports[0]}")
        print("   要指定请加 -p COMx")
    return ports[0]


def send_serial(port, baud, data, verbose=True):
    try:
        import serial
    except ImportError:
        sys.exit("需要 pyserial：pip install pyserial")

    with serial.Serial(port, baud, timeout=2) as ser:
        # DTR/RTS 电平变化可能复位板子，关掉
        try:
            ser.dtr = False
            ser.rts = False
        except Exception:
            pass
        time.sleep(0.3)
        ser.reset_input_buffer()

        # ★ 关键：块间隔必须 > 固件主循环周期（Delay_ms(33)）。
        #   固件只有一个单帧接收缓冲，主循环 33ms 才处理一帧；
        #   发得比这快，后一帧会直接覆盖前一帧 → 只有零星块被处理。
        #   实测：6/20/22/50ms 都会丢；60ms 稳定。
        #   代价：45 块约 2.4 秒，可接受（换皮肤不是高频操作）。
        sent = 0
        i = 0
        while i < len(data):
            blk = data[i:i + 153]          # 3 字节头 + 180 负载
            ser.write(blk)
            ser.flush()
            sent += len(blk)
            i += 153
            time.sleep(0.080)              # 60ms 间隔（实测唯一稳定值）

        if verbose:
            print(f"→ 已发送 {sent} 字节到 {port} @ {baud}")
        try:
            resp = ser.readline().decode("ascii", "ignore").strip()
            if resp:
                print(f"← 板子回复：{resp}")
            else:
                print("← 没有回复（检查波特率 / 接线 / 固件是否在跑）")
        except Exception:
            pass


# ------------------------------------------------------------------ main

# ------------------------------------------------------------------ 监视模式
def watch_folder(folder, baud, preset, yaw, pitch, arms, outline,
                 port=None, dry_run=False, once=False):
    """盯着一个文件夹：把皮肤 PNG 丢进去就自动渲染并推给板子。

    规则：
      · 只处理 .png
      · 文件新增或修改时间变化就推送
      · 推过的文件记在内存里，不会重复推
    """
    import time
    try:
        import serial
    except ImportError:
        sys.exit("需要 pyserial：pip install pyserial")

    os.makedirs(folder, exist_ok=True)
    port = port or (None if dry_run else auto_port())

    print("=== 监视模式 ===")
    print("  文件夹 : " + os.path.abspath(folder))
    print("  串口   : %s  @ %d" % (port, baud))
    print("  预设   : " + preset)
    print("  把任意 .png 皮肤丢进这个文件夹，就会自动渲染并推送")
    print("  Ctrl+C 退出")
    print()

    seen = {}
    ser = None
    if not dry_run:
        ser = serial.Serial(port, baud, timeout=2)

    try:
        while True:
            try:
                files = [f for f in os.listdir(folder)
                         if f.lower().endswith(".png")]
            except OSError:
                files = []

            for f in files:
                path = os.path.join(folder, f)
                try:
                    mt = os.path.getmtime(path)
                except OSError:
                    continue
                if seen.get(path) == mt:
                    continue

                print(f"→ 发现 {f}，渲染中...")
                try:
                    img, arm, texel = render_preset(path, preset, yaw, pitch,
                                                    arms, outline)
                    px = to_pixels(img)
                    data, enc, nchunks = pack_frame(img.width, img.height, px)
                    if dry_run:
                        print(f"   [dry-run] 渲染 OK {img.width}x{img.height} "
                              f"({len(data)} B, 手臂 {arm})")
                        seen[path] = mt
                        continue
                    ser.reset_input_buffer()
                    ser.write(data)
                    ser.flush()
                    print(f"   已推送 {img.width}x{img.height} "
                          f"({len(data)} B, 手臂 {arm})")
                    seen[path] = mt
                    try:
                        resp = ser.readline().decode("ascii", "ignore").strip()
                        if resp:
                            print(f"   ← {resp}")
                    except Exception:
                        pass
                except Exception as e:
                    print(f"   !! 渲染失败: {type(e).__name__}: {e}")

            if once:
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("退出监视模式")
    finally:
        if ser:
            ser.close()


def main():
    ap = argparse.ArgumentParser(description="渲染并推送 MC 半身像到 STM32")
    ap.add_argument("skin", nargs="?", help="皮肤 PNG")
    ap.add_argument("-p", "--port", default=None,
                    help="串口，如 COM5；不给则自动检测")
    ap.add_argument("-b", "--baud", type=int, default=921600,
                    help="波特率，默认 921600（不稳就 460800）")
    ap.add_argument("--preset", choices=list(PRESETS), default="hd",
                    help="hd=64x80x2(默认,当前选定) / pixel=32x40x4(像素块更粗) / full=128x160x1(最清晰)")
    ap.add_argument("--yaw", type=float, default=24.0)
    ap.add_argument("--pitch", type=float, default=-10.0)
    ap.add_argument("--arms", choices=["auto", "classic", "slim"], default="auto")
    ap.add_argument("--no-outline", action="store_true", help="关闭描边")
    ap.add_argument("-o", "--out", help="只保存打包结果到文件，不发送")
    ap.add_argument("--list", action="store_true", help="列出可用串口")
    ap.add_argument("--preview-only", action="store_true", help="只出预览图")
    ap.add_argument("--watch", metavar="DIR",
                    help="监视模式：把皮肤 PNG 丢进该文件夹就自动渲染并推送")
    ap.add_argument("--dry-run", action="store_true",
                    help="不推送，只走完渲染流程（无板子时自检用）")
    ap.add_argument("--once", action="store_true",
                    help="配合 --watch：只扫一遍就退出，用于自检")
    args = ap.parse_args()

    if args.list:
        try:
            import serial.tools.list_ports as lp
        except ImportError:
            sys.exit("需要 pyserial：pip install pyserial")
        for p in lp.comports():
            print(f"{p.device}  {p.description}")
        return

    if args.watch:
        watch_folder(args.watch, args.baud, args.preset, args.yaw, args.pitch,
                     args.arms, (False if args.no_outline else None),
                     args.port, args.dry_run, args.once)
        return

    if not args.skin:
        sys.exit("需要皮肤 PNG 路径（或用 --watch DIR 进入监视模式）")

    img, arm, texel = render_preset(
        args.skin, args.preset, args.yaw, args.pitch, args.arms,
        outline=(False if args.no_outline else None))

    fw, fh = img.size
    pixels = to_pixels(img)
    data, enc, nchunks = pack_frame(fw, fh, pixels)
    st = stats(pixels, enc)

    print(f"→ 皮肤 {args.skin}   手臂 {arm}")
    print(f"→ 预设 {args.preset}: texel {texel[0]}x{texel[1]} → 屏幕 {fw}x{fh}")
    print(f"→ yaw={args.yaw} pitch={args.pitch}")
    print(f"→ 像素 {st['pixels']}  原始 {st['raw_bytes']} B  "
          f"RLE {st['rle_bytes']} B  压缩 {st['ratio']:.2f}x")
    print(f"→ 共 {nchunks} 块，打包后 {len(data)} B")

    for baud in (921600, 460800, 115200):
        print(f"   @{baud:>7} 约 {len(data) * 10 / baud * 1000:6.1f} ms")

    if fw > 128 or fh > 160:
        print(f"⚠️  输出 {fw}x{fh} 超过屏幕 128x160")

    outdir = os.path.dirname(os.path.abspath(__file__))
    pv = os.path.join(outdir, f"preview_{args.preset}_{fw}x{fh}.png")
    big = img.resize((fw * 2, fh * 2), Image.NEAREST)
    bg = Image.new("RGBA", big.size, (58, 70, 104, 255))
    bg.alpha_composite(big)
    bg.convert("RGB").save(pv)
    print(f"→ 预览 {pv}")

    if args.preview_only:
        return

    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"→ 已保存 {args.out}")
        return

    port = args.port or auto_port()
    send_serial(port, args.baud, data)


if __name__ == "__main__":
    main()
