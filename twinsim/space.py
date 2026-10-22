"""空間（space pack）: USD のシーン 1 つ分の、歩ける所の地図・意味の地図（ゾーン・入口・ゲート・EV の扉など）・経路。Isaac Sim なしで動く。

空間は spaces/<名前>/space.yaml で定義する（形式は docs/spec.md）。歩ける所の地図は Isaac Sim のナビメッシュから作った格子
（isaac/export_space.py。0.5 m か 0.25 m 刻み）。経路は格子の上の A*（壁から離れるほど安い）を、見通しで間引いた折れ線。
"""

import heapq
import math
from pathlib import Path

import numpy as np
import yaml
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parent.parent
SPACES = ROOT / "spaces"


def point_in_poly(poly, x, y):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def load_ascii_grid(path):
    """walkable_*.txt: '# x0 .. y0 .. res ..' の説明の行（「# 」で始まる）と、1 行目が y の最大の '.'/'#' の行。返り値: (歩けるか [ny, nx]（行 0 = y0）, x0, y0, res)"""
    meta, rows = {}, []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):  # 説明の行（地図の行は空白を含まない）
            toks = line[1:].split()
            for k in ("x0", "y0", "res"):
                if k in toks:
                    meta[k] = float(toks[toks.index(k) + 1])
            continue
        if line.strip():
            rows.append(line.strip())
    grid = np.array([[c == "." for c in r] for r in rows[::-1]], bool)
    return grid, meta["x0"], meta["y0"], meta["res"]


class Space:
    def __init__(self, name, spec, folder):
        self.name, self.spec, self.folder = name, spec, Path(folder)
        lv = spec["levels"][0]
        w = lv["walkable"]
        if w.endswith(".npz"):
            z = np.load(self.folder / w)
            self.grid, self.x0, self.y0, self.res = z["walkable"].astype(bool), float(z["x0"]), float(z["y0"]), float(z["res"])
        else:
            self.grid, self.x0, self.y0, self.res = load_ascii_grid(self.folder / w)
        self.z = float(lv.get("z", 0.0))
        self.ny, self.nx = self.grid.shape
        self.clear = distance_transform_edt(self.grid) * self.res  # 壁からの距離（m）
        self.zones = {k: [tuple(map(float, p)) for p in v["polygon"]] for k, v in spec.get("zones", {}).items()}
        self.pois = spec.get("pois", {})
        self._route_cache = {}

    # ---- 格子と座標 ----
    def cell(self, x, y):
        return int(math.floor((y - self.y0) / self.res + 0.5)), int(math.floor((x - self.x0) / self.res + 0.5))

    def center(self, i, j):
        return self.x0 + j * self.res, self.y0 + i * self.res

    def walkable(self, x, y):
        i, j = self.cell(x, y)
        return 0 <= i < self.ny and 0 <= j < self.nx and bool(self.grid[i, j])

    def clearance(self, x, y):
        i, j = self.cell(x, y)
        if 0 <= i < self.ny and 0 <= j < self.nx:
            return float(self.clear[i, j])
        return 0.0

    def snap(self, x, y, min_clear=0.0):
        """いちばん近い歩ける格子の中心（壁から min_clear m 以上離れた所があればそちら）。"""
        if self.walkable(x, y) and self.clearance(x, y) >= min_clear:
            return float(x), float(y)
        ii, jj = np.nonzero(self.clear >= max(min_clear, 1e-6))
        if len(ii) == 0:
            ii, jj = np.nonzero(self.grid)
        cx, cy = self.x0 + jj * self.res, self.y0 + ii * self.res
        k = int(np.argmin((cx - x) ** 2 + (cy - y) ** 2))
        return float(cx[k]), float(cy[k])

    def bounds(self):
        return self.x0, self.x0 + (self.nx - 1) * self.res, self.y0, self.y0 + (self.ny - 1) * self.res

    # ---- 意味の地図 ----
    def zone_of(self, x, y):
        for k, poly in self.zones.items():
            if point_in_poly(poly, x, y):
                return k
        return None

    def zone_area(self, name):
        """ゾーンの中の歩ける所の面積（m²）。"""
        poly = self.zones[name]
        n = 0
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        i0, j0 = self.cell(min(xs), min(ys))
        i1, j1 = self.cell(max(xs), max(ys))
        for i in range(max(i0, 0), min(i1, self.ny - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.nx - 1) + 1):
                if self.grid[i, j] and point_in_poly(poly, *self.center(i, j)):
                    n += 1
        return n * self.res ** 2

    def poi(self, name):
        if name not in self.pois:
            raise KeyError(f"空間 {self.name} に場所 {name} がない（あるもの: {sorted(self.pois)}）")
        return self.pois[name]

    def poi_xy(self, name):
        p = self.poi(name)
        if "xy" in p:
            return tuple(map(float, p["xy"]))
        if "line" in p:
            (x0, y0), (x1, y1) = p["line"]
            return (x0 + x1) / 2, (y0 + y1) / 2
        if "zone" in p:
            poly = self.zones[p["zone"]]
            return float(np.mean([q[0] for q in poly])), float(np.mean([q[1] for q in poly]))
        raise ValueError(f"場所 {name} に位置（xy・line・zone）がない")

    # ---- 経路 ----
    def los(self, a, b, need):
        """a → b の線分の上が、どこも歩けて壁から need m 以上離れているか。"""
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(2, int(d / (self.res * 0.4)))
        for k in range(n + 1):
            x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
            if not self.walkable(x, y) or self.clearance(x, y) < need:
                return False
        return True

    def route(self, a, b, clear_w=1.5):
        """a から b への経路（折れ線、世界の座標）。歩けない所に着かないよう、両端は近い歩ける点に寄せる。"""
        a, b = self.snap(*a), self.snap(*b)
        key = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
        if key in self._route_cache:
            return list(self._route_cache[key])
        s, g = self.cell(*a), self.cell(*b)
        INF = float("inf")
        dist = {s: 0.0}
        prev = {}
        pq = [(0.0, s)]
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0), (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414)]
        while pq:
            _, c = heapq.heappop(pq)
            if c == g:
                break
            dc = dist[c]
            for di, dj, w in moves:
                n_ = (c[0] + di, c[1] + dj)
                if not (0 <= n_[0] < self.ny and 0 <= n_[1] < self.nx) or not self.grid[n_]:
                    continue
                if di and dj and not (self.grid[c[0] + di, c[1]] and self.grid[c[0], c[1] + dj]):
                    continue  # 角をすり抜けない
                nd = dc + w * self.res * (1.0 + clear_w / (self.clear[n_] + 0.25))
                if nd < dist.get(n_, INF):
                    dist[n_] = nd
                    prev[n_] = c
                    h = math.hypot(n_[0] - g[0], n_[1] - g[1]) * self.res
                    heapq.heappush(pq, (nd + h, n_))
        if g not in dist:
            raise ValueError(f"空間 {self.name}: {a} から {b} へ歩いて行けない")
        cells = [g]
        while cells[-1] != s:
            cells.append(prev[cells[-1]])
        pts = [a] + [self.center(*c) for c in cells[::-1][1:-1]] + [b]
        # 見通しで間引く（壁から 0.35 m、両端が壁際ならその近さまで許す）
        out = [pts[0]]
        i = 0
        while i < len(pts) - 1:
            need = min(0.35, self.clearance(*pts[i]), self.clearance(*pts[-1]))
            j = len(pts) - 1
            while j > i + 1 and not self.los(pts[i], pts[j], min(need, self.clearance(*pts[j]))):
                j -= 1
            out.append(pts[j])
            i = j
        self._route_cache[key] = out
        return list(out)

    def route_length(self, pts):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def list_spaces():
    return sorted(p.parent.name for p in SPACES.glob("*/space.yaml"))


def load_space(name):
    folder = SPACES / name
    spec = yaml.safe_load((folder / "space.yaml").read_text(encoding="utf-8"))
    return Space(name, spec, folder)
