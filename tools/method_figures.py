"""仕組みの説明のページ（docs/methods.md）の図を、結果（MOPF の追跡と mopf-link の links.json）から作る。CPU だけ、1 分ほど。

  uv run python tools/method_figures.py [<結果の場所>] [--out docs/img/methods]

図ごとに、日本語・英語 × 明るい表示・暗い表示の 4 枚（<名前>_<ja|en>_<light|dark>.png）。GitHub は <picture> で表示を切り替える。
- path: 2 台の視野と、来るはずの時間の求め方（歩ける所の上の最短の道のり ÷ 歩く速さ）の例
- cues: 時間・向き・見た目の、それぞれの値から足す点数（対数尤度比、LLR）
- separation: トラックレットの組の点数の分布（同じ人・別の人）。手がかりを合わせると分かれる
- timeline: 2 台のトラックレットの時間の並びと、推論したつながり（○ 正しい・× 誤り）
色はデータの可視化の手引きの既定の配色（青・オレンジ、状態の緑・赤は ○・× と一緒に使う）。
"""

import argparse
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from PIL import Image  # noqa: E402

from twinsim import config  # noqa: E402
from twinsim.camera import Camera, camera_dict  # noqa: E402
from twinsim.mopf import linking as LK  # noqa: E402
from twinsim.mopf.io import open_run, tracks_dir_and_offset  # noqa: E402
from twinsim.space import load_space  # noqa: E402

THEMES = {
    "light": {"surface": "#fcfcfb", "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "s1": "#2a78d6", "s2": "#eb6834",
              "good": "#0ca30c", "bad": "#d03b3b", "photo_blend": 0.35},
    "dark": {"surface": "#1a1a19", "text": "#f0efec", "muted": "#c3c2b7", "grid": "#333331", "s1": "#3987e5", "s2": "#d95926",
             "good": "#0ca30c", "bad": "#d03b3b", "photo_blend": 0.55},
}
DPI = 150


def T(lang, ja, en):
    return ja if lang == "ja" else en


def style(th):
    font_manager.fontManager.addfont(str(config.FONT_CJK))
    name = font_manager.FontProperties(fname=str(config.FONT_CJK)).get_name()
    plt.rcParams.update({
        "font.family": name, "font.size": 10, "figure.facecolor": th["surface"], "axes.facecolor": th["surface"],
        "savefig.facecolor": th["surface"], "text.color": th["text"], "axes.labelcolor": th["muted"], "axes.edgecolor": th["grid"],
        "xtick.color": th["muted"], "ytick.color": th["muted"], "axes.grid": True, "grid.color": th["grid"], "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "axes.titlesize": 11, "axes.titlecolor": th["text"],
        "axes.titlelocation": "left", "axes.titleweight": "bold",
    })


# ---- データ ----

class Data:
    def __init__(self, run_dir):
        self.run, self.gt, f0 = open_run(run_dir)
        self.tdir, self.f0 = tracks_dir_and_offset(self.run, None, f0)
        self.sp = load_space(self.gt["space"])
        self.cams = ["CamGate", "CamEV"]
        self.links = json.loads((self.run / "mopf_eval/links.json").read_text())
        self.tracks = LK.build_tracklets(self.run, self.gt, self.cams, self.tdir, self.f0, self.sp)
        self.by = {t.key: t for t in self.tracks}
        self.geo = LK.Geodesic(self.sp)
        LK.truth_labels(self.run, self.gt, self.cams, self.tracks, self.tdir, self.f0)  # 図の「同じ人・別の人」の色分けだけに使う
        self.kind = "osnet_x0_25_msmt17"
        LK.add_appearance(self.run, self.tracks, self.cams, (self.kind,))
        self.null = LK.app_null(self.tracks, self.kind)

    def path(self, a, b):
        """床の a → b の、歩ける所の上の最短の道（世界の座標の列）。"""
        from scipy.sparse.csgraph import dijkstra
        na, nb = self.geo.node(a), self.geo.node(b)
        _, pred = dijkstra(self.geo.graph, directed=False, indices=na, return_predecessors=True)
        ii, jj = np.nonzero(self.sp.grid)
        out, n = [], nb
        while n >= 0 and n != na:
            out.append((self.sp.x0 + jj[n] * self.sp.res, self.sp.y0 + ii[n] * self.sp.res))
            n = pred[n]
        out.append((self.sp.x0 + jj[na] * self.sp.res, self.sp.y0 + ii[na] * self.sp.res))
        return np.array(out[::-1])

    def pairs(self):
        """カメラの間の候補の組（トラックレットの終わり → 別のカメラのトラックレットの始まり、90 秒以内）の点数と、同じ人か。"""
        out = []
        for a in self.tracks:
            for b in self.tracks:
                if a.camera == b.camera:
                    continue
                p = LK.cost_cross(a, b, a.feats.get(self.kind), b.feats.get(self.kind), self.geo, self.null, "map", self.kind)
                if p is None or "llr_app" not in p:
                    continue
                pa, pb = a.extra.get("person_end"), b.extra.get("person_start")
                if pa is None or pb is None:
                    continue
                out.append((p["llr_time"] + p["llr_dir"], p["llr_app"], p["llr"], pa == pb))
        return np.array([o[:3] for o in out]), np.array([o[3] for o in out])


# ---- 図 ----

def fig_path(D, lang, th, out):
    sp, gt = D.sp, D.gt
    lv = sp.spec["levels"][0]
    tv = lv["top_view"]
    top = Camera(camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"]))
    P = lambda pts: top.project([(x, y, 0.0) for x, y in pts])[0]
    img = Image.open(sp.folder / lv["top_image"]).convert("RGB")
    img = Image.blend(img, Image.new("RGB", img.size, th["surface"]), th["photo_blend"])
    # 例: 正しくつないだゲート → EV 前の組のうち、来るはずの時間に近いもの
    ok = [c for c in D.links["cross_links"] if c["correct"] and c["from_camera"] == "CamGate" and c["to_camera"] == "CamEV"
          and -6 <= D.by[c["from"]].end[0] <= 0 and 6 <= D.by[c["from"]].end[1] <= 12]  # ゲートのカメラの手前で追跡が終わった組
    c = min(ok, key=lambda c: abs(c["time_z"]))
    a, b = D.by[c["from"]], D.by[c["to"]]
    path = D.path(a.end, b.start)
    fig, ax = plt.subplots(figsize=(7.2, 6.4))
    lo, hi = P([(-16.5, -7.5), (1.5, 19.0)])
    x0, x1 = sorted((lo[0], hi[0]))
    y0, y1 = sorted((lo[1], hi[1]))
    ax.imshow(img)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y1, y0)
    ax.axis("off")
    # カメラに映る床（2 台）。視野は重ならない
    grid = [(x, y) for x in np.arange(-16.5, 1.5, 0.5) for y in np.arange(-7.5, 19.0, 0.5) if sp.walkable(x, y)]
    for cam, col, ja, en in (("CamGate", th["s1"], "ゲートのカメラに映る床", "Floor seen by the gate camera"),
                             ("CamEV", th["s2"], "EV 前のカメラに映る床", "Floor seen by the elevator-hall camera")):
        C = Camera(gt["cameras"][cam])
        pts = [p for p in grid if C.sees_floor(sp, *p)]
        uv = P(pts)
        ax.scatter(uv[:, 0], uv[:, 1], s=7, color=col, alpha=0.55, linewidths=0, label=T(lang, ja, en))
        e = P([gt["cameras"][cam]["eye"][:2]])[0]
        ax.scatter([e[0]], [e[1]], s=60, marker="s", color=col, edgecolors=th["surface"], linewidths=1.5, zorder=5)
        ax.annotate(cam, e, xytext=(6, -8), textcoords="offset points", color=th["text"], fontsize=9, fontweight="bold")
    uv = P(path)
    ax.plot(uv[:, 0], uv[:, 1], color=th["text"], lw=2.2, solid_capstyle="round", zorder=6,
            label=T(lang, "歩ける所の上の最短の道", "Shortest walkable path"))
    s, e = P([tuple(a.end)])[0], P([tuple(b.start)])[0]
    ax.plot([s[0], e[0]], [s[1], e[1]], color=th["muted"], lw=1.2, ls=(0, (3, 3)), zorder=5, label=T(lang, "直線（使わない）", "Straight line (not used)"))
    for p, ja, en, dx in ((s, "ゲートで追跡が終わった所", "Track ends (gate)", 8), (e, "EV 前で追跡が始まった所", "Track starts (elevator hall)", 8)):
        ax.scatter([p[0]], [p[1]], s=70, color=th["text"], edgecolors=th["surface"], linewidths=2, zorder=7)
        ax.annotate(T(lang, ja, en), p, xytext=(dx, 6), textcoords="offset points", color=th["text"], fontsize=9,
                    bbox={"boxstyle": "round,pad=0.25", "fc": th["surface"], "ec": "none", "alpha": 0.85})
    v = c["dist_m"] / c["expected_s"]
    txt = T(lang, f"道のり {c['dist_m']:.1f} m ÷ 歩く速さ {v:.2f} m/s\n= 来るはずの時間 {c['expected_s']:.1f} 秒\n実際の間 {c['gap']:.1f} 秒",
            f"Path {c['dist_m']:.1f} m ÷ walking speed {v:.2f} m/s\n= expected time {c['expected_s']:.1f} s\nActual gap {c['gap']:.1f} s")
    ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=10, color=th["text"], va="bottom",
            bbox={"boxstyle": "round,pad=0.5", "fc": th["surface"], "ec": th["grid"]})
    ax.legend(loc="upper left", fontsize=8.5, markerscale=2, facecolor=th["surface"], framealpha=0.85, frameon=True, edgecolor=th["grid"])
    ax.set_title(T(lang, "来るはずの時間: 床の地図の上の最短の道のり ÷ 歩く速さ", "Expected time: shortest path on the floor map ÷ walking speed"))
    fig.tight_layout()
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def fig_cues(lang, th, out):
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.3))
    window = LK.GAP_CROSS_S + LK.OVERLAP_S
    exp = 10.0
    g = np.linspace(0, 40, 400)
    axs[0].plot(g, [LK.llr_time(x, exp, window)[0] for x in g], color=th["s1"], lw=1.8)
    axs[0].axvline(exp, color=th["muted"], lw=1, ls=(0, (2, 2)))
    axs[0].annotate(T(lang, "来るはずの時間\n（例 10 秒）", "Expected time\n(e.g. 10 s)"), (exp, 4.8), xytext=(6, 0), textcoords="offset points",
                    fontsize=8.5, color=th["muted"], va="top")
    axs[0].annotate(T(lang, "早すぎる → 強く罰する", "Too early →\nstrong penalty"), (4, -5.6), fontsize=8.5, color=th["muted"])
    axs[0].annotate(T(lang, "遅い（寄り道）→\n弱く罰する", "Late (detour) →\nmild penalty"), (22, -0.5), fontsize=8.5, color=th["muted"])
    axs[0].set_xlabel(T(lang, "実際の間（秒）", "Actual gap (s)"))
    axs[0].set_title(T(lang, "時間", "Time"))
    cs = np.linspace(-1, 1, 200)
    axs[1].plot(cs, [LK.llr_dir(x) for x in cs], color=th["s1"], lw=1.8)
    axs[1].set_xlabel(T(lang, "歩く向きと相手の方向の cos", "cos(walking direction,\ndirection to the other camera's track)"))
    axs[1].annotate(T(lang, "相手の方へ\n歩いている →", "Walking toward\nthe other →"), (-0.95, 2.2), fontsize=8.5, color=th["muted"])
    axs[1].set_title(T(lang, "向き（追跡の終わり・始まり、それぞれ）", "Direction (at each end)"))
    zs = np.linspace(-4, 3, 300)
    axs[2].plot(zs, [_llr_app_z(z) for z in zs], color=th["s1"], lw=1.8)
    axs[2].set_xlabel(T(lang, "見た目の似ていなさ z\n（別の人どうしの分布で標準化）", "Appearance distance z\n(standardized by pairs of different people)"))
    axs[2].annotate(T(lang, "← 別の人どうしより似ている", "← More similar than\ndifferent people"), (-1.3, 4.3), fontsize=8.5, color=th["muted"])
    axs[2].set_title(T(lang, "見た目（OSNet など）", "Appearance (OSNet etc.)"))
    for ax in axs:
        ax.axhline(0, color=th["muted"], lw=0.8)
        ax.set_ylim(-6.5, 6.5)
    axs[0].set_ylabel(T(lang, "足す点数（LLR）", "Score added (LLR)"))
    fig.tight_layout()
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def _llr_app_z(z):
    """llr_app と同じ式（似ていなさの z から）。"""
    v = -math.log(max(math.erfc(-z / math.sqrt(2)), 1e-12)) if z < 0 else -z
    return float(np.clip(v, -LK.LLR_MAX, LK.LLR_MAX))


def fig_separation(D, lang, th, out, X, same):
    prior = float(np.median([c["prior"] for c in D.links["cross_links"]]))
    fig, axs = plt.subplots(1, 3, figsize=(10.5, 3.4), sharey=False)
    bins = np.linspace(-14, 14, 57)
    titles = (T(lang, "時間＋向き", "Time + direction"), T(lang, "見た目（OSNet x0.25）", "Appearance (OSNet x0.25)"),
              T(lang, "合計（つなぐかを決める点数）", "Total (decides the link)"))
    for k, ax in enumerate(axs):
        for mask, col, ja, en in ((same, th["s1"], "同じ人", "Same person"), (~same, th["s2"], "別の人", "Different people")):
            x = np.clip(X[mask, k], -13.9, 13.9)
            ax.hist(x, bins=bins, density=True, histtype="step", lw=1.8, color=col,
                    label=f"{T(lang, ja, en)}（{mask.sum()}）" if lang == "ja" else f"{en} ({mask.sum()})")
        ax.set_title(titles[k])
        ax.set_xlabel("LLR")
    axs[2].axvline(-prior, color=th["text"], lw=1.2, ls=(0, (3, 2)))
    axs[2].annotate(T(lang, f"つなぐ基準\n（{-prior:.1f} 以上）→", f"Link threshold\n(≥ {-prior:.1f}) →"), (-prior, axs[2].get_ylim()[1] * 0.97),
                    xytext=(-5, 0), textcoords="offset points", fontsize=8.5, color=th["text"], va="top", ha="right")
    axs[0].set_ylabel(T(lang, "割合（密度）", "Share (density)"))
    axs[0].legend(loc="upper left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def fig_timeline(D, lang, th, out, t0=250.0, t1=300.0):
    tl = [t for t in D.links["tracklets"] if t["t1"] >= t0 and t["t0"] <= t1]
    rows, y, lane_top = {}, 0, {}
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    yticks, ylabels = [], []
    for cam, ja, en in (("CamGate", "ゲート", "Gate"), ("CamEV", "EV 前", "Elevator hall")):
        ts = sorted([t for t in tl if t["camera"] == cam], key=lambda t: t["t0"])
        ends = []
        lane_top[cam] = y
        for t in ts:
            r = next((i for i, e in enumerate(ends) if e < t["t0"] - 0.3), None)
            if r is None:
                ends.append(t["t1"])
                r = len(ends) - 1
            else:
                ends[r] = t["t1"]
            rows[t["key"]] = y + r
        yticks.append(y + (len(ends) - 1) / 2)
        ylabels.append(T(lang, ja, en))
        y += len(ends) + 2
    for t in tl:
        r = rows[t["key"]]
        ax.plot([max(t["t0"], t0), min(t["t1"], t1)], [r, r], color=th["muted"], lw=3, solid_capstyle="round", alpha=0.75)
    for w in D.links["within_links"]:
        a, b = D.by.get(w["from"]), D.by.get(w["to"])
        if a and b and w["from"] in rows and w["to"] in rows and t0 <= a.t1 <= t1:
            ax.plot([a.t1, b.t0], [rows[w["from"]], rows[w["to"]]], color=th["muted"], lw=1, ls=(0, (2, 2)))
    n_ok = n_bad = 0
    for c in D.links["cross_links"]:
        if c["from"] in rows and c["to"] in rows and t0 <= c["t_from"] <= t1 and t0 <= c["t_to"] <= t1:
            col = th["good"] if c["correct"] else th["bad"]
            ya, yb = rows[c["from"]], rows[c["to"]]
            ax.annotate("", (c["t_to"], yb), (c["t_from"], ya), arrowprops={"arrowstyle": "-|>", "color": col, "lw": 1.4, "shrinkA": 2, "shrinkB": 2})
            f = 0.3 + 0.4 * ((n_ok + n_bad) % 3) / 2  # 印の位置を矢印ごとに少しずらして重なりを減らす
            mx, my = c["t_from"] + f * (c["t_to"] - c["t_from"]), ya + f * (yb - ya)
            ax.text(mx, my, "○" if c["correct"] else "×", fontsize=8, color=th["text"], ha="center", va="center", fontweight="bold",
                    bbox={"boxstyle": "circle,pad=0.12", "fc": th["surface"], "ec": col, "lw": 1})
            n_ok += c["correct"]
            n_bad += not c["correct"]
    ax.set_yticks(yticks, ylabels)
    ax.invert_yaxis()
    ax.set_xlim(t0, t1)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(T(lang, "映像の時刻（秒）", "Video time (s)"))
    ax.set_title(T(lang, f"トラックレットとカメラの間のつながり（{t0:.0f}〜{t1:.0f} 秒、○ 正しい {n_ok}・× 誤り {n_bad}）",
                   f"Tracklets and cross-camera links ({t0:.0f}–{t1:.0f} s, ○ correct {n_ok}, × wrong {n_bad})"))
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=th["muted"], lw=3, label=T(lang, "トラックレット（MOPF の ID のひと続き）", "Tracklet (a run of one MOPF ID)")),
               Line2D([], [], color=th["muted"], lw=1, ls=(0, (2, 2)), label=T(lang, "カメラの中のつながり", "Link within a camera")),
               Line2D([], [], color=th["good"], lw=1.4, label=T(lang, "カメラの間のつながり ○ 正しい", "Cross-camera link ○ correct")),
               Line2D([], [], color=th["bad"], lw=1.4, label=T(lang, "カメラの間のつながり × 誤り", "Cross-camera link × wrong"))]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, -0.32), ncol=2, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(out, dpi=DPI)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", nargs="?", default=str(config.RUNS / "office_gate_ev"))
    ap.add_argument("--out", default="docs/img/methods")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    D = Data(a.run)
    X, same = D.pairs()
    for theme, th in THEMES.items():
        style(th)
        for lang in ("ja", "en"):
            fig_path(D, lang, th, out / f"path_{lang}_{theme}.png")
            fig_cues(lang, th, out / f"cues_{lang}_{theme}.png")
            fig_separation(D, lang, th, out / f"separation_{lang}_{theme}.png", X, same)
            fig_timeline(D, lang, th, out / f"timeline_{lang}_{theme}.png")
    print("組", len(same), "同じ人", int(same.sum()), "→", out)


if __name__ == "__main__":
    main()
