"""ガラスの奥の人の隠れを計算機で数える（描画の正解の注釈を補う。labels.py が使う）。

描画の注釈（isaac/render.py の labels、Replicator の塗り分け）は、ガラスを透かして奥の人の画素を「見えている」と数える。
ところが描いた映像では、飾りガラス・すりガラスの奥の人はほとんど見えない。注釈を取る間だけガラスを不透明にする方法は、
Replicator が人を 1 人も返さなくなって使えなかった（2026-11-04）。

そこで、空間ごとのガラス板（spaces/<空間>/glass.json）とカメラから、隠れる割合を数える。
- glass.json は、Isaac Sim の中で isaac/probe_materials.py が取り出した、向きのある箱。
- 数えるのは、人の体のカメラ側の面に並べた点のうち、カメラとの間に隠す種類のガラス板があるものの割合。
- 隠す種類は space.yaml の glass.occluding（MDL の名前）で決める。透明な窓ガラスなどは数えない。
"""

import json

import numpy as np

from .camera import RADIUS_M

HEIGHTS = np.linspace(0.06, 0.96, 8)  # 体の高さに対する点の高さ
ANGLES = np.radians(np.linspace(-70, 70, 5))  # カメラの方向から左右にずらす角度（カメラ側の半分の面）
THIN_M = 0.01  # 厚みのない板は、この半分の厚みの箱として扱う


def load_boxes(sp):
    """空間の隠す種類のガラス板 → {"center": (B, 3), "axes": (B, 3, 3)（行が単位の向き）, "half": (B, 3), "paths": [...]}。
    space.yaml に glass がないか、glass.json がなければ None。"""
    rule = sp.spec.get("glass")
    path = sp.folder / "glass.json"
    if not rule or not path.exists():
        return None
    occ = set(rule.get("occluding", []))
    prims = [p for p in json.loads(path.read_text())["prims"] if p["mdl"].rsplit(":", 1)[-1] in occ]
    return boxes_from_corners([p["corners"] for p in prims], [p["path"] for p in prims])


def boxes_from_corners(corners, paths=None):
    """向きのある箱の 8 つの角（k 番目の角は、k のビット i が軸 i の大きい側。probe_materials.py の出力）→ load_boxes と同じ形。"""
    centers, axes, halves = [], [], []
    for c in corners:
        c = np.asarray(c, float)
        edges = [c[1] - c[0], c[2] - c[0], c[4] - c[0]]
        lens = [float(np.linalg.norm(e)) for e in edges]
        ax = [e / n if n > 1e-6 else None for e, n in zip(edges, lens)]
        thin = [i for i, a in enumerate(ax) if a is None]
        if len(thin) > 1:  # 線や点のような箱は数えない
            continue
        for i in thin:  # 厚みのない板の法線は、ほかの 2 つの向きから
            j, k = [m for m in range(3) if m != i]
            n = np.cross(ax[j], ax[k])
            ax[i] = n / np.linalg.norm(n)
        centers.append(c[0] + sum(edges) / 2)
        axes.append(np.stack(ax))
        halves.append([max(n / 2, THIN_M) for n in lens])
    return {"center": np.asarray(centers, float).reshape(-1, 3), "axes": np.asarray(axes, float).reshape(-1, 3, 3),
            "half": np.asarray(halves, float).reshape(-1, 3), "paths": list(paths or [])}


def segments_hit(eye, pts, boxes):
    """カメラ（eye）から点（pts、(N, 3)）までの線が、どれかの箱を通るか → (N,) の真偽。点が箱の中にあるときも真（ガラスに触れて立つ人）。"""
    pts = np.asarray(pts, float)
    hit = np.zeros(len(pts), bool)
    for c, a, h in zip(boxes["center"], boxes["axes"], boxes["half"]):
        p0 = (np.asarray(eye, float) - c) @ a.T  # 箱の向きの座標
        p1 = (pts - c) @ a.T
        d = p1 - p0
        tmin = np.zeros(len(pts))
        tmax = np.ones(len(pts))
        ok = np.ones(len(pts), bool)
        for i in range(3):
            par = np.abs(d[:, i]) < 1e-12
            ok &= ~par | (np.abs(p0[i]) <= h[i])
            with np.errstate(divide="ignore", invalid="ignore"):
                t1 = (-h[i] - p0[i]) / d[:, i]
                t2 = (h[i] - p0[i]) / d[:, i]
            lo, hi = np.minimum(t1, t2), np.maximum(t1, t2)
            tmin = np.where(par, tmin, np.maximum(tmin, lo))
            tmax = np.where(par, tmax, np.minimum(tmax, hi))
        hit |= ok & (tmin <= tmax)
    return hit


class GlassOcclusion:
    """1 つのカメラの、ガラスの奥になる割合。boxes は load_boxes の形（カメラの前にない箱は先に外す）。"""

    def __init__(self, cam, boxes):
        self.cam = cam
        keep = []
        for k, (c, a, h) in enumerate(zip(boxes["center"], boxes["axes"], boxes["half"])):
            corners = np.array([c + sum((((s >> i) & 1) * 2 - 1) * h[i] * a[i] for i in range(3)) for s in range(8)])
            uv, depth = cam.project(corners)
            front = depth > 0.05
            if not front.any():
                continue
            if front.all():
                x0, y0 = uv.min(0)
                x1, y1 = uv.max(0)
                if x1 < 0 or y1 < 0 or x0 > cam.w or y0 > cam.h:
                    continue
            keep.append(k)
        paths = boxes.get("paths") or []
        self.boxes = {"center": boxes["center"][keep], "axes": boxes["axes"][keep], "half": boxes["half"][keep],
                      "paths": [paths[k] for k in keep] if paths else []}

    def body_points(self, x, y, height):
        """人の体のカメラ側の面の点（床から height まで）→ (len(HEIGHTS) × len(ANGLES), 3)。"""
        cam = self.cam
        v = np.array([cam.eye[0] - x, cam.eye[1] - y])
        n = float(np.hypot(*v))
        v = v / n if n > 1e-9 else np.array([1.0, 0.0])
        rot = np.stack([np.cos(ANGLES) * v[0] - np.sin(ANGLES) * v[1], np.sin(ANGLES) * v[0] + np.cos(ANGLES) * v[1]], 1)
        xy = np.array([x, y]) + RADIUS_M * rot
        z = cam.floor_z + height * HEIGHTS
        return np.array([[px, py, pz] for pz in z for px, py in xy])

    def fraction(self, x, y, height):
        """画面に入る体の点のうち、隠す種類のガラス板の奥になるものの割合（0〜1）。画面に入る点がなければ 0。"""
        if not len(self.boxes["center"]):
            return 0.0
        pts = self.body_points(x, y, height)
        uv, depth = self.cam.project(pts)
        inside = (depth > 0.1) & (uv[:, 0] >= 0) & (uv[:, 0] < self.cam.w) & (uv[:, 1] >= 0) & (uv[:, 1] < self.cam.h)
        if not inside.any():
            return 0.0
        return float(segments_hit(self.cam.eye, pts[inside], self.boxes).mean())
