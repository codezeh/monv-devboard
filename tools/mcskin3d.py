#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcskin3d.py —— 一个极小的软件光栅化器，用真正的透视相机渲染 Minecraft 皮肤

为什么需要它：
    MC 皮肤 PNG 是一个 64x64 的【纹理图集】，里面平铺着头/身/四肢 6 个面的贴图。
    它本身不含任何 3D 信息。你在皮肤查看器里看到的立体效果，
    是软件"搭盒模型 + 投影 + 光栅化"算出来的。

    上一版用的是斜投影（cabinet），没有透视，所以像"贴纸"。
    这里换成正经的：
        · 透视相机（有灭点，近大远小）
        · z-buffer 深度测试（自动遮挡，不用手工排序）
        · 透视校正纹理映射（按 1/z 插值，避免斜面纹理扭）
        · 逐面法线光照（N·L），立体感来自真实明暗而不是假阴影

坐标约定：
    模型空间  X 向右，Y 向下，Z 向前（0=最前面）
    相机     位于 Z 负方向，朝 +Z 看
"""

import math

import numpy as np
from PIL import Image

# ------------------------------------------------------------------ 皮肤图集 UV
# 每项：(u0, v0, u1, v1)
BOX_UV = {
    # 头 8x8x8
    "head": {
        "front": (8, 8, 16, 16), "back": (24, 8, 32, 16),
        "right": (0, 8, 8, 16),  "left": (16, 8, 24, 16),
        "top":   (8, 0, 16, 8),  "bottom": (16, 0, 24, 8),
    },
    # 身体 8x12x4
    "body": {
        "front": (20, 20, 28, 32), "back": (32, 20, 40, 32),
        "right": (16, 20, 20, 32), "left": (28, 20, 32, 32),
        "top":   (20, 16, 28, 20), "bottom": (28, 16, 36, 20),
    },
    # 右臂（角色右手，观者左侧）
    "armR": {
        "front": (44, 20, 48, 32), "back": (52, 20, 56, 32),
        "right": (40, 20, 44, 32), "left": (48, 20, 52, 32),
        "top":   (44, 16, 48, 20), "bottom": (48, 16, 52, 20),
    },
    # 左臂
    "armL": {
        "front": (36, 52, 40, 64), "back": (44, 52, 48, 64),
        "right": (32, 52, 36, 64), "left": (40, 52, 44, 64),
        "top":   (36, 48, 40, 52), "bottom": (40, 48, 44, 52),
    },
}


def build_boxes(arm_w):
    """返回盒列表：每项 (名称, x0,x1, y0,y1, z0,z1)"""
    aw = arm_w
    x_arm_l0, x_arm_l1 = 0, aw
    x_body0,  x_body1  = aw, aw + 8
    x_arm_r0, x_arm_r1 = aw + 8, aw + 8 + aw

    # 头最厚(depth 8)，身体和手臂薄(4)，居中于头的 YZ 轴
    return [
        ("head", x_body0, x_body1, 0,  8,  0, 8),
        ("body", x_body0, x_body1, 8, 20,  2, 6),
        ("armL", x_arm_l0, x_arm_l1, 8, 20, 2, 6),
        ("armR", x_arm_r0, x_arm_r1, 8, 20, 2, 6),
    ]


def box_faces(x0, x1, y0, y1, z0, z1):
    """
    6 个面，每面 4 个角点（模型空间），顺序统一为
    从外侧看该面时的 左上、右上、右下、左下 —— 和纹理 UV 的 TL,TR,BR,BL 一一对应。
    """
    return {
        # 正面：法线 -Z，从 -Z 侧看，右手方向 = +X，向下 = +Y
        "front":  [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
        # 背面：法线 +Z，从 +Z 侧看，右手方向 = -X
        "back":   [(x1, y0, z1), (x0, y0, z1), (x0, y1, z1), (x1, y1, z1)],
        # 左侧面：法线 -X，从 -X 侧看，右手方向 = +Z
        "left":   [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
        # 右侧面：法线 +X，从 +X 侧看，右手方向 = -Z
        "right":  [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)],
        # 顶面：法线 -Y，从上往下看，右手 = +X，向下 = +Z
        "top":    [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        # 底面：法线 +Y，从下往上看，右手 = +X，向下 = -Z
        "bottom": [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)],
    }


def rot_matrix(yaw_deg, pitch_deg):
    """先绕 Y 轴偏航，再绕 X 轴俯仰（Y 轴向下，所以符号要反）"""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)

    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)

    Ry = np.array([[cy, 0, sy],
                   [0,  1, 0],
                   [-sy, 0, cy]], dtype=np.float64)
    Rx = np.array([[1, 0, 0],
                   [0, cp, -sp],
                   [0, sp, cp]], dtype=np.float64)
    return Rx @ Ry


def build_uv_table(skin):
    """按皮肤实际尺寸生成 UV 表，并处理两种特殊皮肤。

    1) 高清皮肤（128x128 / 256x256 / ...）
       MC 的高清皮肤是标准 64x64 布局的**等比放大**，所以坐标统一乘 k = 宽/64。

    2) 老格式 64x32
       没有独立的左臂/左腿贴图（游戏里是镜像右臂），
       这里退化为直接借用右臂贴图 —— 会少了镜像，但好过缺失整条手臂。
    """
    k = max(1, skin.width // 64)

    table = {}
    for part, faces in BOX_UV.items():
        table[part] = {}
        for f, (u0, v0, u1, v1) in faces.items():
            table[part][f] = (u0 * k, v0 * k, u1 * k, v1 * k)

    # 老格式 64x32：左臂/左腿区域不存在（y 从 48 起），借用右侧
    if skin.height * 1.0 < 64 * k * 0.75:
        table["armL"] = dict(table["armR"])

    return table


def render(skin, arm_w, out_w, out_h, yaw=24.0, pitch=-10.0,
           ss=4, light=(-0.45, -0.6, -0.66), ambient=0.42, dist_k=1.55,
           use_overlay=True):
    """
    渲染半身像，返回 RGBA Image（尺寸 out_w x out_h）
      ss       : 超采样倍数（先按 ss 倍渲染再下采样，边缘更干净）
      yaw      : 偏航角，正值让角色转向观者右侧
      pitch    : 俯仰角，负值表示相机在上方俯视
      light    : 光照方向（相机空间）
      ambient  : 环境光，避免暗面全黑
      dist_k   : 相机距离 = span * dist_k。**越大透视越弱、越接近正交**
                 1.5 附近透视很强（头会被放大，因为头比身体更靠近相机）
                 5~10 接近正交投影，比例最准，但仍然有侧脸和明暗
    """
    W, H = out_w * ss, out_h * ss

    uv_table = build_uv_table(skin)
    overlay_uv = build_overlay_uv(skin) if use_overlay else {}
    boxes = build_boxes(arm_w)

    # ---- 模型整体包围盒，用于求中心 ----
    xs = [b[1] for b in boxes] + [b[2] for b in boxes]
    ys = [b[3] for b in boxes] + [b[4] for b in boxes]
    zs = [b[5] for b in boxes] + [b[6] for b in boxes]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0

    R = rot_matrix(yaw, pitch)

    # 相机距离与焦距：让模型刚好填满画面
    span = max(max(xs) - min(xs), (max(ys) - min(ys)) * out_w / out_h)
    dist = span * dist_k
    focal = W * dist / (span * 1.28)

    def to_screen(pts):
        """模型点 → (屏幕x, 屏幕y, 相机z)"""
        p = np.asarray(pts, dtype=np.float64) - np.array([cx, cy, cz])
        pc = p @ R.T
        pc[:, 2] += dist                      # 推到相机前方
        z = pc[:, 2]
        z = np.where(np.abs(z) < 1e-6, 1e-6, z)
        sx = W * 0.5 + focal * pc[:, 0] / z
        sy = H * 0.5 + focal * pc[:, 1] / z
        return np.stack([sx, sy], axis=1), z

    # 纹理像素数组，归一化到 0~1（避免后面重复乘 255）
    tex = np.asarray(skin.convert("RGBA"), dtype=np.float64) / 255.0

    color = np.zeros((H, W, 4), dtype=np.float64)
    zbuf = np.full((H, W), np.inf, dtype=np.float64)

    L = np.array(light, dtype=np.float64)
    L = L / np.linalg.norm(L)

    for (name, x0, x1, y0, y1, z0, z1) in boxes:
        box_c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
        for fname, corners in box_faces(x0, x1, y0, y1, z0, z1).items():
            uvr = uv_table[name][fname]
            if uvr[2] > skin.width or uvr[3] > skin.height:
                continue

            scr, zc = to_screen(corners)

            # 面法线（相机空间），朝外定向
            c3 = np.array(corners, dtype=np.float64) - np.array([cx, cy, cz])
            c3c = c3 @ R.T
            n = np.cross(c3c[1] - c3c[0], c3c[2] - c3c[0])
            ln = np.linalg.norm(n)
            if ln < 1e-9:
                continue
            n /= ln
            # 朝外：法线应背离盒心
            box_c3 = (box_c - np.array([cx, cy, cz])) @ R.T
            face_c3 = c3c.mean(axis=0)
            if np.dot(n, face_c3 - box_c3) < 0:
                n = -n

            ndl = float(np.dot(n, L))
            shade = ambient + (1.0 - ambient) * max(0.0, ndl)
            shade = min(1.6, shade)

            # 纹理四个角（角点顺序 0,1,2,3 对应 uv 的 TL,TR,BR,BL 按面定义）
            u0, v0, u1, v1 = uvr
            uvs = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], dtype=np.float64)

            # 拆成两个三角形
            for tri in ((0, 1, 2), (0, 2, 3)):
                _raster_tri(color, zbuf, scr, zc, uvs, tri, tex, shade, W, H)

    # ---- overlay 层（帽子/外套/袖子）：同一几何，深度略靠前，覆盖基础层 ----
    if use_overlay and overlay_uv:
        OV_BIAS = -0.35        # 负值=更靠近相机
        for (name, x0, x1, y0, y1, z0, z1) in boxes:
            if name not in overlay_uv:
                continue
            box_c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
            for fname, corners in box_faces(x0, x1, y0, y1, z0, z1).items():
                if fname not in overlay_uv[name]:
                    continue
                uvr = overlay_uv[name][fname]
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
                uvs = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], dtype=np.float64)

                for tri in ((0, 1, 2), (0, 2, 3)):
                    _raster_tri(color, zbuf, scr, zc, uvs, tri, tex, shade, W, H,
                                z_bias=OV_BIAS)

    # ---- 下采样（面积平均，抗锯齿） ----
    img = Image.fromarray(np.clip(color * 255.0, 0, 255).astype(np.uint8), "RGBA")
    if ss != 1:
        img = img.resize((out_w, out_h), Image.BOX)
    return img


def _raster_tri(color, zbuf, scr, zc, uvs, tri, tex, shade, W, H, z_bias=0.0):
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

    alpha_ok = samp[:, :, 3] >= 0.5
    mask &= alpha_ok
    if not mask.any():
        return

    sub_z[mask] = zz[mask] + z_bias
    sub_c = color[ymin:ymax + 1, xmin:xmax + 1]
    rgb = samp[:, :, :3] * shade
    sub_c[:, :, :3] = np.where(mask[:, :, None], rgb, sub_c[:, :, :3])
    sub_c[:, :, 3] = np.where(mask, 255.0, sub_c[:, :, 3])


# ------------------------------------------------------------------ overlay 层
# 64x64 皮肤的"帽子/外套/袖子"叠加层。坐标同样是 64 基准，会按皮肤尺寸缩放。
BOX_UV_OVERLAY = {
    "head": {
        "top":    (40, 0, 48, 8),  "bottom": (48, 0, 56, 8),
        "right":  (32, 8, 40, 16), "front":  (40, 8, 48, 16),
        "left":   (48, 8, 56, 16), "back":   (56, 8, 64, 16),
    },
    "body": {
        "top":    (20, 32, 28, 36), "bottom": (28, 32, 36, 36),
        "right":  (16, 36, 20, 48), "front":  (20, 36, 28, 48),
        "left":   (28, 36, 32, 48), "back":   (32, 36, 40, 48),
    },
    "armR": {
        "top":    (44, 32, 48, 36), "bottom": (48, 32, 52, 36),
        "right":  (40, 36, 44, 48), "front":  (44, 36, 48, 48),
        "left":   (48, 36, 52, 48), "back":   (52, 36, 56, 48),
    },
    "armL": {
        "top":    (52, 48, 56, 52), "bottom": (56, 48, 60, 52),
        "right":  (48, 52, 52, 64), "front":  (52, 52, 56, 64),
        "left":   (56, 52, 60, 64), "back":   (60, 52, 64, 64),
    },
}


def build_overlay_uv(skin):
    """生成 overlay 的 UV 表（按皮肤尺寸缩放）；不支持的皮肤返回空表"""
    k = max(1, skin.width // 64)
    if skin.height < 64 * k:          # 老格式没有 overlay
        return {}

    table = {}
    for part, faces in BOX_UV_OVERLAY.items():
        table[part] = {}
        for f, (u0, v0, u1, v1) in faces.items():
            table[part][f] = (u0 * k, v0 * k, u1 * k, v1 * k)

    if skin.height < 64 * k * 0.75:
        table["armL"] = dict(table["armR"])
    return table
