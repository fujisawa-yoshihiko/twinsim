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

from . import config

ROOT = Path(__file__).resolve().parent  # 空間・テンプレート・画面・Isaac Sim のスクリプトはパッケージの中に置く（pip で入れても動くように）
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
    """walkable_*.txt: '# x0 .. y0 .. res ..' の説明の行（「# 」で始まる）と、1 行目が y の最大の '.'/'#' の行。
    返り値: (歩けるか [ny, nx]（行 0 = y0）, x0, y0, res)"""
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
        for b in lv.get("blocked", []):  # 置いた物（描画で足す EV のかごなど）の場所は歩けない
            poly = [tuple(map(float, q)) for q in b["polygon"]]
            for i in range(self.ny):
                for j in range(self.nx):
                    if self.grid[i, j] and point_in_poly(poly, self.x0 + j * self.res, self.y0 + i * self.res):
                        self.grid[i, j] = False
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

    PORTAL_R = 0.8  # 出入り口の範囲の半径（m）
    # かごのない EV（cabin_m なし）で、扉から外へ伸ばす長さ（m）。降りる人は扉から外へ 0.4 + 0.5 × k m・左右 ±0.3 m に現れる
    # （scenario.py の on_arrival）ので、1 m 伸ばすと 3 人目（k = 2）まで範囲に入る。扉の点だけだと 2 人目から範囲の外で、
    # 画面の中で急に現れる人を採点していた（hospital の見立ての EV、2026-11-04）
    ALIGHT_OUT_M = 1.0

    def portals(self):
        """人が現れる・消える所（spawn・exit・elevator）の範囲: [{name, kind, a, b}]。a〜b の線分から PORTAL_R 以内。
        spawn・exit は xy〜hidden（hidden がなければ xy の点）、elevator は扉〜かごの中（cabin_m）。
        かごのない elevator は、扉から外へ ALIGHT_OUT_M（降りる人が現れる所。face がなければ扉の点）。"""
        out = []
        for k, p in self.pois.items():
            kind = p.get("kind")
            if kind not in ("spawn", "exit", "elevator") or "xy" not in p:
                continue
            a = tuple(map(float, p["xy"]))
            b = a
            if p.get("hidden"):
                b = tuple(map(float, p["hidden"]))
            elif kind == "elevator" and "face" in p:
                dx, dy = p["face"][0] - a[0], p["face"][1] - a[1]
                n = math.hypot(dx, dy) or 1.0
                cabin = float(p.get("cabin_m", 0) or 0)
                d = cabin if cabin > 0 else -self.ALIGHT_OUT_M  # かごの中へ、かごがなければ外へ
                b = (a[0] + dx / n * d, a[1] + dy / n * d)
            out.append({"name": k, "kind": kind, "a": a, "b": b})
        return out

    def in_portal(self, x, y, r=None):
        """(x, y) が出入り口の範囲（portals）の中なら、その名前。外なら None。"""
        r = self.PORTAL_R if r is None else r
        for q in self.portals_cache():
            ax, ay = q["a"]
            bx, by = q["b"]
            vx, vy = bx - ax, by - ay
            L = vx * vx + vy * vy
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L))
            if math.hypot(x - (ax + t * vx), y - (ay + t * vy)) <= r:
                return q["name"]
        return None

    def portals_cache(self):
        if not hasattr(self, "_portals"):
            self._portals = self.portals()
        return self._portals

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


def _space_dirs():
    return ([config.USER_SPACES] if config.USER_SPACES else []) + [SPACES]


def list_spaces():
    names = {p.parent.name for d in _space_dirs() for p in d.glob("*/space.[yj]*") if p.suffix in (".yaml", ".json")}
    return sorted(names)


def find_space(name):
    """空間の名前（TWINSIM_SPACES の場所 → 付属の空間の順に探す）か、space.yaml・space.json のあるフォルダの場所 → そのフォルダ。"""
    p = Path(str(name)).expanduser()
    for folder in ([p] if p.is_absolute() or "/" in str(name) else []) + [d / str(name) for d in _space_dirs()]:
        if (folder / "space.yaml").exists() or (folder / "space.json").exists():
            return folder
    raise FileNotFoundError(f"空間 {name} がない（付属の空間: {', '.join(list_spaces())}。自分の空間はフォルダの場所を書くか、環境変数 TWINSIM_SPACES に置く）")


def load_space(name):
    folder = find_space(name)
    f = folder / "space.yaml"
    if not f.exists():
        f = folder / "space.json"
    return Space(folder.name, yaml.safe_load(f.read_text(encoding="utf-8")), folder)  # JSON は YAML として読める


# ---- 道のり ----
def _simplify(pts, tol):
    """折れ線の間引き（Ramer–Douglas–Peucker 法）。両端を結ぶ線から tol より離れた点だけを残す。"""
    if len(pts) < 3:
        return pts
    p = np.asarray(pts, float)
    d = p[-1] - p[0]
    n = float(np.hypot(*d))
    q = p - p[0]
    off = np.abs(d[0] * q[:, 1] - d[1] * q[:, 0]) / n if n > 1e-9 else np.hypot(q[:, 0], q[:, 1])
    k = int(off.argmax())
    if off[k] <= tol:
        return [pts[0], pts[-1]]
    return _simplify(pts[:k + 1], tol)[:-1] + _simplify(pts[k:], tol)


class Geodesic:
    """歩ける所の格子の上の最短の道のり（m）。始点ごとに 1 回だけダイクストラ法で全体の距離を求めて覚える。"""

    def __init__(self, sp):
        from scipy.sparse import coo_matrix
        self.sp = sp
        g = sp.grid
        ny, nx = g.shape
        idx = -np.ones(g.shape, int)
        idx[g] = np.arange(int(g.sum()))
        self.idx = idx
        rows, cols, w = [], [], []
        ii, jj = np.nonzero(g)
        for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
            i2, j2 = ii + di, jj + dj
            ok = (i2 < ny) & (j2 >= 0) & (j2 < nx)
            ok[ok] = g[i2[ok], j2[ok]]
            rows.append(idx[ii[ok], jj[ok]])
            cols.append(idx[i2[ok], j2[ok]])
            w.append(np.full(int(ok.sum()), sp.res * math.hypot(di, dj)))
        r, c, ww = np.concatenate(rows), np.concatenate(cols), np.concatenate(w)
        n = int(g.sum())
        self.graph = coo_matrix((np.r_[ww, ww], (np.r_[r, c], np.r_[c, r])), shape=(n, n)).tocsr()
        self.cache = {}
        self.ij = np.argwhere(g)   # 点の番号 → 格子の (i, j)（idx と同じ並び）
        self.pred = {}

    def node(self, xy):
        x, y = self.sp.snap(*xy) if not self.sp.walkable(*xy) else xy
        i, j = self.sp.cell(x, y)
        return int(self.idx[i, j])

    def dist(self, a, b):
        from scipy.sparse.csgraph import dijkstra
        na, nb = self.node(a), self.node(b)
        if na < 0 or nb < 0:
            return float(np.hypot(*(np.asarray(a) - np.asarray(b))))
        if nb not in self.cache:
            self.cache[nb] = dijkstra(self.graph, directed=False, indices=nb)
        d = float(self.cache[nb][na])
        return d if np.isfinite(d) else float("inf")

    def path(self, a, b, tol=0.2):
        """a から b への最短の道の点の列 [(x, y)]。格子の点の列を tol m の幅で間引く（両端は a と b）。つながらなければ直線。"""
        from scipy.sparse.csgraph import dijkstra
        na, nb = self.node(a), self.node(b)
        if na < 0 or nb < 0:
            return [tuple(map(float, a)), tuple(map(float, b))]
        if na not in self.pred:
            self.pred[na] = dijkstra(self.graph, directed=False, indices=na, return_predecessors=True)[1]
        pred, nodes = self.pred[na], [nb]
        while nodes[-1] != na:
            k = int(pred[nodes[-1]])
            if k < 0:
                return [tuple(map(float, a)), tuple(map(float, b))]
            nodes.append(k)
        pts = [self.sp.center(*self.ij[k]) for k in reversed(nodes)]
        pts[0], pts[-1] = tuple(map(float, a)), tuple(map(float, b))
        return _simplify(pts, tol)
