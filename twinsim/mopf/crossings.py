"""人流モニターの線とエリアの数え方（MOPF の live_monitor.py と同じ決まり）: 正解なら数えるはずの値、MOPF の追跡で横切った出来事、その突き合わせ。"""

import json
from collections import defaultdict

import numpy as np

from ..camera import Camera
from .io import VIS_MIN, ensure_ids, load_mot_gt, load_tracks, open_run, tracks_dir_and_offset

LINE_MARGIN_PX = 8.0  # MOPF の人流モニター（live_monitor.py）と同じ


def _side(a, b, p, w, h):
    ax, ay, bx, by = a[0] * w, a[1] * h, b[0] * w, b[1] * h
    d = ((bx - ax) * (p[1] * h - ay) - (by - ay) * (p[0] * w - ax)) / max(float(np.hypot(bx - ax, by - ay)), 1e-9)
    return 0 if abs(d) < LINE_MARGIN_PX else (1 if d > 0 else -1)


def _cross(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _segx(p1, p2, a, b):
    return _cross(a, b, p1) * _cross(a, b, p2) < 0 and _cross(p1, p2, a) * _cross(p1, p2, b) < 0


def _inside(poly, p):
    x, y = p
    ins = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            ins = not ins
    return ins


def expect(run_dir, camera, frames=None, vis_min=VIS_MIN, config=None):
    """mopf/<カメラ>/config.json の線とエリアで、正解の足元（見えている人だけ）から MOPF と同じ決まりで数える。
    frames=(始まり, 終わり)（シミュレータのコマ）。既定は描いた範囲（render_log.json）、なければ全部。"""
    run, gt, f0 = open_run(run_dir)
    cfg = config or json.loads((run / "mopf" / camera / "config.json").read_text())
    rl = run / "render_log.json"
    a, b = frames or (json.loads(rl.read_text())["frames"] if rl.exists() else (0, gt["total_frames"] - 1))
    cam = Camera(gt["cameras"][camera])
    W, H = cam.w, cam.h
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    ids = ensure_ids(run, gt)
    name_of = {v: k for k, v in ids.items()}
    side = defaultdict(dict)
    counts = [{"name": ln["name"], "to_pos": 0, "to_neg": 0, "pos_label": ln.get("pos_label"), "neg_label": ln.get("neg_label")} for ln in cfg["lines"]]
    zone_people = [set() for _ in cfg["zones"]]
    events = []
    peak = 0
    for f in range(a, b + 1):
        vis = [x for x in G.get(f, []) if x[5] >= vis_min]
        peak = max(peak, len(vis))
        for pid, *_ in vis:
            if pid not in name_of:
                continue
            n = name_of[pid]
            p = gt["people"][n]
            kk = f - p["start_frame"]
            tr = gt["tracks"][n]
            if not 0 <= kk < len(tr):
                continue
            uv, d = cam.project([(tr[kk][0], tr[kk][1], 0.0)])
            foot = (float(uv[0][0]) / W, float(uv[0][1]) / H)
            for k, ln in enumerate(cfg["lines"]):
                s = _side(ln["a"], ln["b"], foot, W, H)
                if s == 0:
                    continue
                last = side[pid].get(k)
                if last is not None and last[0] != s and _segx(last[1], foot, ln["a"], ln["b"]):
                    counts[k]["to_pos" if s > 0 else "to_neg"] += 1
                    events.append({"line": k, "dir": "to_pos" if s > 0 else "to_neg", "frame": f, "person": n})
                side[pid][k] = (s, foot)
            for k, z in enumerate(cfg["zones"]):
                if _inside(z["points"], foot):
                    zone_people[k].add(pid)
    out = {"camera": camera, "frames": [int(a), int(b)], "seconds": round((b - a + 1) / gt["fps"], 1), "lines": counts,
           "zones": [{"name": z["name"], "people_entered": len(s)} for z, s in zip(cfg["zones"], zone_people)],
           "max_people_in_view": peak, "events": events,
           "rule": "MOPF の人流モニターと同じ（足元・線から 8 画素・線分の交差）。見えている割合 0.4 以上の人だけ"}
    if config is None:
        (run / "mopf" / camera / "expected.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def track_crossings(run_dir, camera, tracks_dir=None, config=None):
    """MOPF の追跡（足元）が線を横切った出来事（人流モニターと同じ決まり）。frame はシミュレータのコマ。"""
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    cfg = config or json.loads((run / "mopf" / camera / "config.json").read_text())
    W, H = gt["cameras"][camera]["width"], gt["cameras"][camera]["height"]
    T = load_tracks(tdir / f"{camera}.jsonl")
    side, events = defaultdict(dict), []
    for k in sorted(T):
        for tid, x0, _y0, x1, y1 in T[k]:
            foot = ((x0 + x1) / 2 / W, y1 / H)
            for i, ln in enumerate(cfg["lines"]):
                sd = _side(ln["a"], ln["b"], foot, W, H)
                if sd == 0:
                    continue
                last = side[tid].get(i)
                if last is not None and last[0] != sd and _segx(last[1], foot, ln["a"], ln["b"]):
                    events.append({"line": i, "dir": "to_pos" if sd > 0 else "to_neg", "frame": f0 + k, "mopf_id": tid})
                side[tid][i] = (sd, foot)
    return events


def compare_crossings(run_dir, camera, tracks_dir=None, window_s=1.5):
    """正解なら横切る出来事と MOPF の出来事を、同じ線・同じ向き・window_s 秒以内で 1 対 1 に対応づける → 数えもらし・余分。"""
    run, gt, f0 = open_run(run_dir)
    exp = expect(run, camera)["events"]
    got = track_crossings(run, camera, tracks_dir)
    w = window_s * gt["fps"]
    used, missed = set(), []
    for e in sorted(exp, key=lambda e: e["frame"]):
        cand = [(abs(g["frame"] - e["frame"]), j) for j, g in enumerate(got)
                if j not in used and g["line"] == e["line"] and g["dir"] == e["dir"] and abs(g["frame"] - e["frame"]) <= w]
        if cand:
            used.add(min(cand)[1])
        else:
            missed.append({**e, "t_s": round(e["frame"] / gt["fps"], 2)})
    extra = [{**g, "t_s": round(g["frame"] / gt["fps"], 2)} for j, g in enumerate(got) if j not in used]
    out = {"camera": camera, "expected": len(exp), "mopf": len(got), "matched": len(used), "missed": missed, "extra": extra}
    (run / "mopf_eval").mkdir(exist_ok=True)
    (run / "mopf_eval" / f"{camera}_crossings.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out
