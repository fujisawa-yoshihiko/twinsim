"""人の動きのモデルを直す前後の比べ（CPU だけ）。確かめのテンプレートと場面のテンプレートを同じ種で計算し、
文献との比べの判定（validity.json）、人どうしの重なり、計算の時間をまとめる。

  uv run python tools/crowd_check.py <名前> [--only verify_bottleneck,office_gate_ev]
結果: ~/dt-data/twinsim/crowd_check/<名前>/（テンプレートごとの計算の結果と crowd_check.json）

重なり: 同じコマの 2 人（グループの仲間どうしは除く）の中心の距離が 0.3 m 未満の組 × コマ。
立っている人どうし（ss）・立っている人と歩く人（sm）・歩く人どうし（mm）に分ける。歩ける所の外（出入り口の向こう）の人は数えない。
"""

import argparse
import csv
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import twinsim  # noqa: E402
from twinsim.space import load_space  # noqa: E402

TEMPLATES = ["verify_corridor_speed", "verify_fundamental_diagram", "verify_groups", "verify_gate_capacity", "verify_counterflow",
             "verify_bottleneck", "office_gate_ev", "office_ev_hall", "hospital_gate_ev"]
OUT = Path.home() / "dt-data/twinsim/crowd_check"
CLOSE_M = (0.2, 0.3, 0.4)


def overlaps(run):
    sp = None
    gt = json.loads((run / "ground_truth.json").read_text())
    sp = load_space(gt["space"])
    by = defaultdict(list)
    with gzip.open(run / "frames.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            x, y = float(r["x"]), float(r["y"])
            if not sp.walkable(x, y):
                continue
            by[int(r["frame"])].append((x, y, int(r["moving"]), r["group"] or r["person"]))
    pairs = {k: 0 for k in ("ss", "sm", "mm")}
    close = {m: 0 for m in CLOSE_M}
    nearest = []
    person_frames = 0
    for ps in by.values():
        person_frames += len(ps)
        if len(ps) < 2:
            continue
        xy = np.array([p[:2] for p in ps])
        mv = np.array([p[2] for p in ps])
        grp = np.array([p[3] for p in ps])
        d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
        mate = grp[:, None] == grp[None, :]
        d[mate] = np.inf
        iu = np.triu_indices(len(ps), 1)
        dd = d[iu]
        kind = mv[iu[0]] + mv[iu[1]]
        for k, name in ((0, "ss"), (1, "sm"), (2, "mm")):
            pairs[name] += int(((dd < 0.3) & (kind == k)).sum())
        for m in CLOSE_M:
            close[m] += int((dd < m).sum())
        nearest += [float(v) for v in d.min(1) if np.isfinite(v)]
    q = [round(float(v), 3) for v in np.percentile(nearest, [1, 5, 50])] if nearest else None
    return {"person_frames": person_frames, "pairs_lt03": pairs, "pairs_lt": {str(m): v for m, v in close.items()},
            "pairs_lt03_per_1000_person_frames": round(1000 * sum(pairs.values()) / max(person_frames, 1), 2),
            "nearest_non_mate_p1_p5_p50": q}


def verdicts(v):
    out = {}
    for part in ("input_reproduction", "emergent"):
        for k, r in (v.get(part) or {}).items():
            if isinstance(r, dict) and "verdict" in r:
                out[f"{part}.{k}"] = r["verdict"]
            elif isinstance(r, dict):  # 流れごとの到着（arrivals）など、1 段下に判定があるもの
                out.update({f"{part}.{k}.{s}": x["verdict"] for s, x in r.items() if isinstance(x, dict) and "verdict" in x})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=1, help="2 以上で、テンプレートごとに別のプロセスで並べて計算する")
    ap.add_argument("--people", default="", help='people に足す JSON（例 {"cfsm": {"time_gap": 0.8}}）')
    a = ap.parse_args()
    names = [n for n in TEMPLATES if not a.only or n in a.only.split(",")]
    root = OUT / a.label
    root.mkdir(parents=True, exist_ok=True)
    rp = root / "crowd_check.json"
    report = json.loads(rp.read_text()) if rp.exists() else {}
    if a.jobs > 1:  # テンプレートごとに別のプロセスで（結果は最後にまとめる）
        import subprocess
        procs = [subprocess.Popen([sys.executable, __file__, f"{a.label}/{n}", "--only", n, "--people", a.people],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT) for n in names]
        for pr in procs:
            pr.wait()
        for n in names:
            sub = OUT / a.label / n / "crowd_check.json"
            if sub.exists():
                report[n] = json.loads(sub.read_text())[n]
                print(n, report[n]["seconds"], "秒", report[n]["pairs_lt03"], report[n]["gridlock"],
                      {k: x for k, x in report[n]["verdicts"].items() if x not in ("合う", "参考", "対象外")}, flush=True)
            else:
                print(n, "結果がない", flush=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
        print("書いた:", rp)
        return
    for name in names:
        t0 = time.time()
        cfg = twinsim.template(name)
        if a.people:
            cfg["people"] = {**cfg.get("people", {}), **json.loads(a.people)}
        r = twinsim.simulate(cfg, out_dir=root / name)
        sec = time.time() - t0
        if not (root / name / "validity.json").exists():  # 出力に validity がないテンプレートは、ここで作る
            from twinsim.validity import evaluate
            evaluate(root / name)
        v = r.validity() or {}
        em = v.get("emergent", {})
        report[name] = {"people_override": a.people, "seconds": round(sec, 1), "people": r.summary.get("people"),
                        "motion": r.summary.get("motion"), "verdicts": verdicts(v),
                        "gridlock": em.get("gridlock", {}).get("n_stuck"), "bottleneck": em.get("bottleneck"),
                        "speed_density": [(b["rho"], b["mean_v"], b["mean_ratio"]) for b in (em.get("speed_density") or {}).get("bins", [])],
                        "standing_spacing": em.get("standing_spacing", {}).get("share_below_0.45m"),
                        "dyad": em.get("dyad_distance", {}).get("distance_m"), **overlaps(root / name)}
        print(name, f"{sec:.0f} 秒", report[name]["pairs_lt03"], report[name]["nearest_non_mate_p1_p5_p50"],
              {k: x for k, x in report[name]["verdicts"].items() if x not in ("合う", "参考", "対象外")}, flush=True)
        rp.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("書いた:", rp)


if __name__ == "__main__":
    main()
