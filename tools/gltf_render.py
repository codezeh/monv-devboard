#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gltf_render.py —— 用 Axolotl 自带的 glTF 玩家模型渲染皮肤

不自己搭盒子模型，而是直接读 Axolotl 的 classic-player.gltf / slim-player.gltf：
  · 顶点 / 法线 / UV / 索引 全部来自官方模型
  · 骨骼是纯节点层级（skins=0），每部位一个节点挂一个 mesh
  · 贴图直接套玩家皮肤

用法（渲染一个姿态并存图）：
    python gltf_render.py
"""
import base64
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image

MODEL_DIR = r"D:\axolotl\packages\assets\models"


# ==============================================================
#  glTF 解析
# ==============================================================
class GltfModel:
    def __init__(self, path):
        self.dir = os.path.dirname(path)
        with open(path, encoding="utf-8") as f:
            self.g = json.load(f)
        self._bin = self._load_buffer(0)

    def _load_buffer(self, idx):
        b = self.g["buffers"][idx]
        uri = b["uri"]
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        with open(os.path.join(self.dir, uri), "rb") as f:
            return f.read()

    def accessor(self, idx):
        """返回 numpy 数组（float32 或 uint）"""
        acc = self.g["accessors"][idx]
        n = acc["count"]
        ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
        ctype = acc["componentType"]
        dtype = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
                 5123: np.uint16, 5125: np.uint32, 5126: np.float32}[ctype]

        if "bufferView" not in acc:
            return np.zeros((n, ncomp) if ncomp > 1 else n, dtype=dtype)

        bv = self.g["bufferViews"][acc["bufferView"]]
        off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = bv.get("byteStride", 0) or (ncomp * np.dtype(dtype).itemsize)

        out = np.empty((n, ncomp), dtype=dtype)
        for i in range(n):
            out[i] = np.frombuffer(self._bin, dtype=dtype,
                                   count=ncomp, offset=off + i * stride)
        return out if ncomp > 1 else out.reshape(-1)

    def node_world(self, i, parent=np.eye(4)):
        """递归计算每个节点的世界矩阵（含 pose 覆盖）"""
        nd = self.g["nodes"][i]
        local = self._local_matrix(nd)

        # ★ pose 覆盖：支持
        #     float          -> 绕 X 轴旋转(度)
        #     {'rx':度,'ry':度,'ty':位移,'tz':位移}
        pname = nd.get("name", "")
        if pname in self._pose:
            pv = self._pose[pname]
            if isinstance(pv, (int, float)):
                pv = {"rx": float(pv)}
            rx = math.radians(pv.get("rx", 0.0))
            ry = math.radians(pv.get("ry", 0.0))
            ty = pv.get("ty", 0.0)
            tz = pv.get("tz", 0.0)

            Rx = np.array([[1, 0, 0, 0],
                           [0, math.cos(rx), -math.sin(rx), 0],
                           [0, math.sin(rx), math.cos(rx), 0],
                           [0, 0, 0, 1]], dtype=np.float64)
            Ry = np.array([[math.cos(ry), 0, math.sin(ry), 0],
                           [0, 1, 0, 0],
                           [-math.sin(ry), 0, math.cos(ry), 0],
                           [0, 0, 0, 1]], dtype=np.float64)
            T = np.eye(4); T[:3, 3] = local[:3, 3]
            RS = local.copy(); RS[:3, 3] = 0
            local = T @ Ry @ Rx @ RS
            # 平移叠加（模型空间）
            local[:3, 3] += np.array([0.0, ty, tz])

        M = parent @ local
        self._world[i] = M
        for c in nd.get("children", []):
            self.node_world(c, M)

    @staticmethod
    def _local_matrix(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
        t = np.array(nd.get("translation", [0, 0, 0]), dtype=np.float64)
        r = np.array(nd.get("rotation", [0, 0, 0, 1]), dtype=np.float64)  # x,y,z,w
        s = np.array(nd.get("scale", [1, 1, 1]), dtype=np.float64)

        x, y, z, w = r
        R = np.array([
            [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w),   0],
            [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w),   0],
            [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y), 0],
            [0, 0, 0, 1],
        ], dtype=np.float64)
        T = np.eye(4); T[:3, 3] = t
        S = np.eye(4); S[0, 0], S[1, 1], S[2, 2] = s
        return T @ R @ S

    def build(self, pose=None):
        """pose: {节点名: 绕 X 轴旋转角度(度)}，用于摆姿势/做动画"""
        self._pose = pose or {}
        self._world = [np.eye(4)] * len(self.g["nodes"])
        scene = self.g["scenes"][self.g.get("scene", 0)]
        for root in scene["nodes"]:
            self.node_world(root)
        return self

    def parts(self):
        """返回 [(node_name, mesh_prim, world_matrix), ...]"""
        out = []
        for i, nd in enumerate(self.g["nodes"]):
            if "mesh" not in nd:
                continue
            mi = nd["mesh"]
            prim = self.g["meshes"][mi]["primitives"][0]
            out.append((nd.get("name", f"node{i}"), prim, self._world[i],
                        self.g["nodes"][i].get("name", "")))
        return out

    def load_texture(self, mat_idx):
        mat = self.g["materials"][mat_idx]
        pbr = mat.get("pbrMetallicRoughness", {})
        tex = pbr.get("baseColorTexture")
        if tex is None:
            return None
        img_i = self.g["textures"][tex["index"]]["source"]
        img = self.g["images"][img_i]
        uri = img.get("uri", "")
        if uri.startswith("data:"):
            raw = base64.b64decode(uri.split(",", 1)[1])
            from io import BytesIO
            return Image.open(BytesIO(raw)).convert("RGBA")
        return Image.open(os.path.join(self.dir, uri)).convert("RGBA")


# ==============================================================
#  渲染
# ==============================================================
def render(model, skin_img, out_w, out_h, yaw=160.0, pitch=-6.0,
           zoom=1.0, center_y=0.35, frame_below=0.60,
           skip=None, only=None):
    """
    skin_img: 64x64 或 64x32 皮肤（RGBA）
    返回 RGBA Image

    skip / only：要【跳过绘制】/【只绘制】的部位名集合（None = 不限制）。
    ★ 注意：取景（包围盒）始终按"全部部位"算，否则单画头时相机会怼到头上。
      做"头/身分层"时靠这个保证两层坐标完全对齐。
    """
    W, H = out_w, out_h
    color = np.zeros((H, W, 4), dtype=np.float64)
    zbuf = np.full((H, W), np.inf)

    # 相机：绕 Y 轴 yaw，再绕 X 轴 pitch
    ya, pa = math.radians(yaw), math.radians(pitch)
    Ry = np.array([[math.cos(ya), 0, math.sin(ya), 0],
                   [0, 1, 0, 0],
                   [-math.sin(ya), 0, math.cos(ya), 0],
                   [0, 0, 0, 1]], dtype=np.float64)
    Rx = np.array([[1, 0, 0, 0],
                   [0, math.cos(pa), -math.sin(pa), 0],
                   [0, math.sin(pa), math.cos(pa), 0],
                   [0, 0, 0, 1]], dtype=np.float64)
    R = Rx @ Ry

    # ---- 用模型真实包围盒自动取景 ----
    lo = np.array([1e9, 1e9, 1e9]); hi = -lo.copy()
    for (name, prim, world, nname) in model.parts():
        p_ = model.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
        v4 = np.hstack([p_, np.ones((p_.shape[0], 1))])
        wp = (world @ v4.T).T[:, :3]
        lo = np.minimum(lo, wp.min(axis=0))
        hi = np.maximum(hi, wp.max(axis=0))
    mid = (lo + hi) / 2.0
    size = hi - lo
    model_h = float(size[1])

    # 头肩特写：从头顶往下取 frame_below 比例
    top = hi[1]
    bottom = hi[1] - model_h * frame_below
    view_h = top - bottom
    aspect = W / float(H)
    view_w = view_h * aspect

    # 水平方向：按模型实际宽度取，保证人不被裁
    view_cx = float(mid[0])
    # 垂直：顶部留 6% 空隙
    view_cy = float(top - view_h * 0.5 + view_h * 0.06)

    # ★ 透视相机：焦距由「视野高度」直接决定，不能再和 cam_dist 互相依赖
    #   焦距 = 图像高度 / (2*tan(fov/2))，fov=30°
    fov = math.radians(30.0)
    focal = (H * 0.5) / math.tan(fov * 0.5) / zoom
    cam_dist = 6.0                     # 足够远，近似正交，减少透视畸变
    # 让 view_h 正好铺满画面高度
    focal = focal * (H / view_h) * (view_h / (2 * cam_dist * math.tan(fov * 0.5)))
    focal = (H / view_h) * cam_dist * math.tan(fov * 0.5) / math.tan(fov * 0.5)
    focal = cam_dist * (H / view_h)

    L = np.array([-0.4, -0.5, -0.75]); L /= np.linalg.norm(L)
    ambient = 0.72

    tex = np.asarray(skin_img.convert("RGBA"), dtype=np.float64) / 255.0
    th, tw = tex.shape[0], tex.shape[1]

    _dbg = {"tri": 0, "drawn": 0, "shade_min": 9e9, "shade_max": -9e9, "samp_max": 0.0}
    for (name, prim, world, nname) in model.parts():
        if skip is not None and name in skip:
            continue
        if only is not None and name not in only:
            continue
        pos = model.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
        nrm = model.accessor(prim["attributes"]["NORMAL"]).astype(np.float64)
        uv = model.accessor(prim["attributes"]["TEXCOORD_0"]).astype(np.float64)
        idx = model.accessor(prim["indices"]).astype(np.int32).reshape(-1)

        # 顶点 → 世界
        v4 = np.hstack([pos, np.ones((pos.shape[0], 1))])
        wpos = (world @ v4.T).T[:, :3]
        wn = (world[:3, :3] @ nrm.T).T

        # 世界 → 相机
        cpos = (R @ np.hstack([wpos, np.ones((wpos.shape[0], 1))]).T).T[:, :3]
        cn = (R[:3, :3] @ wn.T).T
        # 整体下移，让模型居中
        cpos[:, 0] -= view_cx
        cpos[:, 1] -= view_cy

        # 投影
        z = cpos[:, 2] + cam_dist
        z = np.where(np.abs(z) < 1e-6, 1e-6, z)
        sx = W * 0.5 + focal * cpos[:, 0] / z
        sy = H * 0.5 - focal * cpos[:, 1] / z     # 屏幕 y 向下

        for t in range(0, len(idx), 3):
            i0, i1, i2 = idx[t], idx[t + 1], idx[t + 2]
            if z[i0] <= 0 or z[i1] <= 0 or z[i2] <= 0:
                continue
            p0 = (sx[i0], sy[i0]); p1 = (sx[i1], sy[i1]); p2 = (sx[i2], sy[i2])
            area = (p1[0]-p0[0])*(p2[1]-p0[1]) - (p2[0]-p0[0])*(p1[1]-p0[1])
            if abs(area) < 1e-9:
                continue
            # 背面剔除
            nz = (cn[i0] + cn[i1] + cn[i2]) / 3.0
            ln = np.linalg.norm(nz)
            if ln < 1e-9:
                continue
            nz = nz / ln

            # ★ 背面剔除改用【屏幕绕序】判断，不靠法线符号。
            #   因为 glTF 模型的 world matrix 带 x=-1/z=-1 镜像，
            #   法线方向会被翻转，按符号剔除会误杀大量正面三角形。
            #   area>0 表示逆时针（正面，OpenGL 约定）
            if area < 0:
                continue

            # 光照：用世界空间法线与光源，两面都算（abs）
            ndl = abs(float(np.dot(nz, L)))
            shade = ambient + 0.55 * ndl
            shade = min(1.45, max(0.70, shade))

            xmin = max(0, int(math.floor(min(p0[0], p1[0], p2[0]))))
            xmax = min(W - 1, int(math.ceil(max(p0[0], p1[0], p2[0]))))
            ymin = max(0, int(math.floor(min(p0[1], p1[1], p2[1]))))
            ymax = min(H - 1, int(math.ceil(max(p0[1], p1[1], p2[1]))))
            if xmin > xmax or ymin > ymax:
                continue

            X, Y = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5,
                               np.arange(ymin, ymax + 1) + 0.5)
            w0 = ((p1[0]-X)*(p2[1]-Y) - (p2[0]-X)*(p1[1]-Y)) / area
            w1 = ((p2[0]-X)*(p0[1]-Y) - (p0[0]-X)*(p2[1]-Y)) / area
            w2 = 1.0 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not m.any():
                continue

            invz = w0/z[i0] + w1/z[i1] + w2/z[i2]
            with np.errstate(divide="ignore", invalid="ignore"):
                zz = np.where(np.abs(invz) > 1e-12, 1.0/invz, np.inf)
            sub_z = zbuf[ymin:ymax+1, xmin:xmax+1]
            m &= zz < sub_z
            if not m.any():
                continue

            u = (w0*uv[i0][0]/z[i0] + w1*uv[i1][0]/z[i1] + w2*uv[i2][0]/z[i2]) * zz
            v = (w0*uv[i0][1]/z[i0] + w1*uv[i1][1]/z[i1] + w2*uv[i2][1]/z[i2]) * zz
            tu = np.clip((u * tw).astype(np.int32), 0, tw - 1)
            tv = np.clip((v * th).astype(np.int32), 0, th - 1)
            samp = tex[tv, tu]
            m &= samp[:, :, 3] >= 0.5
            if not m.any():
                continue

            _dbg["drawn"] += 1
            _dbg.setdefault(name, 0)
            _dbg[name] = _dbg.get(name, 0) + 1
            _dbg["shade_min"] = min(_dbg["shade_min"], shade)
            _dbg["shade_max"] = max(_dbg["shade_max"], shade)
            _dbg["samp_max"] = max(_dbg["samp_max"], float(samp[:, :, :3].max()))
            sub_z[m] = zz[m]
            sub = color[ymin:ymax+1, xmin:xmax+1]
            rgb = samp[:, :, :3] * shade
            sub[:, :, :3] = np.where(m[:, :, None], rgb, sub[:, :, :3])
            sub[:, :, 3] = np.where(m, 255.0, sub[:, :, 3])

    out = color.copy()
    out[:, :, :3] = np.clip(out[:, :, :3] * 255.0, 0, 255)   # RGB 是 0~1 → 0~255
    out[:, :, 3] = np.clip(out[:, :, 3], 0, 255)             # alpha 已是 0/255
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def main():
    skin = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "skin_user.png")).convert("RGBA")

    for fname, tag in (("classic-player.gltf", "classic"),
                       ("slim-player.gltf", "slim")):
        path = os.path.join(MODEL_DIR, fname)
        m = GltfModel(path).build()
        parts = m.parts()
        print(f"=== {tag}: {len(parts)} 个部位 ===")
        for (nm, prim, w, nname) in parts[:6]:
            print(f"   {nm}")
        img = render(m, skin, 126, 160)
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           f"gltf_{tag}.png")
        img.save(out)
        print(f"   → {out}")


if __name__ == "__main__":
    main()
