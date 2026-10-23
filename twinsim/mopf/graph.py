"""中間層のグラフ: MOPF の追跡（画素）→ 足元 → 床の上の位置 → ゾーンの人数（秒ごと）・ゾーン間の移動（1 分ごと）を、
シミュレータの graph/ と同じ形で mopf_graph/<カメラ>/ に書き、正解のグラフと比べる（映像からでもシミュレータからでも同じ形）。"""

import csv
import json
from collections import Counter, defaultdict

import numpy as np

from ..camera import Camera
from ..space import load_space
from .io import load_tracks, open_run, tracks_dir_and_offset


def floor_tracks(gt, camn, T, f0):
    """MOPF の追跡 → {シミュレータのコマ: [(ID, x, y), ...]}（足元を床に移す）"""
    cam = Camera(gt["cameras"][camn])
    out = defaultdict(list)
    for k, rows in T.items():
        for tid, x0, _y0, x1, y1 in rows:
            q = cam.floor_point((x0 + x1) / 2, y1)
            if q is not None:
                out[f0 + k].append((tid, q[0], q[1]))
    return out


def graph(run_dir, tracks_dir=None, coverage_min=0.6):
    """MOPF の追跡から、シミュレータの graph/ と同じ形のゾーンの人数・移動を作り、正解と比べる。
    比べるのは、カメラから床の coverage_min 以上が見えるゾーンだけ（graph.json の observed）。"""
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    sp = load_space(gt["space"])
    fps = gt["fps"]
    obs = json.loads((run / "graph/graph.json").read_text())["observed"]
    zones = list(sp.zones)
    G = {}
    for tp in sorted(tdir.glob("*.jsonl")):
        camn = tp.stem
        T = load_tracks(tp)
        F = floor_tracks(gt, camn, T, f0)
        if not F:
            continue
        frames = range(f0, f0 + max(T) + 1)
        seen_z = [z for z, c in obs.get(camn, {}).get("zones", {}).items() if c >= coverage_min]
        out = run / "mopf_graph" / camn
        out.mkdir(parents=True, exist_ok=True)
        secs = sorted({f // fps for f in frames})
        # 秒ごとのゾーンの人数（その秒の最初のコマ）。正解は同じコマの全員（ゾーンの中にいる人）
        rows_m, rows_g = [], []
        for t in secs:
            f = min(max(t * fps, frames.start), frames.stop - 1)
            cm = Counter(sp.zone_of(x, y) for _, x, y in F.get(f, []))
            cg = Counter()
            for n, p in gt["people"].items():
                kk = f - p["start_frame"]
                tr = gt["tracks"][n]
                if 0 <= kk < len(tr):
                    cg[sp.zone_of(tr[kk][0], tr[kk][1])] += 1
            rows_m.append([t] + [cm.get(z, 0) for z in zones])
            rows_g.append([t] + [cg.get(z, 0) for z in zones])
        with open(out / "zone_counts.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["t"] + zones)
            w.writerows(rows_m)
        # 1 分ごとのゾーン間の移動（同じ ID のゾーンが変わったら 1 回）
        last, flows = {}, Counter()
        for f in sorted(F):
            for tid, x, y in F[f]:
                z = sp.zone_of(x, y)
                if z and tid in last and last[tid] != z:
                    flows[(f // fps // 60, last[tid], z)] += 1
                if z:
                    last[tid] = z
        with open(out / "zone_flows.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["minute", "source", "target", "count"])
            for (m, a, b), c in sorted(flows.items()):
                w.writerow([m, a, b, c])
        zi = {z: i + 1 for i, z in enumerate(zones)}
        cmp = {}
        for z in seen_z:
            m = np.array([r[zi[z]] for r in rows_m], float)
            g = np.array([r[zi[z]] for r in rows_g], float)
            cmp[z] = {"coverage": obs[camn]["zones"][z], "mean_mopf": round(float(m.mean()), 2), "mean_truth": round(float(g.mean()), 2),
                      "mae": round(float(np.abs(m - g).mean()), 2)}
        G[camn] = {"seconds": len(secs), "zones_compared": cmp, "flows": len(flows), "files": [str(out / "zone_counts.csv"), str(out / "zone_flows.csv")]}
    (run / "mopf_graph").mkdir(exist_ok=True)
    (run / "mopf_graph" / "summary.json").write_text(json.dumps(G, ensure_ascii=False, indent=1))
    return G
