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
        self.pois = spec.get("pois", {})
        for p in self.pois.values():  # 家具（1.2。座る場所の席・窓口のカウンター）: 描画で置く家具は、床の上の形の分を歩ける所から外す
            for fur in p.get("furniture", []):  # （USD にある家具 in_usd は、歩ける所の地図にもう入っている）
                if not fur.get("in_usd"):
                    self._block(furniture_place(fur)[0])
            if p.get("kind") == "seats":  # 家具でない席は半径 SEAT_BLOCK_M（経路が席の列を通らないように。座る人は席の前から決まった動作で入る）
                from .scenario import seats_of
                for (x, y), _yaw in seats_of(p, furniture=False):
                    for i in range(max(0, int((y - SEAT_BLOCK_M - self.y0) / self.res)), min(self.ny, int((y + SEAT_BLOCK_M - self.y0) / self.res) + 2)):
                        for j in range(max(0, int((x - SEAT_BLOCK_M - self.x0) / self.res)), min(self.nx, int((x + SEAT_BLOCK_M - self.x0) / self.res) + 2)):
                            if math.hypot(self.x0 + j * self.res - x, self.y0 + i * self.res - y) <= SEAT_BLOCK_M:
                                self.grid[i, j] = False
        self.clear = distance_transform_edt(self.grid) * self.res  # 壁からの距離（m）
        self.zones = {k: [tuple(map(float, p)) for p in v["polygon"]] for k, v in spec.get("zones", {}).items()}
        self._route_cache = {}
        self.soft, self.soft_id = [], None  # 経路がなるべく避ける円（set_soft）

    def _block(self, poly):
        """多角形の中の格子を歩けなくする（家具）。"""
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        for i in range(max(0, int((min(ys) - self.y0) / self.res)), min(self.ny, int((max(ys) - self.y0) / self.res) + 2)):
            for j in range(max(0, int((min(xs) - self.x0) / self.res)), min(self.nx, int((max(xs) - self.x0) / self.res) + 2)):
                if point_in_poly(poly, self.x0 + j * self.res, self.y0 + i * self.res):
                    self.grid[i, j] = False

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
            if p.get("hidden"):  # 範囲の線は、入る人と出る人の 2 本の線（door_lanes）の真ん中
                o_in, o_out, n = self.door_lanes(k)
                m = (o_in + o_out) / 2
                a = (a[0] + n[0] * m, a[1] + n[1] * m)
                b = (float(p["hidden"][0]) + n[0] * m, float(p["hidden"][1]) + n[1] * m)
            elif kind == "elevator" and "face" in p:
                dx, dy = p["face"][0] - a[0], p["face"][1] - a[1]
                n = math.hypot(dx, dy) or 1.0
                cabin = float(p.get("cabin_m", 0) or 0)
                d = cabin if cabin > 0 else -self.ALIGHT_OUT_M  # かごの中へ、かごがなければ外へ
                b = (a[0] + dx / n * d, a[1] + dy / n * d)
            out.append({"name": k, "kind": kind, "a": a, "b": b})
        return out

    DOOR_LANE_M = 0.6  # 扉の向こう（hidden）との行き来の、入る人と出る人の 2 本の線の間隔（m。体の幅 0.36 m に少しの余裕）
    DOOR_BODY_M = 0.2  # 線の外側に、この幅（体の半分ほど）も歩ける所があること

    def door_lanes(self, name):
        """扉の向こう（hidden）がある出入り口の、入る人と出る人の線 (o_in, o_out, n)。n は出る向き（xy → hidden）の左の単位ベクトル、
        o_in・o_out は xy〜hidden の線から n の向きに測ったずれ（m）。1 本の線を両方が通ると、入る人が続くあいだ出る人が線に入れず、
        扉の横の角で止まった（hospital のロビーの入口、2026-11-06）。
        入る人の線は元の線のまま（入る流れは今までの確かめと同じ）にし、出る人の線をその横 DOOR_LANE_M に置く。出る向きの左（左側通行）を先に、
        建物の中の部分（xy から、もとの線が歩ける所の外に出るまで）で出る人の線とその外側 DOOR_BODY_M が歩ける側を選ぶ
        （どちらも歩けない所があれば、歩けない点の少ない側）。出口だけの扉（kind exit）と、出る人の扉の点が歩けない（狭い扉）なら 1 本のまま (0, 0)。"""
        if not hasattr(self, "_door_lanes"):
            self._door_lanes = {}
        if name not in self._door_lanes:
            p = self.pois[name]
            ax, ay = map(float, p["xy"])
            bx, by = map(float, p["hidden"])
            L = math.hypot(bx - ax, by - ay) or 1.0
            u = ((bx - ax) / L, (by - ay) / L)
            n = (-u[1], u[0])
            pts = []
            for k in range(int(L / 0.25) + 1):
                q = (ax + u[0] * 0.25 * k, ay + u[1] * 0.25 * k)
                if k and not self.walkable(*q):
                    break
                pts.append(q)
            W, B = self.DOOR_LANE_M, self.DOOR_BODY_M

            def blocked(o):
                return sum(not self.walkable(q[0] + n[0] * o, q[1] + n[1] * o) for q in pts)
            best, out = None, (0.0, 0.0, n)
            if p.get("kind") != "exit":
                for side in (1.0, -1.0):
                    o = side * W
                    if not self.walkable(ax + n[0] * o, ay + n[1] * o):
                        continue
                    cost = blocked(o) + blocked(o + side * B)
                    if best is None or cost < best:
                        best, out = cost, (0.0, o, n)
            self._door_lanes[name] = out
        return self._door_lanes[name]

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
        if p.get("kind") == "service" and "points" in p:  # 窓口（1.2）: 応対の場所の真ん中（line は列の線）
            return float(np.mean([q[0] for q in p["points"]])), float(np.mean([q[1] for q in p["points"]]))
        if p.get("kind") == "seats":  # 座る場所（1.2）: 最初の席の前（歩ける所）
            from .components import SEAT_APPROACH_M
            from .scenario import seats_of
            (x, y), yaw = seats_of(p)[0]
            return x + SEAT_APPROACH_M * math.cos(math.radians(yaw)), y + SEAT_APPROACH_M * math.sin(math.radians(yaw))
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

    def set_soft(self, circles, weight=None):
        """経路がなるべく避ける所: [(x, y, 半径, 組の名前)]（歩けるが、通らずに済むなら通らない。窓口の前など）。
        経路の始まりか終わりがある組の円の中（＋SOFT_NEAR_M）なら、その組の円は避けない（その窓口へ行く人・出る人）。"""
        self.soft = [(float(x), float(y), float(r), g) for x, y, r, g in circles]
        self.soft_w = float(SOFT_W if weight is None else weight)
        self.soft_id = np.full(self.grid.shape, -1, int)
        for k, (x, y, r, _g) in enumerate(self.soft):
            for i in range(max(0, int((y - r - self.y0) / self.res)), min(self.ny, int((y + r - self.y0) / self.res) + 2)):
                for j in range(max(0, int((x - r - self.x0) / self.res)), min(self.nx, int((x + r - self.x0) / self.res) + 2)):
                    if math.hypot(self.x0 + j * self.res - x, self.y0 + i * self.res - y) <= r:
                        self.soft_id[i, j] = k
        self._route_cache = {}

    def _soft_active(self, a, b):
        """経路 a → b で避ける円の番号の集まり（始まり・終わりのある組は除く）。"""
        near = {g for x, y, r, g in self.soft for q in (a, b) if math.hypot(q[0] - x, q[1] - y) <= r + SOFT_NEAR_M}
        return {k for k, (_x, _y, _r, g) in enumerate(self.soft) if g not in near}

    def _crosses_soft(self, p, q, active):
        for k in active:
            x, y, r, _g = self.soft[k]
            dx, dy = q[0] - p[0], q[1] - p[1]
            L2 = dx * dx + dy * dy
            u = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((x - p[0]) * dx + (y - p[1]) * dy) / L2))
            if math.hypot(p[0] + u * dx - x, p[1] + u * dy - y) < r:
                return True
        return False

    def route(self, a, b, clear_w=1.5):
        """a から b への経路（折れ線、世界の座標）。歩けない所に着かないよう、両端は近い歩ける点に寄せる。
        なるべく避ける円（set_soft。窓口の前など）は、重みを足して避け、見通しで間引くときも横切らない。"""
        a, b = self.snap(*a), self.snap(*b)
        active = self._soft_active(a, b) if self.soft else set()
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
                if active and self.soft_id[n_] in active:
                    nd += w * self.res * self.soft_w
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
            while j > i + 1 and (not self.los(pts[i], pts[j], min(need, self.clearance(*pts[j])))
                                 or (active and self._crosses_soft(pts[i], pts[j], active))):
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


SEAT_BLOCK_M = 0.25  # 席の点からこの距離（m）の中の格子を歩けなくする
# ソファ（sofa3）の腰の位置の奥行き（家具の座標の x、正面が +）。座らせて比べた: 0 m 以下はすねが座面の縁に、+0.20 m は前の端に浅く腰かける（2026-11-16）
SOFA_SEAT_X = 0.10
SOFT_W, SOFT_NEAR_M = 4.0, 0.3  # なるべく避ける円（Space.set_soft）の重み（1 m あたり、足す長さ m）と、始まり・終わりがその円の近くとみる余り（m）
NVIDIA_HOSPITAL_PROPS = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/Environments/Hospital/Props/"
NVIDIA_OFFICE_PROPS = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/Environments/Office/Props/"
# 家具（space.yaml の場所の furniture: [{asset, xy, rot, in_usd}]。座る場所の席・窓口のカウンター）。値は家具の座標（rot は USD の z 軸まわりの回転、度）。
# box は床の上の形 [x0, y0, x1, y1]、front は正面（座る人・客の向く側）の向き（度、回す前）、seats は座った人の腰の位置。
# in_usd が真なら空間の USD にもうある（歩ける所の地図にも入っている）ので置かない。形は素材の点から測った（2026-11-16）
FURNITURE = {
    "bench3": {"usd": NVIDIA_HOSPITAL_PROPS + "SM_Chair_02a.usd", "box": [-1.178, -0.37, 1.178, 0.37], "front": -90.0,
               "seats": [[-0.785, 0.0], [0.0, 0.0], [0.785, 0.0]],
               "note": "3 人掛けの長椅子（病院の待合。NVIDIA Isaac Sim の素材、CC BY 4.0）。"
                       "腰の位置は奥行きの真ん中（座る動きを描いて決めた: 0.05 m 奥で脚が座面に、"
                       "0.10 m 奥で体が背もたれにめり込む、2026-11-16）"},
    "sofa3": {"usd": NVIDIA_OFFICE_PROPS + "SM_Sofa.usd", "box": [-0.41, -1.02, 0.41, 1.02], "front": 0.0,
              "seats": [[SOFA_SEAT_X, -0.6], [SOFA_SEAT_X, 0.0], [SOFA_SEAT_X, 0.6]],
              "note": "3 人掛けのソファ（オフィスのロビー。NVIDIA Isaac Sim の素材、CC BY 4.0）。背もたれは -x、座面の高さ約 0.45 m"},
    "counter2": {"usd": NVIDIA_OFFICE_PROPS + "SM_ReceptionTableStraight.usd", "box": [-0.08, -1.0, 0.78, 1.0], "front": 180.0, "seats": [],
                 "note": "長さ 2 m・高さ 1.12 m のカウンター（オフィスの受付の机。NVIDIA Isaac Sim の素材、CC BY 4.0）。客は -x の側"},
}


def furniture_place(fur):
    """家具 1 つ（space.yaml の furniture の要素）→ (床の上の四隅 [(x, y)], 席 [((x, y), 向き（度）)])。"""
    F = FURNITURE[fur["asset"]]
    (cx, cy), rot = map(float, fur["xy"]), math.radians(float(fur.get("rot", 0.0)))
    c, s = math.cos(rot), math.sin(rot)

    def w(x, y):
        return cx + c * x - s * y, cy + s * x + c * y
    x0, y0, x1, y1 = F["box"]
    corners = [w(x0, y0), w(x1, y0), w(x1, y1), w(x0, y1)]
    yaw = (float(fur.get("rot", 0.0)) + F["front"] + 180.0) % 360.0 - 180.0  # 正面の向き
    return corners, [(w(x, y), yaw) for x, y in F["seats"]]


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
