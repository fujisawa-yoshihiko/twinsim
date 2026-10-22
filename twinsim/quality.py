"""計算の結果の確かめ（妥当性の最初の目安）: 壁の中に入ったコマ、人どうしの近さ、歩く速さの分布、止まる時間、状態とゾーン。
使い方: python -m twinsim check <結果の場所>
"""

import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .space import load_space


def check(run_dir):
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    sp = load_space(gt["space"])
    fps = gt["fps"]
    rows = list(csv.DictReader(gzip.open(run / "frames.csv.gz", "rt")))
    bad = sum(1 for r in rows if not sp.walkable(float(r["x"]), float(r["y"])))
    byf = defaultdict(list)
    for r in rows:
        byf[int(r["frame"])].append((float(r["x"]), float(r["y"]), r["group"]))
    near = []
    for f, pts in byf.items():
        if len(pts) < 2:
            continue
        P = np.array([p[:2] for p in pts])
        D = np.linalg.norm(P[:, None] - P[None], axis=2)
        g = [p[2] for p in pts]
        same = np.array([[bool(gi) and gi == gj for gj in g] for gi in g])
        D = np.where(same | np.eye(len(P), dtype=bool), 99, D)
        near.append(D.min())
    near = np.array(near) if near else np.array([99.0])
    speeds = []
    for name, tr in gt["tracks"].items():
        mv = gt["moving"][name]
        xy = np.array([t[:2] for t in tr])
        if len(xy) > fps:
            v = np.linalg.norm(xy[fps:] - xy[:-fps], axis=1)
            m = np.array(mv[fps:], bool) & np.array(mv[:-fps], bool)
            if m.any():
                speeds.append(float(np.median(v[m])))
    stops = Counter()
    for p in gt["people"].values():
        for s0, s1, st in p["states"]:
            if st not in ("pass", "ev_approach", "alight"):
                stops[st] += (s1 - s0 + 1) / fps
    res = {"rows": len(rows), "not_walkable_frac": round(bad / max(len(rows), 1), 5),
           "closest_non_group_pair_m": {"p1": round(float(np.percentile(near, 1)), 2), "p5": round(float(np.percentile(near, 5)), 2),
                                        "median": round(float(np.median(near)), 2), "frames_below_0.4m": round(float((near < 0.4).mean()), 4)},
           "walking_speed_m_s": {"median": round(float(np.median(speeds)), 2), "p10": round(float(np.percentile(speeds, 10)), 2),
                                 "p90": round(float(np.percentile(speeds, 90)), 2)} if speeds else None,
           "stop_seconds_by_state": {k: round(v, 1) for k, v in stops.most_common()},
           "state_zone_top": Counter(f"{r['state']}@{r['zone'] or '-'}" for r in rows).most_common(12)}
    return res
