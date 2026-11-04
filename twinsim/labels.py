"""描画から出した人ごとの枠（Replicator の注釈、render.py の labels）を、カメラごとの正解の表 labels/<カメラ>.csv にまとめる。

mot/<カメラ>.txt（計算だけで作る近似の枠）と違い、描かれた人の画素から作るので、枠は輪郭に合い、隠れの割合は壁・家具・人を全部数える。
列: frame（MOT と同じ 1 始まり = シミュレータのコマ + 1）、id（labels/ids.json。mot/ids.json の番号はそのまま、新しく映る人には続きの番号）、name、
tight_x0〜y1（見えている画素の枠。画面の中だけ。見えない人は空）、amodal_x0〜y1（隠れた部分も含む全身の枠。画面の外へはみ出す分も含む）、
visibility（全身のうち見えている割合 = (1 - occlusion) × (1 - truncation)）、occlusion（画面の中の部分のうち、ほかの物・人に隠れた割合）、
truncation（全身のうち画面の外の割合）、portal（現れる・消える所の範囲にいるか、space.portals）、state（その人の状態）、
visible_px（見えている画素の数）、occ_source（occlusion の出どころ。occlusion() の説明: silhouette・silhouette_interp・fill_median・box_ratio・hidden）。
labels/<カメラ>_mot.txt は同じ中身の MOTChallenge の gt.txt の形（frame, id, 全身の枠 x, y, w, h, 1, 1, visibility）。
"""

import csv
import json
from pathlib import Path

import numpy as np

from .camera import Camera
from .space import load_space

COLUMNS = ["frame", "id", "name", "tight_x0", "tight_y0", "tight_x1", "tight_y1", "amodal_x0", "amodal_y0", "amodal_x1", "amodal_y1",
           "visibility", "occlusion", "truncation", "portal", "state", "visible_px", "occ_source"]
MIN_INSIDE = 0.02  # 計算の全身の枠のこれだけが画面に入れば、見えていなくても行を書く（完全に隠れた人も visibility 0 で残す）
EDGE_PX = 1  # 描画の全身の枠がこれ以内で画面の端に触れていたら、画面の外へ続くとみて、計算の枠で外側を伸ばす


def _state_at(runs, f):
    for a, b, s in runs:
        if a <= f <= b:
            return s
    return ""


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _clip(b, w, h):
    return (max(b[0], 0.0), max(b[1], 0.0), min(b[2], float(w)), min(b[3], float(h)))


def _box(b):
    """Replicator の枠 [x_min, y_min, x_max, y_max(, occlusionRatio)] → (x0, y0, x1, y1)。x_max・y_max は最後の画素の番号なので +1 して右下の端にする。"""
    return (b[0], b[1], b[2] + 1, b[3] + 1)


def occlusion(r, tb, lb, am, f, fill, fill_median, w, h):
    """画面の中の部分のうち隠れた割合と、その出どころ。
    silhouette = 1 - 見えている画素 ÷ 全身の画素（全身は、背景とほかの人を消して描いて数えた、render.py の full_silhouettes）。
    silhouette_interp = 全身の画素を測っていないコマ: 全身の画素 ÷ 全身の枠の面積を、その人の測ったコマの間で補う（fill_median は全員の中央値）。
    box_ratio = 画素の数がない古い注釈: 見えている枠と全身の枠の面積の比（近似）。hidden = 見える画素がない。"""
    if tb is None:
        return 1.0, "hidden"
    px = r.get("px")
    lc = _clip(lb, w, h) if lb else _clip(am, w, h)
    if px is None:
        return min(max(1.0 - _area(tb) / max(_area(lc), 1e-9), 0.0), 1.0), "box_ratio"
    if r.get("full"):
        full, src = float(r["full"]), "silhouette"
    elif fill:
        fs = sorted(fill)
        full, src = float(np.interp(f, [a for a, _ in fs], [v for _, v in fs])) * _area(lc), "silhouette_interp"
    elif fill_median:
        full, src = fill_median * _area(lc), "fill_median"
    else:
        return min(max(1.0 - _area(tb) / max(_area(lc), 1e-9), 0.0), 1.0), "box_ratio"
    return min(max(1.0 - px / max(full, 1.0), 0.0), 1.0), src


def amodal_box(loose, cpu, w, h):
    """全身の枠: 描画の loose（画面で切られている）を基に、画面の端に触れている辺だけ計算の枠（cpu、切られていない）まで伸ばす。"""
    if loose is None:
        return cpu
    x0, y0, x1, y1 = loose
    if cpu is not None:
        if x0 <= EDGE_PX:
            x0 = min(x0, cpu[0])
        if y0 <= EDGE_PX:
            y0 = min(y0, cpu[1])
        if x1 >= w - EDGE_PX:
            x1 = max(x1, cpu[2])
        if y1 >= h - EDGE_PX:
            y1 = max(y1, cpu[3])
    return (float(x0), float(y0), float(x1), float(y1))


def build(run_dir, camera, raw, ids=None, occ_includes_truncation=False):
    """raw: render.py の labels_raw の JSON を時刻の順に並べたもの（1 つのカメラ）。→ (表の行のリスト, ids)。
    occ_includes_truncation: Replicator の occlusionRatio が画面の外の分も隠れとして数えるなら True（そのときは visibility = 1 - occlusion）。"""
    run = Path(run_dir)
    gt = json.loads((run / "ground_truth.json").read_text())
    resolved = run / "scenario_resolved.json"
    sp = load_space(json.loads(resolved.read_text(encoding="utf-8")).get("space", gt["space"]) if resolved.exists() else gt["space"])
    cam = Camera(gt["cameras"][camera], floor_z=sp.z)
    w, h = cam.w, cam.h
    ids = dict(ids or {})
    nxt = max(ids.values(), default=0) + 1
    # 全身の画素の数は FULL_EVERY コマごとにしか測っていない（render.py）。人ごとに「全身の画素 ÷ 全身の枠の面積」を、測ったコマの間で補う
    fills = {}
    for part in raw:
        for fr in part["rows"]:
            for name, r in fr["people"].items():
                if r.get("full") and r.get("loose"):
                    lb = _clip(_box(r["loose"]), w, h)
                    if _area(lb) > 0:
                        fills.setdefault(name, []).append((int(fr["frame"]), r["full"] / _area(lb)))
    all_fill = [v for s_ in fills.values() for _, v in s_]
    fill_median = float(np.median(all_fill)) if all_fill else None
    rows = []
    for part in raw:
        for fr in part["rows"]:
            f = int(fr["frame"])
            got = fr["people"]
            for name, p in gt["people"].items():
                s0, tr = p["start_frame"], gt["tracks"][name]
                if not (s0 <= f < s0 + len(tr)):
                    continue
                x, y = tr[f - s0][0], tr[f - s0][1]
                b = cam.person_box(x, y, float(p.get("height_m", 1.75)))
                cpu = (b[0], b[1], b[2], b[3]) if b else None
                r = got.get(name, {})
                tight, loose = r.get("tight"), r.get("loose")
                if tight is None and loose is None and (b is None or b[4] < MIN_INSIDE):
                    continue
                tb = _box(tight) if tight else None
                lb = _box(loose) if loose else None
                am = amodal_box(lb, cpu, w, h)
                if am is None:
                    continue
                inside = _area(_clip(am, w, h)) / max(_area(am), 1e-9)
                trunc = 1.0 - inside
                occ, src = occlusion(r, tb, lb, am, f, fills.get(name), fill_median, w, h)
                vis = (1.0 - occ) if occ_includes_truncation else (1.0 - occ) * (1.0 - trunc)
                if name not in ids:
                    ids[name] = nxt
                    nxt += 1
                rows.append({"frame": f + 1, "id": ids[name], "name": name,
                             **({k: round(float(v), 1) for k, v in zip(("tight_x0", "tight_y0", "tight_x1", "tight_y1"), tb)} if tb else
                                {"tight_x0": "", "tight_y0": "", "tight_x1": "", "tight_y1": ""}),
                             **{k: round(float(v), 1) for k, v in zip(("amodal_x0", "amodal_y0", "amodal_x1", "amodal_y1"), am)},
                             "visibility": round(max(vis, 0.0), 4), "occlusion": round(occ, 4), "truncation": round(trunc, 4),
                             "portal": 1 if sp.in_portal(x, y) else 0, "state": _state_at(p.get("states", []), f),
                             "visible_px": int(r.get("px", 0)), "occ_source": src})
    rows.sort(key=lambda r: (r["frame"], r["id"]))
    return rows, ids


def write(run_dir, camera, rows):
    out = Path(run_dir) / "labels"
    out.mkdir(exist_ok=True)
    with open(out / f"{camera}.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLUMNS)
        wr.writeheader()
        wr.writerows(rows)
    with open(out / f"{camera}_mot.txt", "w") as f:
        for r in rows:
            x0, y0, x1, y1 = r["amodal_x0"], r["amodal_y0"], r["amodal_x1"], r["amodal_y1"]
            f.write(f"{r['frame']},{r['id']},{x0:.1f},{y0:.1f},{x1 - x0:.1f},{y1 - y0:.1f},1,1,{r['visibility']:.4f}\n")
    return out / f"{camera}.csv"


def build_all(run_dir, raw_by_camera, occ_includes_truncation=False):
    """raw_by_camera: {カメラ: [labels_raw の JSON, ...]}。labels/<カメラ>.csv・<カメラ>_mot.txt・ids.json を書き、行の数を返す。"""
    run = Path(run_dir)
    idp = run / "mot" / "ids.json"
    ids = json.loads(idp.read_text()) if idp.exists() else {}
    counts = {}
    for cam, raw in raw_by_camera.items():
        rows, ids = build(run, cam, sorted(raw, key=lambda r: r["frames"][0]), ids, occ_includes_truncation)
        write(run, cam, rows)
        counts[cam] = len(rows)
    (run / "labels").mkdir(exist_ok=True)
    (run / "labels" / "ids.json").write_text(json.dumps(ids))
    return counts


def summary(rows):
    """確かめ用: 行の数、見えている画素のある行の数、visibility の分布。"""
    vis = np.array([r["visibility"] for r in rows], float) if rows else np.zeros(0)
    return {"rows": len(rows), "with_tight": sum(1 for r in rows if r["tight_x0"] != ""),
            "visibility_p10_50_90": [round(float(x), 3) for x in np.percentile(vis, [10, 50, 90])] if len(vis) else None}
