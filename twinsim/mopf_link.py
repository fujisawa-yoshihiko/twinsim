"""MOPF（~/MOPF_ALL_video）との連携: 描いた動画を MOPF で検出・追跡し、シミュレータの正解と比べる。MOPF の追跡から中間層のグラフを作る。

  process   video/<カメラ>.mp4 を MOPF の uploads に写し、検出・追跡を頼む（MOPF が動いているときだけ。GPU を使う）。
            結果（tracking.jsonl）を mopf_tracks/<カメラ>.jsonl に写す
  evaluate  mopf_tracks と正解（mot/<カメラ>.txt）を比べる: MOTA・IDF1・ID の切り替わり・再現率・適合率、人数の誤差、足元の床の上の位置のずれ
  graph     MOPF の追跡（画素）→ 足元 → 床の上の位置 → ゾーンの人数（秒ごと）・ゾーン間の移動（1 分ごと）を、
            シミュレータの graph/ と同じ形で mopf_graph/<カメラ>/ に書き、正解のグラフと比べる（中間層: 映像からでもシミュレータからでも同じ形）
  expect    人流モニターに送る設定（mopf/<カメラ>/config.json）で、正解の足元が線を横切る回数・エリアに入った人数を、MOPF と同じ決まりで数える
動画の 0 コマ目はシミュレータの render_log.json の frames[0]（試し撮りなら途中から）。
"""

import csv
import json
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .camera import Camera
from .space import load_space

MOPF = Path.home() / "MOPF_ALL_video/MOPF_CV_Native"
CV = "http://127.0.0.1:8010"
IOU_MIN = 0.3   # 正解の枠は人を囲む箱から作った近似なので 0.3 で対応づける（research/sim-cctv/evaluate.py と同じ）
VIS_MIN = 0.4   # これより見えていない正解の枠は、見逃しにも誤検出にも数えない
LINE_MARGIN_PX = 8.0  # MOPF の人流モニター（live_monitor.py）と同じ


def _run(run_dir):
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    rl = run / "render_log.json"
    f0 = json.loads(rl.read_text())["frames"][0] if rl.exists() else 0
    return run, gt, int(f0)


# ---- MOPF で処理する ----
def _get(url, timeout=10):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def mopf_ready(base=CV):
    try:
        urllib.request.urlopen(f"{base}/api/video/list", timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def process(run_dir, cameras=None, model="yolo11m", base=CV, poll=5, wait_s=3600):
    run, gt, f0 = _run(run_dir)
    if not mopf_ready(base):
        raise RuntimeError("MOPF が動いていない（cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --no-llm --no-vc3。GPU は確認を取ってから）")
    vids = sorted((run / "video").glob("*.mp4"))
    if cameras:
        vids = [v for v in vids if v.stem in cameras]
    if not vids:
        raise ValueError(f"{run}/video に動画がない（先に render）")
    (run / "mopf_tracks").mkdir(exist_ok=True)
    done = {}
    for v in vids:
        name = f"twinsim-{run.name}-{v.stem}.mp4"
        shutil.copy(v, MOPF / "uploads" / name)
        req = urllib.request.Request(f"{base}/api/video/process/{name}?model_name={model}", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=30).read()
        t0 = time.time()
        while True:
            st = _get(f"{base}/api/video/status/{name}")
            if st.get("status") not in ("queued", "processing"):
                break
            if time.time() - t0 > wait_s:
                raise TimeoutError(f"{name}: {wait_s} 秒たっても終わらない")
            time.sleep(poll)
        src = MOPF / "outputs/uploads" / Path(name).stem / "tracking.jsonl"
        if not src.exists():
            raise RuntimeError(f"{name}: 結果がない（状態 {st}）")
        shutil.copy(src, run / "mopf_tracks" / f"{v.stem}.jsonl")
        done[v.stem] = {"status": st.get("status"), "model": model, "seconds": round(time.time() - t0, 1), "mopf_name": name}
    (run / "mopf_tracks" / "info.json").write_text(json.dumps({"frame_offset": f0, "videos": done}, ensure_ascii=False, indent=1))
    return done


def ensure_ids(run, gt):
    """mot/ids.json（枠の番号 → 人）がない古い結果では、枠の位置から作り直す（番号ごとに最初の枠と、そのコマの人の枠の IoU が最大の人）。"""
    p = run / "mot/ids.json"
    if p.exists():
        return json.loads(p.read_text())
    ids = {}
    for txt in sorted((run / "mot").glob("*.txt")):
        cam = Camera(gt["cameras"][txt.stem])
        first = {}
        for line in txt.read_text().splitlines():
            f, i, x, y, w, h = line.split(",")[:6]
            first.setdefault(int(i), (int(f) - 1, float(x), float(y), float(x) + float(w), float(y) + float(h)))
        for i, (f, *box) in first.items():
            if i in ids.values():
                continue
            best, name = 0.0, None
            for n, pp in gt["people"].items():
                kk = f - pp["start_frame"]
                tr = gt["tracks"][n]
                if 0 <= kk < len(tr):
                    b = cam.person_box(tr[kk][0], tr[kk][1], pp.get("height_m", 1.7))
                    if b:
                        v = float(_iou_matrix([box], [b[:4]])[0, 0])
                        if v > best:
                            best, name = v, n
            if name and best > 0.9:
                ids[name] = i
    p.write_text(json.dumps(ids))
    return ids


# ---- 読む ----
def load_tracks(path):
    """MOPF の tracking.jsonl → {動画のコマ: [(ID, x0, y0, x1, y1), ...]}"""
    out = defaultdict(list)
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[int(r["frame_id"])].append((int(r["tracking_id"]), r["position_x_min"], r["position_y_min"], r["position_x_max"], r["position_y_max"]))
    return out


def load_mot_gt(path):
    """mot/<カメラ>.txt → {シミュレータのコマ: [(人の番号, x0, y0, x1, y1, 見えている割合), ...]}（MOT のコマは 1 から）"""
    out = defaultdict(list)
    for line in Path(path).read_text().splitlines():
        f, i, x, y, w, h, _, _, vis = line.split(",")[:9]
        out[int(f) - 1].append((int(i), float(x), float(y), float(x) + float(w), float(y) + float(h), float(vis)))
    return out


def _iou_matrix(a, b):
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = ix * iy
    area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / np.maximum(area(a)[:, None] + area(b)[None, :] - inter, 1e-9)


# ---- 比べる ----
def evaluate(run_dir, tracks_dir=None):
    import motmetrics as mm
    from scipy.optimize import linear_sum_assignment
    run, gt, f0 = _run(run_dir)
    tdir = Path(tracks_dir) if tracks_dir else run / "mopf_tracks"
    info = json.loads((tdir / "info.json").read_text()) if (tdir / "info.json").exists() else {"frame_offset": f0}
    f0 = int(info.get("frame_offset", f0))
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
                mi = _iou_matrix([x[1:5] for x in t], [x[1:5] for x in gi]).max(1)
                mv = _iou_matrix([x[1:5] for x in t], [x[1:5] for x in gv]).max(1) if gv else np.zeros(len(t))
                t = [x for x, a, b in zip(t, mi, mv) if not (a >= IOU_MIN and b < IOU_MIN)]
            d = 1 - _iou_matrix([x[1:5] for x in gv], [x[1:5] for x in t]) if gv and t else np.empty((len(gv), len(t)))
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


# ---- 中間層のグラフ ----
def _floor_tracks(gt, camn, T, f0):
    """MOPF の追跡 → {シミュレータのコマ: [(ID, x, y), ...]}（足元を床に移す）"""
    cam = Camera(gt["cameras"][camn])
    out = defaultdict(list)
    for k, rows in T.items():
        for tid, x0, y0, x1, y1 in rows:
            q = cam.floor_point((x0 + x1) / 2, y1)
            if q is not None:
                out[f0 + k].append((tid, q[0], q[1]))
    return out


def graph(run_dir, tracks_dir=None, coverage_min=0.6):
    """MOPF の追跡から、シミュレータの graph/ と同じ形のゾーンの人数・移動を作り、正解と比べる。
    比べるのは、カメラから床の coverage_min 以上が見えるゾーンだけ（graph.json の observed）。"""
    run, gt, f0 = _run(run_dir)
    tdir = Path(tracks_dir) if tracks_dir else run / "mopf_tracks"
    info = json.loads((tdir / "info.json").read_text()) if (tdir / "info.json").exists() else {"frame_offset": f0}
    f0 = int(info.get("frame_offset", f0))
    sp = load_space(gt["space"])
    fps = gt["fps"]
    obs = json.loads((run / "graph/graph.json").read_text())["observed"]
    zones = list(sp.zones)
    G = {}
    for tp in sorted(tdir.glob("*.jsonl")):
        camn = tp.stem
        T = load_tracks(tp)
        F = _floor_tracks(gt, camn, T, f0)
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


# ---- 人流モニターで数えるはずの値 ----
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
    run, gt, f0 = _run(run_dir)
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
    run, gt, f0 = _run(run_dir)
    tdir = Path(tracks_dir) if tracks_dir else run / "mopf_tracks"
    info = json.loads((tdir / "info.json").read_text()) if (tdir / "info.json").exists() else {"frame_offset": f0}
    f0 = int(info.get("frame_offset", f0))
    cfg = config or json.loads((run / "mopf" / camera / "config.json").read_text())
    W, H = gt["cameras"][camera]["width"], gt["cameras"][camera]["height"]
    T = load_tracks(tdir / f"{camera}.jsonl")
    side, events = defaultdict(dict), []
    for k in sorted(T):
        for tid, x0, y0, x1, y1 in T[k]:
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
    run, gt, f0 = _run(run_dir)
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


# ---- 確かめ用: 正解から MOPF の形の追跡を作る（揺れ・見逃し・ID の取り違えを足す） ----
def synthetic_tracks(run_dir, camera, out_dir, jitter_px=3.0, miss=0.1, switch_every=0, seed=0):
    run, gt, f0 = _run(run_dir)
    rng = np.random.default_rng(seed)
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    rl = run / "render_log.json"
    a, b = json.loads(rl.read_text())["frames"] if rl.exists() else (0, gt["total_frames"] - 1)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{camera}.jsonl", "w") as fh:
        for f in range(a, b + 1):
            for pid, x0, y0, x1, y1, vis in G.get(f, []):
                if vis < VIS_MIN or rng.random() < miss:
                    continue
                tid = pid + (1000 * ((f - a) // switch_every) if switch_every else 0)
                j = rng.normal(0, jitter_px, 4)
                fh.write(json.dumps({"frame_id": f - a, "tracking_id": int(tid), "position_x_min": x0 + j[0], "position_y_min": y0 + j[1],
                                     "position_x_max": x1 + j[2], "position_y_max": y1 + j[3]}) + "\n")
    (out / "info.json").write_text(json.dumps({"frame_offset": a, "synthetic": {"jitter_px": jitter_px, "miss": miss, "switch_every": switch_every}}))
    return out


# ---- 見て確かめる: 正解と MOPF の枠を重ねた動画、数えもらした場面の一覧の画像 ----
def overlay(run_dir, camera, tracks_dir=None, scale=0.75, sheet_max=24):
    """mopf_eval/<カメラ>_overlay.mp4（緑の枠 = 正解（見えている人）、灰色 = ほとんど隠れた正解、色つき = MOPF の ID、黄色の線 = 通過線）と
    mopf_eval/<カメラ>_missed.png（線の数えもらしの場面）。数えもらしの前後は赤、ID の切り替わりは黄色の文字で示す。"""
    import subprocess

    import cv2
    from PIL import Image, ImageDraw, ImageFont
    run, gt, f0 = _run(run_dir)
    tdir = Path(tracks_dir) if tracks_dir else run / "mopf_tracks"
    info = json.loads((tdir / "info.json").read_text()) if (tdir / "info.json").exists() else {"frame_offset": f0}
    f0 = int(info.get("frame_offset", f0))
    fps = gt["fps"]
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    T = load_tracks(tdir / f"{camera}.jsonl")
    ids = ensure_ids(run, gt)
    name_of = {v: k for k, v in ids.items()}
    cfgp = run / "mopf" / camera / "config.json"
    lines = json.loads(cfgp.read_text())["lines"] if cfgp.exists() else []
    cmp_ = compare_crossings(run, camera, tracks_dir) if lines else {"missed": [], "extra": []}
    exp_ev = expect(run, camera)["events"] if lines else []
    got_ev = track_crossings(run, camera, tracks_dir) if lines else []
    ev = json.loads((run / "mopf_eval/summary.json").read_text())["cameras"].get(camera, {}) if (run / "mopf_eval/summary.json").exists() else {}
    switches = ev.get("switches", [])
    missed = cmp_["missed"]
    font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 20)
    small = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 15)
    cap = cv2.VideoCapture(str(run / "video" / f"{camera}.mp4"))
    W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W, H = int(W0 * scale) // 2 * 2, int(H0 * scale) // 2 * 2
    out = run / "mopf_eval" / f"{camera}_overlay.mp4"
    ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", str(out)], stdin=subprocess.PIPE)
    color = lambda i: tuple(int(c) for c in cv2.cvtColor(np.uint8([[[(i * 47) % 180, 200, 255]]]), cv2.COLOR_HSV2BGR)[0, 0])
    miss_at = {m["frame"]: m for m in missed[:sheet_max]}
    crops = []
    k = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        f = f0 + k
        img = cv2.resize(img, (W, H))
        sx, sy = W / W0, H / H0
        hot = {m["person"] for m in missed if -0.5 * fps <= f - m["frame"] <= 1.5 * fps}
        swp = [x for x in switches if -0.5 * fps <= f - x["frame"] <= 1.0 * fps]
        for pid, x0, y0, x1, y1, vis in G.get(f, []):
            n = name_of.get(pid)
            c, t = ((0, 0, 230), 3) if n in hot else (((60, 200, 60), 2) if vis >= VIS_MIN else ((150, 150, 150), 1))
            cv2.rectangle(img, (int(x0 * sx), int(y0 * sy)), (int(x1 * sx), int(y1 * sy)), c, t)
        for tid, x0, y0, x1, y1 in T.get(k, []):
            c = color(tid)
            cv2.rectangle(img, (int(x0 * sx) + 2, int(y0 * sy) + 2), (int(x1 * sx) - 2, int(y1 * sy) - 2), c, 1)
            cv2.putText(img, f"ID {tid}", (int(x0 * sx), max(12, int(y0 * sy) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
        for ln in lines:
            cv2.line(img, (int(ln["a"][0] * W), int(ln["a"][1] * H)), (int(ln["b"][0] * W), int(ln["b"][1] * H)), (0, 220, 255), 2)
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        head = f"{f / fps:6.1f} 秒  {camera}"
        if lines:
            e_in = sum(1 for e in exp_ev if e["frame"] <= f and e["dir"] == "to_pos")
            e_out = sum(1 for e in exp_ev if e["frame"] <= f and e["dir"] == "to_neg")
            g_in = sum(1 for e in got_ev if e["frame"] <= f and e["dir"] == "to_pos")
            g_out = sum(1 for e in got_ev if e["frame"] <= f and e["dir"] == "to_neg")
            head += f"   正解なら 入館 {e_in}・退館 {e_out}   MOPF 入館 {g_in}・退館 {g_out}"
        d.rectangle([0, 0, W, 30], fill=(0, 0, 0))
        d.text((8, 3), head, font=font, fill=(255, 255, 255))
        y = 36
        for n in sorted(hot):
            d.text((8, y), f"数えもらし（{n}）", font=font, fill=(255, 60, 60))
            y += 26
        for x in swp[:3]:
            d.text((8, y), f"ID の切り替わり（{x['person']}、MOPF の ID {x['mopf_id']}）", font=font, fill=(255, 220, 0))
            y += 26
        d.text((8, H - 22), "緑 = 正解（見えている）・灰 = ほとんど隠れた正解・赤 = 線を数えもらした人・色つきの細い枠 = MOPF（ID）・黄色の線 = 通過線",
               font=small, fill=(255, 255, 255))
        img = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        if f in miss_at and lines:  # 線のまわりを切り出す
            ax = [ln["a"][0] * W for ln in lines] + [ln["b"][0] * W for ln in lines]
            ay = [ln["a"][1] * H for ln in lines] + [ln["b"][1] * H for ln in lines]
            cx0, cx1 = max(0, int(min(ax)) - 160), min(W, int(max(ax)) + 160)
            cy0, cy1 = max(0, int(min(ay)) - 200), min(H, int(max(ay)) + 120)
            crops.append((miss_at[f], img[cy0:cy1, cx0:cx1].copy()))
        ff.stdin.write(img.tobytes())
        k += 1
    ff.stdin.close()
    ff.wait()
    cap.release()
    files = [str(out)]
    if crops:
        ch, cw = max(c.shape[0] for _, c in crops), max(c.shape[1] for _, c in crops)
        cols = 4
        rows = (len(crops) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows * (ch + 28)), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, (m, c) in enumerate(crops):
            x, y = (i % cols) * cw, (i // cols) * (ch + 28)
            sheet.paste(Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)), (x, y + 28))
            d.text((x + 6, y + 4), f"{m['t_s']} 秒 {m['person']}（{'入館' if m['dir'] == 'to_pos' else '退館'}）", font=small, fill=(0, 0, 0))
        sp = run / "mopf_eval" / f"{camera}_missed.png"
        sheet.save(sp)
        files.append(str(sp))
    return {"files": files, "frames": k, "missed": len(missed), "switches": len(switches)}
