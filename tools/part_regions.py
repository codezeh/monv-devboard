#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
part_regions.py —— 让渲染器输出每个身体部位的屏幕区域
                          用于固件做「局部动画」（手臂摆动、头部倾斜等）

原理：
    渲染时每个盒子的每个面都会投影到屏幕，记录所有部位像素的包围盒，
    就能知道「左臂在精灵图的哪一块」。
    固件按这些区域做独立位移，就能做出手臂摆动而不是整块图片平移。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

import mcskin3d

_LAST_OWNER = [None]   # 最近一次渲染的降采样部位归属图


def render_with_regions(skin, arm_w, out_w, out_h, yaw=24.0, pitch=-10.0,
                        ss=2, dist_k=1.55, use_overlay=True, keep_frac=1.0,
                        crop_content=False):
    """渲染并返回 (图像, 部位区域字典)

    区域格式：{'head': (x0,y0,x1,y1), 'armL': ..., 'armR': ..., 'body': ...}
    坐标是最终图像的像素坐标（inclusive）。
    """
    W, H = out_w * ss, out_h * ss
    boxes = mcskin3d.build_boxes(arm_w)
    uv_table = mcskin3d.build_uv_table(skin)
    overlay_uv = mcskin3d.build_overlay_uv(skin) if use_overlay else {}

    xs = [b[1] for b in boxes] + [b[2] for b in boxes]
    ys = [b[3] for b in boxes] + [b[4] for b in boxes]
    zs = [b[5] for b in boxes] + [b[6] for b in boxes]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0

    R = mcskin3d.rot_matrix(yaw, pitch)
    span = max(max(xs) - min(xs), (max(ys) - min(ys)) * out_w / out_h)
    dist = span * dist_k
    focal = W * dist / (span * 1.28)

    def to_screen(pts):
        p = np.asarray(pts, dtype=np.float64) - np.array([cx, cy, cz])
        pc = p @ R.T
        pc[:, 2] += dist
        z = pc[:, 2]
        z = np.where(np.abs(z) < 1e-6, 1e-6, z)
        sx = W * 0.5 + focal * pc[:, 0] / z
        sy = H * 0.5 + focal * pc[:, 1] / z
        return np.stack([sx, sy], axis=1), z

    tex = np.asarray(skin.convert("RGBA"), dtype=np.float64) / 255.0
    color = np.zeros((H, W, 4), dtype=np.float64)
    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    # 每个像素属于哪个部位（用于统计包围盒）
    owner = np.full((H, W), -1, dtype=np.int8)

    L = np.array((-0.45, -0.6, -0.66))
    L = L / np.linalg.norm(L)
    ambient = 0.42

    # ★ 必须与固件 bsp_skin.h 的 PART_* 完全一致：
    #   PART_BODY=0  PART_HEAD=1  PART_ARML=2  PART_ARMR=3
    part_index = {"body": 0, "head": 1, "armL": 2, "armR": 3}

    def draw_faces(box_list, uvmap, bias):
        for (name, x0, x1, y0, y1, z0, z1) in box_list:
            if name not in uvmap:
                continue
            pidx = part_index.get(name, -1)
            box_c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
            for fname, corners in mcskin3d.box_faces(x0, x1, y0, y1, z0, z1).items():
                if fname not in uvmap[name]:
                    continue
                uvr = uvmap[name][fname]
                if uvr[2] > skin.width or uvr[3] > skin.height:
                    continue

                scr, zc = to_screen(corners)
                c3 = np.array(corners, dtype=np.float64) - np.array([cx, cy, cz])
                c3c = c3 @ R.T
                n = np.cross(c3c[1] - c3c[0], c3c[2] - c3c[0])
                ln = np.linalg.norm(n)
                if ln < 1e-9:
                    continue
                n /= ln
                box_c3 = (box_c - np.array([cx, cy, cz])) @ R.T
                face_c3 = c3c.mean(axis=0)
                if np.dot(n, face_c3 - box_c3) < 0:
                    n = -n

                ndl = float(np.dot(n, L))
                shade = min(1.6, ambient + (1.0 - ambient) * max(0.0, ndl))

                u0, v0, u1, v1 = uvr
                uvs = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]],
                               dtype=np.float64)
                for tri in ((0, 1, 2), (0, 2, 3)):
                    _raster(color, zbuf, owner, scr, zc, uvs, tri, tex,
                            shade, W, H, bias, pidx)

    # 先画身体各部（基础层），再画 overlay
    draw_faces(boxes, uv_table, 0.0)
    if overlay_uv:
        draw_faces(boxes, overlay_uv, -0.35)

    # 先裁掉透明边（与 mcstream.framed_canvas 的 crop_to_content 对应）
    if crop_content:
        alpha = color[:, :, 3]
        rows = np.where(alpha.max(axis=1) > 0)[0]
        cols = np.where(alpha.max(axis=0) > 0)[0]
        if rows.size and cols.size:
            r0, r1 = int(rows[0]), int(rows[-1]) + 1
            c0, c1 = int(cols[0]), int(cols[-1]) + 1
            color = color[r0:r1, c0:c1, :]
            owner = owner[r0:r1, c0:c1]
            H = r1 - r0
            W = c1 - c0

    # 头肩特写裁切：在降采样前对 color 和 owner 同步裁切，保证两者取景一致
    if keep_frac and keep_frac < 1.0:
        keep_h = max(2, int(round(H * keep_frac)))
        color = color[:keep_h, :, :]
        owner = owner[:keep_h, :]
        H = keep_h
        out_h = max(2, int(round(out_h * keep_frac)))
    out_w = W

    img = Image.fromarray(np.clip(color * 255.0, 0, 255).astype(np.uint8), "RGBA")
    if ss != 1:
        img = img.resize((out_w, out_h), Image.BOX)

    # 把 owner 按 ss 降到最终分辨率（每块取块内出现最多的部位）
    if ss != 1:
        oh, ow = H // ss, W // ss
        owner_small = np.zeros((oh, ow), dtype=np.int8)
        for oy in range(oh):
            for ox in range(ow):
                blk = owner[oy*ss:(oy+1)*ss, ox*ss:(ox+1)*ss].ravel()
                blk = blk[blk >= 0]
                if blk.size:
                    vals, cnts = np.unique(blk, return_counts=True)
                    owner_small[oy, ox] = vals[np.argmax(cnts)]
    else:
        owner_small = owner

    # ★ 强制对齐：owner 缩放到与输出图完全相同的尺寸，杜绝任何错位
    if owner_small.shape != (img.size[1], img.size[0]):
        ih, iw = img.size[1], img.size[0]
        oh2, ow2 = owner_small.shape
        fixed = np.zeros((ih, iw), dtype=np.int8)
        for y in range(ih):
            y0 = y * oh2 // ih; y1 = max(y0 + 1, (y + 1) * oh2 // ih)
            for x in range(iw):
                x0 = x * ow2 // iw; x1 = max(x0 + 1, (x + 1) * ow2 // iw)
                blk = owner_small[y0:y1, x0:x1].ravel()
                blk = blk[blk >= 0]
                fixed[y, x] = int(np.bincount(blk).argmax()) if blk.size else -1
        owner_small = fixed

    _LAST_OWNER[0] = owner_small

    # 区域直接在超采样分辨率上统计，再按 ss 缩放到最终坐标
    regions = {}
    for name, pidx in part_index.items():
        mask = (owner == pidx)
        if not mask.any():
            continue
        ys_i, xs_i = np.where(mask)
        regions[name] = (
            int(xs_i.min() // ss), int(ys_i.min() // ss),
            int(xs_i.max() // ss), int(ys_i.max() // ss),
        )
    return img, regions


def _raster(color, zbuf, owner, scr, zc, uvs, tri, tex, shade, W, H,
            z_bias, pidx):
    import math
    i0, i1, i2 = tri
    p0, p1, p2 = scr[i0], scr[i1], scr[i2]
    z0, z1, z2 = zc[i0], zc[i1], zc[i2]
    if z0 <= 0 or z1 <= 0 or z2 <= 0:
        return

    area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
    if abs(area) < 1e-9:
        return

    xmin = max(0, int(math.floor(min(p0[0], p1[0], p2[0]))))
    xmax = min(W - 1, int(math.ceil(max(p0[0], p1[0], p2[0]))))
    ymin = max(0, int(math.floor(min(p0[1], p1[1], p2[1]))))
    ymax = min(H - 1, int(math.ceil(max(p0[1], p1[1], p2[1]))))
    if xmin > xmax or ymin > ymax:
        return

    xs = np.arange(xmin, xmax + 1) + 0.5
    ys = np.arange(ymin, ymax + 1) + 0.5
    X, Y = np.meshgrid(xs, ys)

    w0 = ((p1[0] - X) * (p2[1] - Y) - (p2[0] - X) * (p1[1] - Y)) / area
    w1 = ((p2[0] - X) * (p0[1] - Y) - (p0[0] - X) * (p2[1] - Y)) / area
    w2 = 1.0 - w0 - w1

    mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not mask.any():
        return

    invz = w0 / z0 + w1 / z1 + w2 / z2
    with np.errstate(divide="ignore", invalid="ignore"):
        zz = np.where(np.abs(invz) > 1e-12, 1.0 / invz, np.inf)

    sub_z = zbuf[ymin:ymax + 1, xmin:xmax + 1]
    mask &= (zz + z_bias) < sub_z
    if not mask.any():
        return

    u = (w0 * uvs[i0][0] / z0 + w1 * uvs[i1][0] / z1 + w2 * uvs[i2][0] / z2) * zz
    v = (w0 * uvs[i0][1] / z0 + w1 * uvs[i1][1] / z1 + w2 * uvs[i2][1] / z2) * zz

    tu = np.clip(u.astype(np.int32), 0, tex.shape[1] - 1)
    tv = np.clip(v.astype(np.int32), 0, tex.shape[0] - 1)
    samp = tex[tv, tu]

    a_ok = samp[:, :, 3] >= 0.5
    mask &= a_ok
    if not mask.any():
        return

    sub_z[mask] = zz[mask] + z_bias
    sub_o = owner[ymin:ymax + 1, xmin:xmax + 1]
    sub_o[mask] = pidx
    sub_c = color[ymin:ymax + 1, xmin:xmax + 1]
    rgb = samp[:, :, :3] * shade
    sub_c[:, :, :3] = np.where(mask[:, :, None], rgb, sub_c[:, :, :3])
    sub_c[:, :, 3] = np.where(mask, 255.0, sub_c[:, :, 3])


if __name__ == "__main__":
    skin = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "skin_user.png")).convert("RGBA")
    for aw, tag in ((3, "slim"), (4, "classic")):
        img, reg = render_with_regions(skin, aw, 126, 158, ss=2)
        print(f"=== {tag} {img.size} ===")
        for k, v in reg.items():
            print(f"  {k:6} x={v[0]}~{v[2]}  y={v[1]}~{v[3]}")



def _make_px(final):
    px = []
    pix = final.load()
    for yy in range(final.size[1]):
        for xx in range(final.size[0]):
            r, g, b, a = pix[xx, yy]
            px.append(0xF81F if a < 128 else
                      (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))
    return px


def _partmap_from_silhouette(small, tw, th):
    """从轮廓剖面推出部位归属，每像素只属一个部位（不重叠 → 位移时不开裂）。

    做法（基于实测轮廓）：
      · 逐行求左右边界
      · 头部区间 = 宽度较窄的上半段；一旦行宽明显跳增，就是肩线
      · 肩线以下：落在「头部区间的 x 范围」内 → 身体；落在两侧外扩区 → 手臂
    """
    a = np.array(small.split()[-1])
    opaque = a >= 128
    pm = bytearray((tw * th + 3) // 4)
    if not opaque.any():
        return bytes(pm)

    left = np.full(th, -1); right = np.full(th, -1)
    for y in range(th):
        xs = np.where(opaque[y])[0]
        if xs.size:
            left[y], right[y] = xs[0], xs[-1]

    rows = np.where(left >= 0)[0]
    if rows.size == 0:
        return bytes(pm)
    top, bot = int(rows[0]), int(rows[-1])

    # 头部最宽值（取上 40% 区间的最大宽度作为基准）
    head_end_guess = top + max(1, int((bot - top) * 0.40))
    head_w = max((right[y] - left[y] + 1) for y in range(top, head_end_guess + 1)
                 if left[y] >= 0)

    # 肩线：行宽首次超过 head_w + 6 的那一行
    shoulder = head_end_guess
    for y in range(top, bot + 1):
        if left[y] >= 0 and (right[y] - left[y] + 1) > head_w + 6:
            shoulder = y
            break

    # 躯干 x 范围 = 头部区间的 x 范围（头颅与躯干同宽）
    tl = min((left[y] for y in range(top, shoulder) if left[y] >= 0), default=int(tw*0.2))
    tr = max((right[y] for y in range(top, shoulder) if right[y] >= 0), default=int(tw*0.8))
    # 稍微内收 1px，避免把手臂边缘算进躯干
    body_l, body_r = tl + 1, tr - 1

    for y in range(th):
        for x in range(tw):
            if not opaque[y, x]:
                continue
            if y < shoulder:
                p = 1                                  # 头
            elif x < body_l:
                p = 2                                  # 左臂（观者左侧）
            elif x > body_r:
                p = 3                                  # 右臂
            else:
                p = 0                                  # 身体
            idx = y * tw + x
            pm[idx >> 2] |= ((p & 3) << ((idx & 3) * 2))
    return bytes(pm)


def export_frame(skin_path, preset="hd", arms="slim", yaw=24.0, pitch=-10.0):
    """渲染最终图像 + 由轮廓剖面推出的部位图（保证与图像严格同尺寸、不重叠）"""
    import skin2c
    import mcstream

    skin = Image.open(skin_path).convert("RGBA")
    arm_w = 3 if arms == "slim" else 4
    sc = mcstream.PRESETS[preset]["scale"]
    tw = mcstream.PRESETS[preset]["target_w"]

    # ★ 完全复用 mcstream 的取景，保证与推上去的图一模一样
    canvas = mcstream.framed_canvas(skin, arm_w, yaw, pitch)
    th = max(1, round(tw * canvas.height / canvas.width))
    if th * sc > 160:
        th = 160 // sc
        tw = max(1, round(th * canvas.width / canvas.height))
    if tw * sc > 126:
        tw = 126 // sc
        th = max(1, round(tw * canvas.height / canvas.width))

    small = canvas.resize((tw, th), Image.BOX)
    pm_texel = _partmap_from_silhouette(small, tw, th)

    outlined = skin2c.apply_outline(small)
    final = outlined.resize((tw * sc, th * sc), Image.NEAREST)
    fw, fh = final.size

    # ★ 关键：部位图必须与【最终图像】同分辨率（fw x fh），
    #   因为固件按图像像素坐标查表。之前给的是 texel 尺寸(57x80)，
    #   而图像是 114x160，查表越界 → 全部退化为"身体" → 除染红外看不到动画。
    pm = bytearray((fw * fh + 3) // 4)
    for y in range(fh):
        ty = y * th // fh
        for x in range(fw):
            tx = x * tw // fw
            i = ty * tw + tx
            p_ = (pm_texel[i >> 2] >> ((i & 3) * 2)) & 3
            idx = y * fw + x
            pm[idx >> 2] |= (p_ << ((idx & 3) * 2))
    return fw, fh, px_dummy if False else _make_px(final), bytes(pm), (fw, fh)

    px = []
    pix = final.load()
    for yy in range(fh):
        for xx in range(fw):
            r, g, b, a = pix[xx, yy]
            px.append(0xF81F if a < 128 else
                      (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)))

    return fw, fh, px, partmap, (tw, th)


if __name__ == "__main__":
    import mcstream
    from collections import Counter
    HERE = os.path.dirname(os.path.abspath(__file__))
    sp = os.path.join(HERE, "..", "skin_user.png")

    fw, fh, px, pm, texel = export_frame(sp)
    ref, _a, rtx = mcstream.render_preset(sp, "hd", arms="slim")
    print(f"export: {fw}x{fh} texel={texel}")
    print(f"ref   : {ref.size} texel={rtx}")
    print("✅ 尺寸一致" if (fw, fh) == ref.size else "❌ 不一致")

    tw, th = texel
    c = Counter()
    for i in range(tw * th):
        c[(pm[i >> 2] >> ((i & 3) * 2)) & 3] += 1
    names = {0: "身体", 1: "头", 2: "左臂", 3: "右臂"}
    for k in sorted(c):
        print(f"  {names[k]}: {c[k]} ({c[k]/(tw*th):.0%})")

    COLORS = {0: (90, 90, 100), 1: (255, 90, 90), 2: (90, 255, 140), 3: (255, 220, 80)}
    vis = Image.new("RGB", (tw, th)); v = vis.load()
    for y in range(th):
        for x in range(tw):
            i = y * tw + x
            v[x, y] = COLORS[(pm[i >> 2] >> ((i & 3) * 2)) & 3]
    vis.resize((tw * 4, th * 4), Image.NEAREST).save(os.path.join(HERE, "preview_partmap.png"))
