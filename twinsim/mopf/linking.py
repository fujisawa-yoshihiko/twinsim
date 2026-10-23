"""正解を使わずに、カメラの中の途切れと、カメラの間をつなぎ、全体の人の番号（G001…）を推論する。正解は最後の採点だけに使う。

手がかり（どれも MOPF の追跡・動画・空間の地図だけから求める）:
  時間    a の終わりの床の位置から b の始まりの床の位置までの道のり（空間の歩ける所の上の最短の道）を、歩く速さで割った「来るはずの時間」と、
          実際の間の時間のずれ。早すぎる（来るはずの時間より短い）ほど強く、遅い（受付・待ち合わせへの立ち寄り）ほど弱く罰する
  向き    a の終わりの歩く向きが b の方を向いているか、b の始まりの歩く向きが a の方から来ているか
  見た目  動画から切り出した人の見た目の似ていなさ。服の色（上半分・下半分の色相・彩度のヒストグラム）か、人物照合のモデル
          （OSNet など、twinsim/reid.py）の特徴。同じカメラに同じ時刻に映る 2 人（必ず別の人）の似ていなさの分布で標準化する（正解を使わない）
  時間の学習（time*）  1 回目の推論の確からしい組（余裕が大きく、見た目もよく似ている）から、来るはずの時間とのずれの分布を
          カメラの組ごとに学び（カーネル密度推定）、2 回目の推論に使う（正解を使わない）
段:
  1. トラックレット: MOPF の ID のひと続き（0.5 秒より長い途切れで分ける）。足元を床に写す
  2. カメラの中: 3 秒以内の途切れを、位置の予測と見た目でつなぐ → カメラの追跡
  3. カメラの間: カメラの追跡の終わり → 別のカメラの追跡の始まり（90 秒以内）を、時間・向き・見た目でつなぐ
  2・3 とも、各端のつながりは 1 つまで（ハンガリー法）。費用が上限を超える組はつながない
  4. つながりをたどって全体の番号
採点（正解を使う）: トラックレットの人（コマごとの対応で多い人）、カメラの間の組の適合率・再現率、2 台を合わせた IDF1（AI City の MTMC と同じ考え方）。
方式の名前: 手がかりを + でつなぐ。time（時間＋向き、来るはずの時間は地図から）・time*（時間＋向き、ずれの分布を学ぶ）・
color・osnet_x0_25_msmt17 など（見た目）。例 time+color、time*+osnet_x0_25_msmt17。比べのための none（つながない）・within（カメラの中だけ）。
"""

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

from .. import config
from ..camera import Camera
from ..space import load_space
from .identity import match_frames
from .io import iou_matrix, load_tracks, open_run, tracks_dir_and_offset

SPLIT_FRAMES = 15      # この長さより長い途切れで ID を分ける（0.5 秒）
MIN_FRAMES = 10        # これより短いトラックレットは使わない
GAP_WITHIN_S = 3.0     # カメラの中でつなぐ途切れの上限（秒）
GAP_CROSS_S = 90.0     # カメラの間の移動の上限（秒。受付に寄る人を含める）
OVERLAP_S = 1.0        # カメラの間で、b が a の終わりよりこれだけ前に始まってもよい（視野の端の重なり）
MAX_COST_WITHIN = 0.0    # 費用（= −LLR）がこれ以下の組だけつなぐ
MAX_COST_CROSS = 0.0
N_CROPS = 8            # 見た目に使う切り出しの数（トラックレットごと）
MIN_BOX_H = 50         # これより小さい人は見た目に使わない（画素）
CROP_SELECT = "spread"  # 代表の切り出しの選び方: spread（時間に等間隔）か quality（全身の縦横比・大きさを先に。office_gate_ev では差が ±0.01 で効果なし）
BIG = 1e6
KDE_MIN = 10           # 時間の学習に要る、確からしい組の数（カメラの組ごと。足りなければ地図からの仮定のまま）


def parse_method(m):
    """方式の名前 → {"time": None・"map"・"learned", "app": 見た目の種類か None, "cluster": 階層クラスタリングか}。
    頭に "hc:" があれば、カメラの間を 1 対 1 の割り当てではなく階層クラスタリングでまとめる。none・within は None を返す"""
    if m in ("none", "within"):
        return None
    out = {"time": None, "app": None, "cluster": m.startswith("hc:")}
    for part in m.removeprefix("hc:").split("+"):
        if part == "time":
            out["time"] = "map"
        elif part == "time*":
            out["time"] = "learned"
        else:
            out["app"] = part
    return out


@dataclass
class Tracklet:
    key: str
    camera: str
    mopf_id: int
    frames: np.ndarray            # シミュレータのコマ
    boxes: np.ndarray             # (n, 4) 画素
    floor: np.ndarray             # (n, 2) 足元の床の上の位置（m）
    fps: int
    feats: dict = field(default_factory=dict)  # 見た目の種類 → 特徴（服の色のヒストグラムか、人物照合のモデルのベクトル）
    n_crops: int = 0
    thumb: object = None          # 見た目の見本（PIL の画像）
    extra: dict = field(default_factory=dict)

    @property
    def t0(self):
        return float(self.frames[0]) / self.fps

    @property
    def t1(self):
        return float(self.frames[-1]) / self.fps

    def _pos(self, sl):
        return np.median(self.floor[sl], axis=0)

    @property
    def start(self):
        return self._pos(slice(0, self.fps // 2))

    @property
    def end(self):
        return self._pos(slice(-(self.fps // 2), None))

    def _vel(self, sl):
        f, p = self.frames[sl], self.floor[sl]
        if len(f) < 2 or f[-1] == f[0]:
            return np.zeros(2)
        return (np.median(p[-5:], axis=0) - np.median(p[:5], axis=0)) / ((f[-1] - f[0]) / self.fps)

    @property
    def v_start(self):
        return self._vel(slice(0, self.fps))

    @property
    def v_end(self):
        return self._vel(slice(-self.fps, None))

    @property
    def speed(self):
        """歩く速さ: 1 秒離れたコマの間の速さの 75% 点（止まっている間に引きずられないように。0.6〜1.8 m/s に収める）"""
        k = self.fps
        if len(self.frames) <= k:
            v = float(np.linalg.norm(self._vel(slice(None))))
        else:
            d = np.linalg.norm(self.floor[k:] - self.floor[:-k], axis=1) / ((self.frames[k:] - self.frames[:-k]) / self.fps)
            v = float(np.percentile(d, 75))
        return float(np.clip(v, 0.6, 1.8))


@dataclass
class CamTrack:
    """カメラの中でつないだトラックレットのまとまり（カメラの間をつなぐ単位）"""
    key: str
    camera: str
    members: list
    feats: dict

    @property
    def first(self):
        return self.members[0]

    @property
    def last(self):
        return self.members[-1]

    @property
    def t0(self):
        return self.first.t0

    @property
    def t1(self):
        return self.last.t1


# ---- 1. トラックレット ----
def build_tracklets(run, gt, cams, tdir, f0, sp):
    out = []
    for cam in cams:
        c = Camera(gt["cameras"][cam])
        per = defaultdict(list)
        for k, rows in load_tracks(tdir / f"{cam}.jsonl").items():
            for tid, x0, y0, x1, y1 in rows:
                per[tid].append((f0 + k, x0, y0, x1, y1))
        for tid, rows in sorted(per.items()):
            rows.sort()
            parts = [[rows[0]]]
            for r in rows[1:]:
                (parts.append([r]) if r[0] - parts[-1][-1][0] > SPLIT_FRAMES else parts[-1].append(r))
            for pi, part in enumerate(parts):
                if len(part) < MIN_FRAMES:
                    continue
                fl, keep = [], []
                for f, x0, y0, x1, y1 in part:
                    q = c.floor_point((x0 + x1) / 2, y1, sp.z)
                    if q is not None:
                        fl.append(sp.snap(*q) if not sp.walkable(*q) else q)
                        keep.append((f, x0, y0, x1, y1))
                if len(keep) < MIN_FRAMES:
                    continue
                a = np.asarray(keep, float)
                out.append(Tracklet(f"{cam}:{tid}" + (f".{pi}" if len(parts) > 1 else ""), cam, int(tid), a[:, 0].astype(int), a[:, 1:5],
                                    np.asarray(fl, float), int(gt["fps"])))
    return out


# ---- 見た目 ----
def _hist(crop_hsv):
    h = crop_hsv.shape[0]
    feats = []
    for part in (crop_hsv[int(h * 0.15): h // 2], crop_hsv[h // 2: int(h * 0.9)]):  # 頭と足元を少し除いた上半分・下半分
        hist, _, _ = np.histogram2d(part[..., 0].ravel(), part[..., 1].ravel(), bins=(18, 8), range=((0, 180), (0, 256)))
        feats.append(hist.ravel() / max(hist.sum(), 1))
    return np.stack(feats)


def color_distance(a, b):
    """上半分・下半分のバタチャリヤ距離の平均（0 = 同じ色、1 = 重ならない）"""
    return float(np.mean([math.sqrt(max(0.0, 1.0 - float(np.sum(np.sqrt(a[i] * b[i]))))) for i in range(2)]))


def app_distance(kind, a, b):
    """見た目の似ていなさ。服の色はバタチャリヤ距離、人物照合のモデルはコサイン距離（1 − 内積）"""
    return color_distance(a, b) if kind == "color" else float(1.0 - float(a @ b))


def aggregate(kind, feats, weights):
    """いくつかの特徴（切り出しごと・トラックレットごと）を 1 つにまとめる"""
    m = np.sum([f * w for f, w in zip(feats, weights)], axis=0)
    if kind == "color":
        return m / np.maximum(m.sum(axis=1, keepdims=True), 1e-12)
    return m / max(float(np.linalg.norm(m)), 1e-12)


def pick_crops(tracks):
    """トラックレットごとに代表の切り出しを N_CROPS 個選ぶ → {(カメラ, コマ): [(トラックレット, 枠)]}。
    候補: ほかの人と重ならない（IoU 0.05 以下）・画面の端にかからない・高さ MIN_BOX_H 以上。
    その中で、全身が入った縦横比（高さ ÷ 幅 1.8〜3.6）を先に、大きい枠を先にして、時間に散らばるように
    （トラックレットを N_CROPS に区切った各区間から 1 つ）選ぶ。
    （AI City 2024 の 1 位の手法は姿勢で代表の画像を選ぶ。ここでは姿勢のモデルを足さずに、縦横比と大きさで代える）"""
    want = defaultdict(list)
    by_cf = defaultdict(list)
    for t in tracks:
        for f, b in zip(t.frames, t.boxes):
            by_cf[(t.camera, int(f))].append(b)
    for t in tracks:
        ok = []
        for i, (f, b) in enumerate(zip(t.frames, t.boxes)):
            if b[3] - b[1] < MIN_BOX_H or b[0] < 4 or b[1] < 4 or b[2] > 1276 or b[3] > 716:
                continue
            others = [o for o in by_cf[(t.camera, int(f))] if not np.allclose(o, b)]
            if others and iou_matrix([b], others).max() > 0.05:
                continue
            ok.append(i)
        if not ok:
            continue

        def quality(i, boxes=t.boxes):
            b = boxes[i]
            h, w = b[3] - b[1], max(b[2] - b[0], 1.0)
            return (1.8 <= h / w <= 3.6, h)
        if CROP_SELECT == "spread":
            chosen = [ok[int(k)] for k in np.linspace(0, len(ok) - 1, min(N_CROPS, len(ok)))]
        else:
            chosen = [max(part, key=quality) for part in np.array_split(np.asarray(ok), min(N_CROPS, len(ok)))]
        for i in chosen:
            want[(t.camera, int(t.frames[i]))].append((t, t.boxes[i]))
    return want


def add_appearance(run, tracks, cams, kinds=("color",)):
    """動画を 1 回ずつ読んで切り出し、見た目の特徴を種類ごとに作る（t.feats[種類]）。返り値: かかった時間（切り出し 1 枚あたり ms）"""
    import time

    import cv2
    from PIL import Image
    want = pick_crops(tracks)
    crops = defaultdict(list)
    thumbs = {}
    rl = run / "render_log.json"
    v0 = json.loads(rl.read_text())["frames"][0] if rl.exists() else 0
    t_read = time.perf_counter()
    for cam in cams:
        frames = sorted(f for c, f in want if c == cam)
        if not frames:
            continue
        cap = cv2.VideoCapture(str(run / "video" / f"{cam}.mp4"))
        k, fi = 0, 0
        while fi < len(frames):
            if v0 + k == frames[fi]:
                ok, img = cap.read()
                if not ok:
                    break
                for t, b in want[(cam, frames[fi])]:
                    x0, y0, x1, y1 = (int(v) for v in b)
                    crop = img[max(0, y0):y1, max(0, x0):x1]
                    if crop.size == 0:
                        continue
                    crops[t.key].append(crop.copy())
                    if t.key not in thumbs or len(crops[t.key]) == (N_CROPS + 1) // 2:
                        thumbs[t.key] = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)).resize((48, 120))
                fi += 1
            elif not cap.grab():
                break
            k += 1
        cap.release()
    timing = {"read_s": round(time.perf_counter() - t_read, 1), "crops": sum(len(v) for v in crops.values())}
    by = {t.key: t for t in tracks}
    for key, cs in crops.items():
        by[key].n_crops = len(cs)
        by[key].thumb = thumbs.get(key)
    for kind in kinds:
        t0 = time.perf_counter()
        if kind == "color":
            for key, cs in crops.items():
                by[key].feats["color"] = aggregate("color", [_hist(cv2.cvtColor(c, cv2.COLOR_BGR2HSV).astype(float)) for c in cs], [1.0] * len(cs))
            timing["color_ms_per_crop"] = round(1000 * (time.perf_counter() - t0) / max(timing["crops"], 1), 2)
        else:
            from ..reid import Embedder
            emb = Embedder(kind)
            keys = list(crops)
            flat = [c for k in keys for c in crops[k]]
            f = emb(flat)
            i = 0
            for key in keys:
                n = len(crops[key])
                by[key].feats[kind] = aggregate(kind, list(f[i:i + n]), [1.0] * n)
                i += n
            timing[f"{kind}_ms_per_crop"] = emb.ms_per_crop
    return timing


def app_null(tracks, kind):
    """同じカメラに 1 秒以上同じ時刻に映る 2 つ（必ず別の人）の見た目の距離の平均と標準偏差 → 見た目の標準化に使う"""
    d = []
    for i, a in enumerate(tracks):
        for b in tracks[i + 1:]:
            if a.camera != b.camera or kind not in a.feats or kind not in b.feats:
                continue
            if min(a.t1, b.t1) - max(a.t0, b.t0) >= 1.0:
                d.append(app_distance(kind, a.feats[kind], b.feats[kind]))
    if len(d) < 10:
        return None
    return {"mean": float(np.mean(d)), "sd": float(max(np.std(d), 0.02)), "n": len(d)}


# ---- 道のり ----
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


# ---- 費用: 「同じ人」と「別の人」の尤もらしさの比の対数（LLR）の和の符号を変えたもの。0 より小さい（同じ人のほうが尤もらしい）組だけつなぐ ----
DETOUR_P = 0.2   # 同じ人が寄り道（受付・待ち合わせ）をして遅れる割合（仮）
KAPPA = 2.0      # 同じ人の、歩く向きと相手の方向の合い方（フォン・ミーゼス分布の集中度、仮）
LLR_MAX = 6.0    # 1 つの手がかりで足す LLR の上限（1 つの手がかりだけで決めない）
P_HAS = 0.5      # 端（追跡の終わり・始まり）に、つながる相手がいる見込み（事前の確率、仮）。候補の数で割って事前の対数オッズにする


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


def llr_time(gap, exp, window, learned=None):
    """同じ人: 来るはずの時間のまわりの正規分布（1 − DETOUR_P）＋来るはずの時間から窓の終わりまでの一様（寄り道、DETOUR_P）。
    learned（学んだずれ gap − exp の列）があれば、正規分布の代わりにそのカーネル密度推定。別の人: 窓の中の一様。"""
    sig = 0.8 + 0.15 * exp
    if learned is not None:
        r = np.asarray(learned, float)
        h = max(0.3, 1.06 * float(np.std(r)) * len(r) ** -0.2)  # シルバーマンの目安
        dens = float(np.mean(np.exp(-0.5 * ((gap - exp - r) / h) ** 2))) / (h * math.sqrt(2 * math.pi))
        same = (1 - DETOUR_P) * dens
    else:
        same = (1 - DETOUR_P) * math.exp(-0.5 * ((gap - exp) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))
    if gap >= exp:
        same += DETOUR_P / max(window - exp, 1.0)
    return float(np.clip(math.log(max(same, 1e-12) * window), -LLR_MAX, LLR_MAX)), (gap - exp) / sig


def llr_dir(cos):
    """同じ人: 歩く向きが相手の方を向く（フォン・ミーゼス、集中度 KAPPA）。別の人: 一様"""
    return math.log(KAPPA / math.sinh(KAPPA)) + KAPPA * cos


def llr_app(kind, fa, fb, null):
    """別の人の見た目の距離（同じ時刻に同じカメラに映る 2 人から求めた分布）より似ているほど大きく。z ≥ 0（別の人より似ていない）は −z"""
    z = (app_distance(kind, fa, fb) - null["mean"]) / null["sd"]
    v = -math.log(max(2 * 0.5 * math.erfc(-z / math.sqrt(2)), 1e-12)) if z < 0 else -z
    return float(np.clip(v, -LLR_MAX, LLR_MAX)), z


def cost_within(a, b, null, kind):
    """同じカメラの中の途切れ: 位置の予測（a の終わりの位置と速度から）のずれ。別の人は 30 m² の中のどこか（一様）とみる"""
    gap = b.t0 - a.t1
    if gap < -0.2 or gap > GAP_WITHIN_S:
        return None
    g = max(gap, 0.0)
    pred = a.end + a.v_end * g
    sig = 0.4 + 0.5 * g
    r = float(np.linalg.norm(b.start - pred))
    lp = float(np.clip(math.log(math.exp(-0.5 * (r / sig) ** 2) / (2 * math.pi * sig ** 2) * 30.0 + 1e-12), -LLR_MAX, LLR_MAX))
    parts = {"gap": round(gap, 2), "pos_err_m": round(r, 2), "llr_pos": round(lp, 2)}
    s = lp
    if kind and null and kind in a.feats and kind in b.feats:
        lc, z = llr_app(kind, a.feats[kind], b.feats[kind], null)
        parts.update({"app_z": round(z, 2), "llr_app": round(lc, 2)})
        s += lc
    parts["llr"] = round(s, 3)
    parts["cost"] = round(-s, 3)
    return parts


def cost_cross(a, b, fa, fb, geo, null, use_time, kind, learned=None):
    """a（前のカメラの追跡の最後のトラックレット）の終わり → b（次のカメラの追跡の最初）の始まり。fa・fb はカメラの追跡全体の見た目。
    use_time: None（時間を使わない）・"map"・"learned"。learned: カメラの組（a, b）ごとの学んだずれの列"""
    gap = b.t0 - a.t1
    if gap < -OVERLAP_S or gap > GAP_CROSS_S:
        return None
    parts = {"gap": round(gap, 2)}
    s = 0.0
    if use_time:
        d = geo.dist(a.end, b.start)
        if not np.isfinite(d):
            return None
        v = max(a.speed, b.speed)  # 止まっている間を含むと遅く出るので、速い方（歩いている方）を使う
        exp = d / v
        lr = (learned or {}).get((a.camera, b.camera)) if use_time == "learned" else None
        lt, z = llr_time(gap, exp, GAP_CROSS_S + OVERLAP_S, lr)
        to_b = _unit(b.start - a.end)
        ld, ca, cb = 0.0, None, None
        if to_b is not None:
            ua, ub = _unit(a.v_end), _unit(b.v_start)
            if ua is not None and np.linalg.norm(a.v_end) > 0.3:
                ca = float(ua @ to_b)
                ld += llr_dir(ca)
            if ub is not None and np.linalg.norm(b.v_start) > 0.3:
                cb = float(ub @ to_b)
                ld += llr_dir(cb)
        parts.update({"dist_m": round(d, 1), "expected_s": round(exp, 1), "time_z": round(z, 2), "llr_time": round(lt, 2),
                      "cos_end": None if ca is None else round(ca, 2), "cos_start": None if cb is None else round(cb, 2), "llr_dir": round(ld, 2)})
        s += lt + ld
    if kind:
        if null and fa is not None and fb is not None:
            lc, z = llr_app(kind, fa, fb, null)
            parts.update({"app_z": round(z, 2), "llr_app": round(lc, 2)})
            s += lc
        elif not use_time:
            return None
    parts["llr"] = round(s, 3)
    parts["cost"] = round(-s, 3)
    return parts


def assign(items_a, items_b, fn, max_cost):
    """a の終わり → b の始まりを 1 対 1 に（ハンガリー法）。返り値: [(i, j, 費用の内訳, 余裕)]。余裕 = 2 番目に安い相手との差（確からしさ）"""
    from scipy.optimize import linear_sum_assignment
    n, m = len(items_a), len(items_b)
    if not n or not m:
        return []
    C = np.full((n, m), BIG)
    P = {}
    for i, a in enumerate(items_a):
        for j, b in enumerate(items_b):
            if a is b:
                continue
            p = fn(a, b)
            if p is not None:
                C[i, j] = p["cost"]
                P[(i, j)] = p
    # 事前の対数オッズ: 1 つの端の候補（窓の中のつなげうる相手）の平均の数を k として log(P_HAS / k)。候補が多いほど基準を厳しくする
    n_cand = [int(np.sum([fn(a, b) is not None for b in items_b if b is not a])) for a in items_a]
    k = max(1.0, float(np.mean([x for x in n_cand if x])) if any(n_cand) else 1.0)
    prior = math.log(P_HAS / k)
    C = np.where(C < BIG, C - prior, BIG)
    for key in P:
        P[key] = {**P[key], "prior": round(prior, 2), "cost": round(P[key]["cost"] - prior, 3)}
    C[C > max_cost] = BIG
    r, c = linear_sum_assignment(C)
    out = []
    for i, j in zip(r, c):
        if C[i, j] >= BIG:
            continue
        row = np.sort(np.r_[C[i, :j], C[i, j + 1:]])
        col = np.sort(np.r_[C[:i, j], C[i + 1:, j]])
        second = min(row[0] if len(row) else BIG, col[0] if len(col) else BIG, max_cost)
        out.append((i, j, P[(i, j)], round(float(second - C[i, j]), 2)))
    return out


class Groups:
    def __init__(self, keys):
        self.p = {k: k for k in keys}

    def find(self, k):
        while self.p[k] != k:
            self.p[k] = self.p[self.p[k]]
            k = self.p[k]
        return k

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def chains(tracks, links):
    """つながり [(a のキー, b のキー)] → {キー: 番号の根}"""
    g = Groups([t.key for t in tracks])
    for a, b in links:
        g.union(a, b)
    return {t.key: g.find(t.key) for t in tracks}


def predict(tracks, geo, nulls, method, learned=None):
    """方式ごとに、カメラの中 → カメラの間の順につなぐ。nulls: 見た目の種類 → 別の人の距離の分布。
    返り値: (番号 {キー: G…}, カメラの中のつながり, カメラの間のつながり)"""
    opt = parse_method(method)
    kind = opt["app"] if opt else None
    null = nulls.get(kind) if kind else None
    within = []
    if method != "none":
        for cam in sorted({t.camera for t in tracks}):
            ts = sorted([t for t in tracks if t.camera == cam], key=lambda t: t.t0)
            for i, j, p, mg in assign(ts, ts, lambda a, b: cost_within(a, b, null, kind), MAX_COST_WITHIN):
                within.append({"from": ts[i].key, "to": ts[j].key, **p, "margin": mg})
    root = chains(tracks, [(w["from"], w["to"]) for w in within])
    # カメラの追跡: 同じ根のトラックレットをまとめる（見た目は切り出しの数で重みをつけた平均）
    groups = defaultdict(list)
    for t in tracks:
        groups[root[t.key]].append(t)
    ctracks = []
    for r, ts in groups.items():
        ts.sort(key=lambda t: t.t0)
        feats = {}
        for k in {k for t in ts for k in t.feats}:
            have = [t for t in ts if k in t.feats and t.n_crops]
            if have:
                feats[k] = aggregate(k, [t.feats[k] for t in have], [t.n_crops for t in have])
        ctracks.append(CamTrack(r, ts[0].camera, ts, feats))
    cross = []
    if opt and opt["cluster"]:
        return _predict_cluster(tracks, ctracks, within, geo, null, opt, kind, learned)
    if opt:
        def fn(a, b):
            if a.camera == b.camera:
                return None
            return cost_cross(a.last, b.first, a.feats.get(kind), b.feats.get(kind), geo, null, opt["time"], kind, learned)
        for i, j, p, mg in assign(ctracks, ctracks, fn, MAX_COST_CROSS):
            a, b = ctracks[i], ctracks[j]
            cross.append({"from": a.last.key, "to": b.first.key, "from_track": a.key, "to_track": b.key,
                          "from_camera": a.camera, "to_camera": b.camera, "t_from": round(a.t1, 2), "t_to": round(b.t0, 2), **p, "margin": mg})
    root2 = chains(tracks, [(w["from"], w["to"]) for w in within] + [(c["from"], c["to"]) for c in cross])
    order = sorted({root2[t.key] for t in tracks}, key=lambda r: min(t.t0 for t in tracks if root2[t.key] == r))
    gid = {r: f"G{k + 1:03d}" for k, r in enumerate(order)}
    return {t.key: gid[root2[t.key]] for t in tracks}, within, cross


def _predict_cluster(tracks, ctracks, within, geo, null, opt, kind, learned):
    """カメラの追跡を、平均連結の階層クラスタリングでまとめる（後でまとめて処理する方式）。
    2 つの追跡の点数 = 見た目の LLR ＋（別のカメラで、時間の順に窓の中なら）時間・向きの LLR ＋ 事前の対数オッズ。
    つながない条件: 同じカメラで 0.5 秒以上同時に映る、別のカメラで同時に映る（視野が重ならない）、別のカメラで窓（90 秒）より離れている。
    2 つのまとまりの点数 = 組の点数の平均（つながない組が 1 つでもあれば −∞）。点数が 0 より大きいあいだ、いちばん大きい組をまとめる。"""
    n = len(ctracks)
    S = np.full((n, n), -np.inf)
    n_cand = []
    for i, a in enumerate(ctracks):
        k = 0
        for j, b in enumerate(ctracks):
            if i == j:
                continue
            if a.camera == b.camera:
                if min(a.t1, b.t1) - max(a.t0, b.t0) >= 0.5:
                    continue
                if kind and null and kind in a.feats and kind in b.feats:
                    S[i, j] = llr_app(kind, a.feats[kind], b.feats[kind], null)[0] - 3.0  # 同じカメラにまた現れる見込みは小さい
                continue
            first, second = (a, b) if a.t1 <= b.t1 else (b, a)
            p = cost_cross(first.last, second.first, first.feats.get(kind), second.feats.get(kind), geo, null, opt["time"], kind, learned)
            if p is None:
                continue
            S[i, j] = p["llr"]
            k += 1
        n_cand.append(k)
    prior = math.log(P_HAS / max(1.0, float(np.mean([x for x in n_cand if x])) if any(n_cand) else 1.0))
    S = np.where(np.isfinite(S), S + prior, -np.inf)
    S = np.where(np.isfinite(S) & np.isfinite(S.T), np.maximum(S, S.T), -np.inf)  # どちらの向きから見ても同じ点数に
    clusters = {i: [i] for i in range(n)}
    # 平均連結（つながない組があれば −∞）。まとまりどうしの点数の表を、まとめるたびに更新する
    C = S.copy()
    np.fill_diagonal(C, -np.inf)
    alive = np.ones(n, bool)
    while True:
        Cm = np.where(alive[:, None] & alive[None, :], C, -np.inf)
        i, j = np.unravel_index(int(np.argmax(Cm)), Cm.shape)
        if not np.isfinite(Cm[i, j]) or Cm[i, j] <= 0:
            break
        clusters[i] += clusters.pop(j)
        alive[j] = False
        for k in range(n):
            if alive[k] and k != i:
                vals = S[np.ix_(clusters[i], clusters[k])]
                C[i, k] = C[k, i] = -np.inf if not np.all(np.isfinite(vals)) else float(vals.mean())
    gid_of = {}
    order = sorted(clusters.values(), key=lambda ms: min(ctracks[m].t0 for m in ms))
    cross = []
    for g, ms in enumerate(order):
        members = sorted((ctracks[m] for m in ms), key=lambda c: c.t0)
        for c in members:
            for t in c.members:
                gid_of[t.key] = f"G{g + 1:03d}"
        for a, b in zip(members, members[1:]):  # 時間の順に隣り合う別のカメラの追跡を「カメラの間の組」として書く
            if a.camera == b.camera:
                continue
            p = cost_cross(a.last, b.first, a.feats.get(kind), b.feats.get(kind), geo, null, opt["time"], kind, learned) or {"gap": round(b.t0 - a.t1, 2)}
            cross.append({"from": a.last.key, "to": b.first.key, "from_track": a.key, "to_track": b.key, "from_camera": a.camera, "to_camera": b.camera,
                          "t_from": round(a.t1, 2), "t_to": round(b.t0, 2), **p, "prior": round(prior, 2),
                          "cost": round(-(p.get("llr", 0.0) + prior), 3), "margin": round(p.get("llr", 0.0) + prior, 2)})
    return gid_of, within, cross


def learn_time(cross, margin_min=2.0, app_z_max=-2.0):
    """1 回目の推論の確からしい組（余裕 ≥ margin_min、見た目の z ≤ app_z_max）から、カメラの組ごとに来るはずの時間とのずれ（gap − 来るはずの時間）を集める。
    KDE_MIN 組に満たないカメラの組は学ばない（地図からの仮定のまま）。正解は使わない。"""
    res = defaultdict(list)
    for c in cross:
        if c.get("expected_s") is None or c["margin"] < margin_min or c.get("app_z", -99) > app_z_max:
            continue
        res[(c["from_camera"], c["to_camera"])].append(c["gap"] - c["expected_s"])
    return {k: v for k, v in res.items() if len(v) >= KDE_MIN}


# ---- 採点（正解を使う） ----
def truth_labels(run, gt, cams, tracks, tdir, f0):
    """トラックレットごとに、コマの正解の人の数え上げ（MOPF の枠と正解の枠のコマごとの対応から）"""
    M = {c: match_frames(run, gt, c, tdir, f0) for c in cams}
    inv = {c: {f: {tid: n for n, tid in r["pairs"].items()} for f, r in M[c].items()} for c in cams}
    for t in tracks:
        names = [inv[t.camera].get(int(f), {}).get(t.mopf_id) for f in t.frames]
        cnt = Counter(n for n in names if n)
        t.extra["person"] = cnt.most_common(1)[0][0] if cnt else None
        t.extra["purity"] = round(cnt.most_common(1)[0][1] / len(names), 3) if cnt else 0.0
        head = Counter(n for n in names[: t.fps] if n)
        tail = Counter(n for n in names[-t.fps:] if n)
        # 始まり・終わりの 1 秒にまだ正解の枠と対応しない（体が画面に入りきらないなど）ときは、全体で多い人
        t.extra["person_start"] = head.most_common(1)[0][0] if head else t.extra["person"]
        t.extra["person_end"] = tail.most_common(1)[0][0] if tail else t.extra["person"]
    return M


def score(run, gt, cams, tracks, gids, cross, M, handovers):
    """カメラの間の組の適合率・再現率と、2 台を合わせた IDF1"""
    import motmetrics as mm
    by = {t.key: t for t in tracks}
    ok = 0
    for c in cross:
        pa, pb = by[c["from"]].extra["person_end"], by[c["to"]].extra["person_start"]
        c["correct"] = bool(pa and pa == pb)
        c["person_from"], c["person_to"] = pa, pb
        ok += c["correct"]
    found = {(c["person_from"], c["from_camera"], c["to_camera"]) for c in cross if c["correct"]}
    recall = sum(1 for h in handovers if (h["person"], h["from"], h["to"]) in found)
    # 2 台を合わせた IDF1: コマごとに、見えている正解の枠（人の名前）と MOPF の枠（予測の番号）を対応づける
    key_at = {}
    for t in tracks:
        for f in t.frames:
            key_at[(t.camera, int(f), t.mopf_id)] = t.key
    acc = mm.MOTAccumulator(auto_id=False)
    num = {}  # motmetrics は数の ID だけ受け付ける

    def n_(x):
        return num.setdefault(x, len(num) + 1)
    for ci, c in enumerate(cams):
        for f, r in sorted(M[c].items()):
            gts = list(r["gt_boxes"].items())
            hyps = [(gids.get(key_at.get((c, f, tid)), f"{c}:{tid}:short"), b) for tid, b in r["mopf_boxes"].items()]
            dmat = 1 - iou_matrix([b for _, b in gts], [b for _, b in hyps]) if gts and hyps else np.empty((len(gts), len(hyps)))
            dmat = np.where(dmat > 0.7, np.nan, dmat)
            acc.update([n_(("gt", n)) for n, _ in gts], [n_(("hyp", h)) for h, _ in hyps], dmat, frameid=ci * 10_000_000 + f)
    s = mm.metrics.create().compute(acc, metrics=["idf1", "idp", "idr", "num_switches", "mota"], name="all")
    row = {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else int(v)) for k, v in s.iloc[0].items()}
    row.update({"cross_links": len(cross), "cross_correct": ok, "cross_precision": round(ok / len(cross), 3) if cross else None,
                "handovers": len(handovers), "handovers_found": recall, "cross_recall": round(recall / len(handovers), 3) if handovers else None,
                "global_ids": len(set(gids.values()))})
    return row


def _handovers(run, cams, tracks_dir=None):
    """本当のカメラの間の移り（正解）。identities.json がなければ、または追跡の置き場所を変えたときは作り直す"""
    p = run / "mopf_eval" / "identities.json"
    if tracks_dir is not None or not p.exists():
        from .identity import identities
        res, _ = identities(run, cams, tracks_dir)
    else:
        res = json.loads(p.read_text())
    return [{"person": n, **h} for n, q in res["persons"].items() for h in q["handovers"] if h["from"] in cams and h["to"] in cams]


# ---- まとめ ----
def available_apps():
    """使える見た目の種類: 服の色と、torch と重みがそろっている人物照合のモデル"""
    out = ["color"]
    try:
        import torch  # noqa: F401

        from ..reid import MODELS
        out += [k for k, m in MODELS.items() if m["weights"].exists()]
    except ImportError:
        pass
    return out


def default_methods(apps):
    """比べる方式の一覧（見た目の種類ごとに: 見た目だけ・時間＋見た目・学んだ時間＋見た目・学んだ時間＋見た目の階層クラスタリング）"""
    ms = ["none", "within", "time"]
    for a in apps:
        ms += [a, f"time+{a}", f"time*+{a}", f"hc:time*+{a}"]
    return ms


def link(run_dir, cameras=None, tracks_dir=None, apps=None, methods=None, best=None):
    """推論して採点し、mopf_eval/links.json・links.csv・links.png（best の方式の予測した組の切り出しの一覧）を書く。
    apps: 使う見た目の種類（"color"、twinsim.reid.MODELS の名前）。人物照合のモデルは torch が要る（uv run --group reid）。返り値: 結果の dict"""
    import time
    apps = tuple(apps or available_apps())
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    cams = cameras or [c for c in gt["cameras"] if (tdir / f"{c}.jsonl").exists()]
    sp = load_space(gt["space"])
    tracks = build_tracklets(run, gt, cams, tdir, f0, sp)
    timing = {}
    if apps and all((run / "video" / f"{c}.mp4").exists() for c in cams):
        timing = add_appearance(run, tracks, cams, apps)
    nulls = {a: n for a in apps if (n := app_null(tracks, a))}
    methods = [m for m in (methods or default_methods(apps)) if not (parse_method(m) or {}).get("app") or parse_method(m)["app"] in nulls]
    best = best if best in methods else next((m for m in methods if m == "time*+osnet_x0_25_msmt17"),
                                             next((m for m in reversed(methods) if m.startswith("time*+")), methods[-1]))
    geo = Geodesic(sp)
    M = truth_labels(run, gt, cams, tracks, tdir, f0)  # 採点だけに使う（推論には渡さない）
    hand = _handovers(run, cams, tracks_dir)
    results, preds, learned_all = {}, {}, {}
    for m in methods:
        t0 = time.perf_counter()
        opt = parse_method(m)
        learned = None
        if opt and opt["time"] == "learned":  # 1 回目（地図からの時間・1 対 1 の割り当て）で確からしい組を選び、ずれの分布を学んで 2 回目
            first = m.removeprefix("hc:").replace("time*", "time")
            _, _, cross1 = preds[first] if first in preds else predict(tracks, geo, nulls, first)
            learned = learn_time(cross1)
            learned_all[m] = {f"{a}->{b}": {"n": len(v), "median_s": round(float(np.median(v)), 2), "p10_s": round(float(np.percentile(v, 10)), 2),
                                            "p90_s": round(float(np.percentile(v, 90)), 2)} for (a, b), v in learned.items()}
        gids, within, cross = predict(tracks, geo, nulls, m, learned)
        results[m] = score(run, gt, cams, tracks, gids, cross, M, hand)
        results[m]["within_links"] = len(within)
        results[m]["seconds"] = round(time.perf_counter() - t0, 1)
        preds[m] = (gids, within, cross)
    gids, within, cross = preds[best]
    by = {t.key: t for t in tracks}
    out = {"cameras": cams, "method": best, "apps": list(apps), "app_null": nulls, "learned_time": learned_all, "timing": timing,
           "params": {"split_frames": SPLIT_FRAMES, "gap_within_s": GAP_WITHIN_S, "gap_cross_s": GAP_CROSS_S, "max_cost_within": MAX_COST_WITHIN,
                      "max_cost_cross": MAX_COST_CROSS, "n_crops": N_CROPS, "p_has": P_HAS, "detour_p": DETOUR_P, "kappa": KAPPA},
           "metrics": results,
           "tracklets": [{"key": t.key, "camera": t.camera, "mopf_id": t.mopf_id, "t0": round(t.t0, 2), "t1": round(t.t1, 2), "global_id": gids[t.key],
                          "speed": round(t.speed, 2), "n_crops": t.n_crops, "person": t.extra.get("person"), "purity": t.extra.get("purity")}
                         for t in sorted(tracks, key=lambda t: (t.camera, t.t0))],
           "within_links": within,
           "cross_links": sorted([{**c, "global_id": gids[c["from"]], "mopf_id_from": by[c["from"]].mopf_id, "mopf_id_to": by[c["to"]].mopf_id}
                                  for c in cross], key=lambda c: c["t_to"]),
           "missed_handovers": [h for h in hand if not any(c["correct"] and c["person_from"] == h["person"] and c["from_camera"] == h["from"]
                                                          for c in cross)],
           "note": "推論は MOPF の追跡・動画・空間の地図だけ。person・correct は正解による採点（推論には使っていない）"}
    ev = run / "mopf_eval"
    ev.mkdir(exist_ok=True)
    (ev / "links.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    import csv
    with open(ev / "links.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["global_id", "from_camera", "mopf_id_from", "t_from", "to_camera", "mopf_id_to", "t_to", "gap_s", "expected_s", "app_z",
                    "cost", "margin", "correct", "person_from", "person_to"])
        for c in out["cross_links"]:
            w.writerow([c["global_id"], c["from_camera"], c["mopf_id_from"], c["t_from"], c["to_camera"], c["mopf_id_to"], c["t_to"], c["gap"],
                        c.get("expected_s", ""), c.get("app_z", ""), c["cost"], c["margin"], c["correct"], c["person_from"], c["person_to"]])
    if any(t.thumb is not None for t in tracks):
        _sheet(ev / "links.png", out["cross_links"], by)
    return out


def _sheet(path, cross, by, cols=6):
    """予測したカメラの間の組を、確からしい順に、切り出し 2 枚（前のカメラ → 次のカメラ）と当たり・外れで並べる"""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype(config.FONT_CJK, 13)
    except OSError:
        font = ImageFont.load_default()
    items = sorted(cross, key=lambda c: -c["margin"])
    cw, ch = 2 * 48 + 24, 120 + 46
    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGB", (cols * cw, max(1, rows) * ch + 30), "white")
    d = ImageDraw.Draw(img)
    d.text((6, 6), "予測したカメラの間の組（確からしい順。左 = 前のカメラ、右 = 次のカメラ。○ = 正解と同じ人、× = 違う人）", font=font, fill=(30, 30, 30))
    for k, c in enumerate(items):
        x, y = (k % cols) * cw, 30 + (k // cols) * ch
        a, b = by[c["from"]], by[c["to"]]
        for i, t in enumerate((a, b)):
            if t.thumb is not None:
                img.paste(t.thumb, (x + 4 + i * 52, y + 4))
        col = (30, 140, 60) if c["correct"] else (200, 40, 40)
        d.rectangle([x + 2, y + 2, x + cw - 4, y + ch - 4], outline=col, width=3)
        d.text((x + 6, y + 126), f"{'○' if c['correct'] else '×'} {c['global_id']} 間 {c['gap']} 秒", font=font, fill=col)
        d.text((x + 6, y + 142), f"ID {a.mopf_id}→{b.mopf_id} 余裕 {c['margin']}", font=font, fill=(60, 60, 60))
    img.save(path)


def link_video(run_dir, tracks_dir=None):
    """links.json の予測で、2 台を並べた動画 mopf_eval/sync_pred.mp4 を作る（CPU、5 分の動画 2 台で 3〜4 分）"""
    from .identity import sync_video
    run = open_run(run_dir)[0]
    pred = json.loads((run / "mopf_eval" / "links.json").read_text())
    return sync_video(run, pred["cameras"], tracks_dir, pred=pred)
