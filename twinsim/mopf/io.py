"""MOPF の結果・正解を読む共通の部品（コマの対応・枠の番号と人の対応・IoU）。"""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..camera import Camera

IOU_MIN = 0.3   # 正解の枠は人を囲む箱から作った近似なので 0.3 で対応づける（research/sim-cctv/evaluate.py と同じ）
VIS_MIN = 0.4   # これより見えていない正解の枠は、見逃しにも誤検出にも数えない


def open_run(run_dir):
    """(結果の場所, 正解, 動画の 0 コマ目のシミュレータのコマ)。動画の 0 コマ目は render_log.json の frames[0]（試し撮りなら途中から）。"""
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    rl = run / "render_log.json"
    f0 = json.loads(rl.read_text())["frames"][0] if rl.exists() else 0
    return run, gt, int(f0)


def tracks_dir_and_offset(run, tracks_dir, f0):
    """MOPF の追跡の置き場所（既定 <結果>/mopf_tracks）と、その追跡の 0 コマ目（info.json の frame_offset を優先）。"""
    tdir = Path(tracks_dir) if tracks_dir else run / "mopf_tracks"
    info = json.loads((tdir / "info.json").read_text()) if (tdir / "info.json").exists() else {}
    return tdir, int(info.get("frame_offset", f0))


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
                        v = float(iou_matrix([box], [b[:4]])[0, 0])
                        if v > best:
                            best, name = v, n
            if name and best > 0.9:
                ids[name] = i
    p.write_text(json.dumps(ids))
    return ids


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


def iou_matrix(a, b):
    a, b = np.asarray(a, float).reshape(-1, 4), np.asarray(b, float).reshape(-1, 4)
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = ix * iy
    area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / np.maximum(area(a)[:, None] + area(b)[None, :] - inter, 1e-9)
