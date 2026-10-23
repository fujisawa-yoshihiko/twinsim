"""確かめ用: 正解から MOPF の形の追跡を作る（揺れ・見逃し・ID の取り違えを足す）。評価・グラフ・数え方のテストに使う。"""

import json
from pathlib import Path

import numpy as np

from .io import VIS_MIN, load_mot_gt, open_run


def synthetic_tracks(run_dir, camera, out_dir, jitter_px=3.0, miss=0.1, switch_every=0, seed=0):
    run, gt, f0 = open_run(run_dir)
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
