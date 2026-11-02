"""カメラ（Isaac Sim の USD のカメラと同じ表し方: -Z を見て +Y が上、行ベクトル p_cam = p_world · M）。
正解のファイルの cameras[名前] は、カメラの計算にそのまま使える形にする。

人の枠は、人を半径 0.25 m・背の高さの箱とみなして映したもの。隠れた割合は近似（Isaac Sim の描画を使わない）:
  壁: カメラの真下の点から足元・頭への床の上の線が、歩けない所を 1.0 m 以上続けて通れば隠れる（低い家具は 1 m 未満なら無視）
  人: 手前の人の枠と重なる割合（枠の中の 8×16 点で数える）
"""

import math

import numpy as np

RADIUS_M = 0.25


def look_at_rowmajor(eye, target, up=(0.0, 0.0, 1.0)):
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    if np.linalg.norm(s) < 1e-9:
        s = np.cross(f, np.array([0.0, 1.0, 0.0]))
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    M = np.eye(4)
    M[:3, 0], M[:3, 1], M[:3, 2] = s, u, -f
    M[3, 0], M[3, 1], M[3, 2] = -eye @ s, -eye @ u, eye @ f
    return M


def camera_dict(name, eye, target, width=1280, height=720, focal_mm=12.0, h_aperture_mm=20.955, fps=30, extra=None):
    fx = focal_mm / h_aperture_mm * width
    M = look_at_rowmajor(eye, target)
    tilt = math.degrees(math.atan2(eye[2] - target[2], math.hypot(target[0] - eye[0], target[1] - eye[1])))
    d = {"name": name, "eye": list(map(float, eye)), "target": list(map(float, target)), "focal_mm": focal_mm, "h_aperture_mm": h_aperture_mm,
         "width": width, "height": height, "fx_px": fx, "fy_px": fx, "cx_px": width / 2, "cy_px": height / 2,
         "h_fov_deg": math.degrees(2 * math.atan(h_aperture_mm / 2 / focal_mm)), "tilt_down_deg": tilt, "fps": fps,
         "world_to_camera_rowmajor": M.tolist(),
         "camera_convention": "USD: camera looks along -Z, +Y up (row vectors, p_cam = p_world * M)"}
    d.update(extra or {})
    return d


class Camera:
    def __init__(self, c, floor_z=0.0):
        self.c = c
        self.floor_z = float(floor_z)  # 床の高さ（空間の levels[0].z）。人の箱はここから立てる
        self.M = np.asarray(c["world_to_camera_rowmajor"], float)
        self.fx, self.fy, self.cx, self.cy = c["fx_px"], c["fy_px"], c["cx_px"], c["cy_px"]
        self.w, self.h = c["width"], c["height"]
        self.eye = np.asarray(c["eye"], float)

    def project(self, pts):
        ph = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ self.M
        depth = -ph[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):  # カメラと同じ高さの面の点（呼ぶ側が depth で外す）
            u = self.cx + self.fx * ph[:, 0] / depth
            v = self.cy - self.fy * ph[:, 1] / depth
        return np.c_[u, v], depth

    def floor_point(self, u, v, z=0.0):
        """画素 (u, v) を通る光線と床（高さ z）の交点（世界の x, y）。床がカメラの後ろなら None。"""
        inv = np.linalg.inv(self.M)
        d_cam = np.array([(u - self.cx) / self.fx, -(v - self.cy) / self.fy, -1.0, 0.0])
        o = np.array([0.0, 0.0, 0.0, 1.0]) @ inv
        d = d_cam @ inv
        if abs(d[2]) < 1e-9:
            return None
        t = (z - o[2]) / d[2]
        if t <= 0:
            return None
        return float(o[0] + t * d[0]), float(o[1] + t * d[1])

    def person_box(self, x, y, height):
        floor = self.floor_z
        corners = [(x + dx, y + dy, z) for dx in (-RADIUS_M, RADIUS_M) for dy in (-RADIUS_M, RADIUS_M) for z in (floor, floor + height)]
        uv, depth = self.project(corners)
        if np.any(depth <= 0.1):
            return None
        x0, y0 = uv.min(0)
        x1, y1 = uv.max(0)
        if x1 <= 0 or y1 <= 0 or x0 >= self.w or y0 >= self.h:
            return None
        area = (x1 - x0) * (y1 - y0)
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x1, self.w), min(y1, self.h)
        inside = (cx1 - cx0) * (cy1 - cy0) / max(area, 1e-9)
        _, d = self.project([(x, y, floor + height / 2)])
        return float(x0), float(y0), float(x1), float(y1), float(inside), float(d[0])

    def wall_blocked(self, space, x, y, run_m=1.0):
        """カメラの真下から (x, y) への床の上の線が、歩けない所を run_m 以上続けて通るか（近似。格子ごとに覚えておく）。"""
        key = (id(space), space.cell(x, y), run_m)
        cache = self.__dict__.setdefault("_wall", {})
        if key not in cache:
            cache[key] = self._wall_blocked(space, x, y, run_m)
        return cache[key]

    def _wall_blocked(self, space, x, y, run_m):
        ex, ey = self.eye[0], self.eye[1]
        dist = math.hypot(x - ex, y - ey)
        n = max(2, int(dist / 0.2))
        run, entered = 0.0, False  # 壁に付けたカメラの真下は歩けないことが多いので、最初に歩ける所へ入るまでは数えない
        for k in range(1, n):
            px, py = ex + (x - ex) * k / n, ey + (y - ey) * k / n
            if space.walkable(px, py):
                run, entered = 0.0, True
            elif entered:
                run += dist / n
                if run >= run_m:
                    return True
        return False

    def sees_floor(self, space, x, y, margin=0.0):
        uv, d = self.project([(x, y, self.floor_z)])
        if d[0] <= 0.1:
            return False
        u, v = uv[0]
        if not (-margin <= u <= self.w + margin and -margin <= v <= self.h + margin):
            return False
        return not self.wall_blocked(space, x, y)


def boxes_with_visibility(cam, space, people):
    """people: [(名前, x, y, 背の高さ)] → {名前: (x0, y0, x1, y1, 画面の中の割合, 見えている割合)}（近似）。"""
    boxes = {}
    for name, x, y, h in people:
        b = cam.person_box(x, y, h)
        if b is None:
            continue
        if cam.wall_blocked(space, x, y):
            vis_wall = 0.0
        else:
            vis_wall = 1.0
        boxes[name] = (b, vis_wall)
    out = {}
    order = sorted(boxes, key=lambda k: boxes[k][0][5])  # 近い順
    gu, gv = np.meshgrid(np.linspace(0.06, 0.94, 8), np.linspace(0.03, 0.97, 16))
    for i, name in enumerate(order):
        (x0, y0, x1, y1, inside, _), vw = boxes[name]
        if vw == 0.0:
            out[name] = (x0, y0, x1, y1, inside, 0.0)
            continue
        px = x0 + gu.ravel() * (x1 - x0)
        py = y0 + gv.ravel() * (y1 - y0)
        on = (px >= 0) & (px < cam.w) & (py >= 0) & (py < cam.h)
        hidden = np.zeros(len(px), bool)
        for near in order[:i]:
            (a0, b0, a1, b1, _, _), vn = boxes[near]
            hidden |= (px >= a0) & (px <= a1) & (py >= b0) & (py <= b1)
        vis = float((on & ~hidden).sum() / max(len(px), 1))
        out[name] = (x0, y0, x1, y1, inside, vis)
    return out
