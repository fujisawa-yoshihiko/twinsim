"""MOPF の追跡を正解（mot/<カメラ>.txt）と比べる: MOTA・IDF1・ID の切り替わり（時刻つき）・再現率・適合率、人数の誤差、足元の床の上の位置のずれ。"""

import json

import numpy as np

from ..camera import Camera
from .io import IOU_MIN, VIS_MIN, ensure_ids, iou_matrix, load_mot_gt, load_tracks, open_run, tracks_dir_and_offset


def evaluate(run_dir, tracks_dir=None):
    import motmetrics as mm
    from scipy.optimize import linear_sum_assignment
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    ids = ensure_ids(run, gt)
    name_of = {v: k for k, v in ids.items()}
    res = {"run": str(run), "frame_offset": f0, "iou_min": IOU_MIN, "vis_min": VIS_MIN, "cameras": {}}
    for tp in sorted(tdir.glob("*.jsonl")):
        camn = tp.stem
        cam = Camera(gt["cameras"][camn])
        G = load_mot_gt(run / "mot" / f"{camn}.txt")
        T = load_tracks(tp)
        nframes = (max(T) + 1) if T else 0
        acc = mm.MOTAccumulator(auto_id=False)
        cnt_err, foot_err = [], []
        for k in range(nframes):
            f = f0 + k
            g = G.get(f, [])
            gv = [x for x in g if x[5] >= VIS_MIN]
            gi = [x for x in g if x[5] < VIS_MIN]
            t = T.get(k, [])
            # 見えている正解のどれとも対応しえない検出で、見えていない正解の枠と重なるものは、誤検出にしない（数えない）
            if gi and t:
                mi = iou_matrix([x[1:5] for x in t], [x[1:5] for x in gi]).max(1)
                mv = iou_matrix([x[1:5] for x in t], [x[1:5] for x in gv]).max(1) if gv else np.zeros(len(t))
                t = [x for x, a, b in zip(t, mi, mv) if not (a >= IOU_MIN and b < IOU_MIN)]
            d = 1 - iou_matrix([x[1:5] for x in gv], [x[1:5] for x in t]) if gv and t else np.empty((len(gv), len(t)))
            d = np.where(d > 1 - IOU_MIN, np.nan, d)
            acc.update([x[0] for x in gv], [x[0] for x in t], d, frameid=k)
            cnt_err.append(len(t) - len(gv))
            if gv and t:  # 足元の床の上の位置のずれ（対応した組）
                c = np.nan_to_num(d, nan=9.0)
                r, cidx = linear_sum_assignment(c)
                for i, j in zip(r, cidx):
                    if c[i, j] > 1 - IOU_MIN:
                        continue
                    b = t[j]
                    q = cam.floor_point((b[1] + b[3]) / 2, b[4])
                    if gv[i][0] not in name_of:
                        continue
                    tr = gt["tracks"][name_of[gv[i][0]]]
                    p = gt["people"][name_of[gv[i][0]]]
                    kk = f - p["start_frame"]
                    if q is not None and 0 <= kk < len(tr):
                        foot_err.append(float(np.hypot(q[0] - tr[kk][0], q[1] - tr[kk][1])))
        mh = mm.metrics.create()
        s = mh.compute(acc, metrics=["mota", "idf1", "num_switches", "recall", "precision", "num_unique_objects", "num_false_positives", "num_misses"],
                       name=camn)
        row = {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else int(v)) for k, v in s.iloc[0].items()}
        ev = acc.mot_events
        sw = ev[ev.Type == "SWITCH"].reset_index()
        row["switches"] = [{"t_s": round((f0 + int(r.FrameId)) / gt["fps"], 2), "frame": f0 + int(r.FrameId),
                            "person": name_of.get(int(r.OId)), "mopf_id": int(r.HId)} for r in sw.itertuples()][:300]
        row.update({"frames": nframes, "track_ids": len({x[0] for v in T.values() for x in v}),
                    "count_error_mean": round(float(np.mean(cnt_err)), 3) if cnt_err else None,
                    "count_mae": round(float(np.mean(np.abs(cnt_err))), 3) if cnt_err else None,
                    "foot_error_m_median": round(float(np.median(foot_err)), 3) if foot_err else None,
                    "foot_error_m_p90": round(float(np.percentile(foot_err, 90)), 3) if foot_err else None})
        res["cameras"][camn] = row
    out = run / "mopf_eval"
    out.mkdir(exist_ok=True)
    (out / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res
