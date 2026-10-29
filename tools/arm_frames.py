#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arm_frames.py —— 只渲染手臂，并让它【真正绕肩关节旋转】生成多帧

为什么需要这个：
    之前所有动作都是把 2D 图按像素块平移，做不出"手臂划过胸前"。
    MC 原版手臂是绕肩关节旋转的（BipedEntityModel.setupAttackAnimation）。
    这里用 PC 的 3D 渲染器，把手臂按不同角度旋转后渲染成 8 帧，
    固件只负责按状态选帧贴图 → 真正的手臂动画。

输出：
    base   : 底图（头+身，手臂区域留空）
    armL/armR : 各 8 帧，每帧带锚点 (x,y) 和 texel 尺寸
    预览图 tools/preview_arms.png
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math

import numpy as np
from PIL import Image

import mcskin3d

# 8 帧的手臂旋转角度（度，绕肩关节 X 轴）
#   负值 = 向前抬（朝观者方向）
ARM_ANGLES = [-70, -40, 0, 55]   # 0=across chest 1=raised 2=neutral 3=hanging back

# ★ 与 mcstream.framed_canvas 完全一致：canvas 160x184，内部超采样 ss=2
CANVAS_W, CANVAS_H = 160, 184
SS = 2
TW, TH = 57, 80
SCALE = 2


def _rot_x(p, pivot, deg):
    """把点绕 pivot 在 X 轴旋转 deg 度"""
    if deg == 0:
        return p
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    q = p - pivot
    y = q[..., 1] * c - q[..., 2] * s
    z = q[..., 1] * s + q[..., 2] * c
    return np.stack([q[..., 0], y, z], axis=-1) + pivot


def render_parts(skin, arm_w, yaw=24.0, pitch=-10.0, keep_frac=0.80,
                 want="all", arm_angle=0.0, arm_side="R"):
    """渲染指定部位。want: 'base'(头+身) / 'arm'(单臂) / 'all'

    返回 (RGBA Image, dict of part->bbox)  尺寸 TEX_W*SS x TEX_H*SS
    """
    out_w, out_h = CANVAS_W, CANVAS_H
    W, H = out_w * SS, out_h * SS

    boxes = mcskin3d.build_boxes(arm_w)
    uv = mcskin3d.build_uv_table(skin)
    ov = mcskin3d.build_overlay_uv(skin)

    xs = [b[1] for b in boxes] + [b[2] for b in boxes]
    ys = [b[3] for b in boxes] + [b[4] for b in boxes]
    zs = [b[5] for b in boxes] + [b[6] for b in boxes]
    cx, cy, cz = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2

    R = mcskin3d.rot_matrix(yaw, pitch)
    span = max(max(xs)-min(xs), (max(ys)-min(ys)) * out_w / out_h)
    dist = span * 1.55
    focal = W * dist / (span * 1.28)

    def project(pts):
        p = pts - np.array([cx, cy, cz])
        pc = p @ R.T
        pc[:, 2] += dist
        z = np.maximum(pc[:, 2], 1e-6)
        sx = W * 0.5 + focal * pc[:, 0] / z
        sy = H * 0.5 + focal * pc[:, 1] / z
        return np.stack([sx, sy], axis=1), z

    tex = np.asarray(skin.convert("RGBA"), dtype=np.float64) / 255.0
    color = np.zeros((H, W, 4))
    zbuf = np.full((H, W), np.inf)

    L = np.array((-0.45, -0.6, -0.66)); L /= np.linalg.norm(L)

    def draw(part_name, angle):
        for (name, x0, x1, y0, y1, z0, z1) in boxes:
            if name != part_name:
                continue
            # 肩关节枢轴：手臂顶面中心
            # ★ 肩关节枢轴：官方 glTF 中 Right_Arm T=0.3125(=5/16)、身体半宽 4/16，
            #   即枢轴在【身体边缘外 1 单位 = 手臂内缘内侧 1 单位】。
            #   之前用臂盒中心 ((x0+x1)/2) 偏了半个臂宽，旋转会歪。
            if name == "armR":
                px_ = x0 + 1          # 内缘(11) + 1 = 12
            elif name == "armL":
                px_ = x1 - 1          # 内缘(3) - 1 = 2
            else:
                px_ = (x0 + x1) / 2.0
            pivot = np.array([px_, y0, (z0+z1)/2.0])
            for fname, corners in mcskin3d.box_faces(x0, x1, y0, y1, z0, z1).items():
                uvr = uv[name][fname]
                if uvr[2] > skin.width or uvr[3] > skin.height:
                    continue
                c = np.array(corners, dtype=np.float64)
                if angle:
                    c = _rot_x(c, pivot, angle)
                scr, zc = project(c)
                n = np.cross(c[1]-c[0], c[2]-c[0])
                ln = np.linalg.norm(n)
                if ln < 1e-9:
                    continue
                n /= ln
                ndl = float(np.dot(n, L))
                shade = min(1.6, 0.42 + 0.58 * max(0.0, ndl))
                u0, v0, u1, v1 = uvr
                uvs = np.array([[u0,v0],[u1,v0],[u1,v1],[u0,v1]], dtype=np.float64)
                for tri in ((0,1,2),(0,2,3)):
                    _raster(color, zbuf, scr, zc, uvs, tri, tex, shade, W, H)

    if want in ("base", "all"):
        for nm in ("head", "body"):
            draw(nm, 0.0)
    if want in ("arm", "all"):
        draw("armR" if arm_side == "R" else "armL", arm_angle)

    img = Image.fromarray(np.clip(color*255, 0, 255).astype(np.uint8), "RGBA")
    # ★ 不裁剪！所有帧必须共用同一画布，否则贴图对不上。
    #   只把不透明区域作为 bbox 返回，供固件做锚点/裁剪优化。
    bbox = img.getbbox()
    return img, bbox


def _raster(color, zbuf, scr, zc, uvs, tri, tex, shade, W, H):
    i0, i1, i2 = tri
    p0, p1, p2 = scr[i0], scr[i1], scr[i2]
    z0, z1, z2 = zc[i0], zc[i1], zc[i2]
    if z0 <= 0 or z1 <= 0 or z2 <= 0:
        return
    area = (p1[0]-p0[0])*(p2[1]-p0[1]) - (p2[0]-p0[0])*(p1[1]-p0[1])
    if abs(area) < 1e-9:
        return
    xmin = max(0, int(math.floor(min(p0[0], p1[0], p2[0]))))
    xmax = min(W-1, int(math.ceil(max(p0[0], p1[0], p2[0]))))
    ymin = max(0, int(math.floor(min(p0[1], p1[1], p2[1]))))
    ymax = min(H-1, int(math.ceil(max(p0[1], p1[1], p2[1]))))
    if xmin > xmax or ymin > ymax:
        return
    X, Y = np.meshgrid(np.arange(xmin, xmax+1)+0.5, np.arange(ymin, ymax+1)+0.5)
    w0 = ((p1[0]-X)*(p2[1]-Y) - (p2[0]-X)*(p1[1]-Y)) / area
    w1 = ((p2[0]-X)*(p0[1]-Y) - (p0[0]-X)*(p2[1]-Y)) / area
    w2 = 1.0 - w0 - w1
    m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not m.any():
        return
    invz = w0/z0 + w1/z1 + w2/z2
    with np.errstate(divide="ignore", invalid="ignore"):
        zz = np.where(np.abs(invz) > 1e-12, 1.0/invz, np.inf)
    subz = zbuf[ymin:ymax+1, xmin:xmax+1]
    m &= zz < subz
    if not m.any():
        return
    u = (w0*uvs[i0][0]/z0 + w1*uvs[i1][0]/z1 + w2*uvs[i2][0]/z2) * zz
    v = (w0*uvs[i0][1]/z0 + w1*uvs[i1][1]/z1 + w2*uvs[i2][1]/z2) * zz
    tu = np.clip(u.astype(np.int32), 0, tex.shape[1]-1)
    tv = np.clip(v.astype(np.int32), 0, tex.shape[0]-1)
    samp = tex[tv, tu]
    m &= samp[:, :, 3] >= 0.5
    if not m.any():
        return
    subz[m] = zz[m]
    sub = color[ymin:ymax+1, xmin:xmax+1]
    rgb = samp[:, :, :3] * shade
    sub[:, :, :3] = np.where(m[:, :, None], rgb, sub[:, :, :3])
    sub[:, :, 3] = np.where(m, 255.0, sub[:, :, 3])


def main():
    HERE = os.path.dirname(os.path.abspath(__file__))
    sp = os.path.join(HERE, "..", "skin_user.png")
    skin = Image.open(sp).convert("RGBA")

    base, base_bb = render_parts(skin, 3, want="base")
    print("底图(头+身):", base.size, "内容bbox:", base_bb)

    frames = []
    for i, ang in enumerate(ARM_ANGLES):
        im, bb = render_parts(skin, 3, want="arm", arm_angle=ang, arm_side="R")
        frames.append((ang, im, bb))
        print(f"  帧{i}: {ang:+4d}°  画布{im.size}  臂bbox={bb}")

    # 预览：底图 + 各帧叠加
    Z = 3
    cols = 4
    rows = 2
    cw = base.width * Z + 20
    ch = base.height * Z + 24
    sheet = Image.new("RGB", (cols*cw+10, rows*ch+10), (18,18,22))
    from PIL import ImageDraw
    d = ImageDraw.Draw(sheet)
    for i, (ang, fr, bb) in enumerate(frames):
        cx = 10 + (i % cols) * cw
        cy = 10 + (i // cols) * ch
        d.text((cx, cy), f"frame {i}  {ang:+d}deg", fill=(230,230,230))
        canvas = Image.new("RGBA", base.size, (58,70,104,255))
        canvas.alpha_composite(base, (0,0))
        canvas.alpha_composite(fr, (0,0))
        sheet.paste(canvas.convert("RGB").resize(
            (base.width*Z, base.height*Z), Image.NEAREST), (cx, cy+14))
    out = os.path.join(HERE, "preview_arms.png")
    sheet.save(out)
    print("预览:", out, sheet.size)




# ============================================================
#  风格一致的合成：完全套用 mcstream 的流水线
#    crop_to_content → keep_frac(0.8) → resize(57x80) → 描边 → NEAREST x2
# ============================================================
def _fixed_crop_box(skin, aw):
    """固定裁切框：把**所有手臂角度**的并集都算进去，避免前抬时被裁掉。

    之前只用中立姿态算，结果手臂前抬时伸出画布左缘被切断（bbox x=0）。
    """
    import mcstream
    base, _ = render_parts(skin, aw, want="base")
    allb = [base.getbbox()]

    for ang in ARM_ANGLES:
        for side in ("L", "R"):
            im, _ = render_parts(skin, aw, want="arm", arm_angle=ang, arm_side=side)
            bb = im.getbbox()
            if bb:
                allb.append(bb)

    allb = [b for b in allb if b]
    x0 = min(b[0] for b in allb)
    y0 = min(b[1] for b in allb)
    x1 = max(b[2] for b in allb)
    y1 = max(b[3] for b in allb)

    # 头肩特写：保留上部 KEEP_FRAC（以底图高度为基准，避免手臂抬高后过头）
    bh = base.getbbox()
    base_top = bh[1] if bh else y0
    base_h = (bh[3] - bh[1]) if bh else (y1 - y0)
    keep_bottom = base_top + max(2, int(round(base_h * mcstream.KEEP_FRAC)))
    y1 = min(y1, keep_bottom)
    return (x0, y0, x1, y1)


def build_style(arm_angle_r=0.0, arm_angle_l=None, outline=True, crop_box=None):
    """合成一张最终风格图（底图 + 双臂帧），所有帧共用同一裁切框"""
    import skin2c
    import mcstream

    HERE = os.path.dirname(os.path.abspath(__file__))
    skin = Image.open(os.path.join(HERE, "..", "skin_user.png")).convert("RGBA")
    aw = 3

    if crop_box is None:
        crop_box = _fixed_crop_box(skin, aw)

    base, _ = render_parts(skin, aw, want="base")
    armR, _ = render_parts(skin, aw, want="arm", arm_angle=arm_angle_r, arm_side="R")
    al = arm_angle_r if arm_angle_l is None else arm_angle_l
    armL, _ = render_parts(skin, aw, want="arm", arm_angle=al, arm_side="L")

    comp = base.copy()
    comp.alpha_composite(armL, (0, 0))
    comp.alpha_composite(armR, (0, 0))

    # ★ 固定裁切框（所有帧完全一致）
    comp = comp.crop(crop_box)

    tw = mcstream.PRESETS["hd"]["target_w"]
    sc = mcstream.PRESETS["hd"]["scale"]
    th = max(1, round(tw * comp.height / comp.width))
    # ★ 硬约束：必须放进 126x160（留 1px 防 ST7735 列地址越界）
    if th * sc > 160:
        th = 160 // sc
        tw = max(1, round(th * comp.width / comp.height))
    if tw * sc > 126:
        tw = 126 // sc
        th = max(1, round(tw * comp.height / comp.width))
    small = comp.resize((tw, th), Image.BOX)
    if outline:
        small = skin2c.apply_outline(small)
    final = small.resize((tw * sc, th * sc), Image.NEAREST)
    return final, (tw, th)


def style_preview():
    """三种状态对比，确认风格是否与之前一致"""
    from PIL import ImageDraw
    shots = [("IDLE (arm down)", 55.0), ("WALK (arm mid)", 5.0), ("ATTACK (arm across)", -70.0)]
    HERE = os.path.dirname(os.path.abspath(__file__))
    skin = Image.open(os.path.join(HERE, "..", "skin_user.png")).convert("RGBA")
    cb = _fixed_crop_box(skin, 3)
    print("固定裁切框:", cb)
    out = []
    for name, ang in shots:
        img, tx = build_style(ang, ang, crop_box=cb)
        out.append((name, img, tx))
        print(f"  {name}: {img.size} texel={tx}")

    Z = 1
    PAD, LAB = 10, 16
    w = max(i.width for _, i, _ in out)
    h = max(i.height for _, i, _ in out)
    sheet = Image.new("RGB", (len(out)*(w+PAD)+PAD, h+2*PAD+LAB), (18,18,22))
    d = ImageDraw.Draw(sheet)
    for i, (n, img, tx) in enumerate(out):
        cx = PAD + i*(w+PAD)
        d.text((cx, PAD), f"{n}  {img.size}", fill=(235,235,235))
        bgc = Image.new("RGBA", img.size, (58,70,104,255))
        bgc.alpha_composite(img, (0,0))
        sheet.paste(bgc.convert("RGB"), (cx, PAD+LAB))
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview_style.png")
    sheet.save(p)
    print("预览:", p, sheet.size)


if __name__ == "__main__":
    pass

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "style":
        style_preview()
    else:
        main()


# ============================================================
#  导出：底图 + 双臂各 4 帧（含锚点），供 mcstream 推流
# ============================================================
def export_all(skin_path=None):
    """返回 dict:
       base : (w,h,rgb565_list)
       arms : [(arm, frame, x, y, w, h, rgb565_list), ...]
    """
    import skin2c
    import mcstream

    HERE = os.path.dirname(os.path.abspath(__file__))
    if skin_path is None:
        skin_path = os.path.join(HERE, "..", "skin_user.png")
    skin = Image.open(skin_path).convert("RGBA")
    aw = 3

    cb = _fixed_crop_box(skin, aw)

    # ---- 底图：只渲染 head+body（手臂区域天然透明）----
    base_img, _ = render_parts(skin, aw, want="base")
    base_img = base_img.crop(cb)

    tw = mcstream.PRESETS["hd"]["target_w"]
    sc = mcstream.PRESETS["hd"]["scale"]
    th = max(1, round(tw * base_img.height / base_img.width))
    if th * sc > 160:
        th = 160 // sc
        tw = max(1, round(th * base_img.width / base_img.height))
    if tw * sc > 126:
        tw = 126 // sc
        th = max(1, round(tw * base_img.height / base_img.width))

    base_small = base_img.resize((tw, th), Image.BOX)
    base_out = skin2c.apply_outline(base_small)
    final = base_out.resize((tw * sc, th * sc), Image.NEAREST)
    fw, fh = final.size

    base_px = []
    pix = final.load()
    for y in range(fh):
        for x in range(fw):
            r, g, b, a = pix[x, y]
            base_px.append(0xF81F if a < 128 else
                           (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))

    # ---- 手臂帧：同一裁切框 + 同一缩放，然后只取手臂的 bbox ----
    arms = []
    for arm_id, side in ((0, "L"), (1, "R")):
        for fi, ang in enumerate(ARM_ANGLES):
            im, bb = render_parts(skin, aw, want="arm", arm_angle=ang, arm_side=side)
            im = im.crop(cb)
            small = im.resize((tw, th), Image.BOX)
            # 放大到屏幕分辨率（与底图同一尺度）
            big = small.resize((tw * sc, th * sc), Image.NEAREST)
            bb2 = big.getbbox()
            if not bb2:
                arms.append((arm_id, fi, 0, 0, 0, 0, []))
                continue
            x0, y0, x1, y1 = bb2
            crop = big.crop((x0, y0, x1, y1))
            # 缩回 texel 分辨率存储（固件绘制时 x2）
            tex = crop.resize((max(1, (x1-x0)//sc), max(1, (y1-y0)//sc)), Image.BOX)

            px = []
            tp = tex.load()
            for yy in range(tex.height):
                for xx in range(tex.width):
                    r, g, b, a = tp[xx, yy]
                    px.append(0xF81F if a < 128 else
                              (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
            arms.append((arm_id, fi, x0, y0, tex.width, tex.height, px))

    return {"base": (fw, fh, base_px),
            "arms": arms,
            "texel": (tw, th)}
