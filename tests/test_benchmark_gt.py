"""ベンチマークのための直しの確かめ（CPU だけ）: 描画の注釈から作る正解の表、近くの人だけを置く、出入り口、EV のかご、待つ人があふれたとき。"""

import csv
import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from test_farm import fake_worker, work  # noqa: F401  pytest の fixture

import twinsim
from twinsim import isaac_bridge, labels
from twinsim.camera import Camera
from twinsim.space import load_space

CONFIG = {"space": "office", "duration_s": 40, "fps": 10, "seed": 5,
          "streams": [{"origin": "entrance", "rate": 20, "destinations": [{"to": "south_exit", "via": ["gate"]}]}],
          "cameras": [{"name": "CamGate"}, {"name": "CamEV"}]}


def fake_labels(work):  # noqa: F811
    """偽の描画の注釈: 計算の枠を画面で切ったものを loose、その真ん中 6 割を tight、隠れ 0.1 とする（render.py の labels と同じ形）。"""
    for p in sorted((work / "inbox").glob("*.py")):
        job = json.loads((work / "jobs" / f"{p.stem}.json").read_text())
        if not job.get("labels"):
            continue
        run = work / "runs" / Path(job["run_dir"]).name
        gt = json.loads((run / "ground_truth.json").read_text())
        f0, f1 = job["frames"]
        for cam in job["cameras"]:
            c = Camera(gt["cameras"][cam])
            rows = []
            for f in range(f0, f1 + 1):
                got = {}
                for name, pp in gt["people"].items():
                    if job.get("people") is not None and name not in job["people"]:
                        continue
                    s0, tr = pp["start_frame"], gt["tracks"][name]
                    if not s0 <= f < s0 + len(tr):
                        continue
                    b = c.person_box(tr[f - s0][0], tr[f - s0][1], pp["height_m"])
                    if not b or b[4] < 0.05:
                        continue
                    x0, y0, x1, y1 = max(b[0], 0), max(b[1], 0), min(b[2], c.w - 1), min(b[3], c.h - 1)
                    mx, my = (x1 - x0) * 0.2, (y1 - y0) * 0.2
                    got[name] = {"loose": [int(x0), int(y0), int(x1), int(y1), 0.1], "tight": [int(x0 + mx), int(y0 + my), int(x1 - mx), int(y1 - my), 0.1]}
                rows.append({"frame": f, "people": got})
            out = run / "labels_raw" / f"{job.get('frames_dir') or cam}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"camera": cam, "frames": [f0, f1], "width": c.w, "height": c.h, "rows": rows}))


def test_labels_table_from_rendered_boxes(tmp_path, work):  # noqa: F811
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 299), chunk_s=7, labels=True, preroll=3)
    assert all(j["labels"] and j["preroll"] == 3 for _, j in plan["parts"])
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    out = isaac_bridge.finish_plan(plan)
    assert out["videos"] == {"CamGate": 200, "CamEV": 200}
    rl = json.loads((r.out_dir / "render_log.json").read_text())
    assert set(rl["labels"]) == {"CamGate", "CamEV"}
    ids = json.loads((r.out_dir / "labels/ids.json").read_text())
    mot_ids = json.loads((r.out_dir / "mot/ids.json").read_text())
    assert all(ids[k] == v for k, v in mot_ids.items())  # 今の番号は変えない
    for cam in ("CamGate", "CamEV"):
        rows = list(csv.DictReader(open(r.out_dir / "labels" / f"{cam}.csv")))
        assert rows and list(rows[0]) == labels.COLUMNS
        frames = {int(x["frame"]) for x in rows}
        assert min(frames) >= 101 and max(frames) <= 300  # MOT と同じ 1 始まり
        for x in rows:
            v, o, t = float(x["visibility"]), float(x["occlusion"]), float(x["truncation"])
            assert 0 <= v <= 1 and 0 <= t <= 1
            assert abs(v - (1 - o) * (1 - t)) < 1e-3
            assert int(x["id"]) == ids[x["name"]]
            if x["tight_x0"] != "":
                assert float(x["amodal_x0"]) <= float(x["tight_x0"]) and float(x["tight_x1"]) <= float(x["amodal_x1"])
        assert any(float(x["truncation"]) > 0.01 for x in rows)  # 画面の端の人は外の分が数えられる
        mot = np.loadtxt(r.out_dir / "labels" / f"{cam}_mot.txt", delimiter=",", ndmin=2)
        assert len(mot) == len(rows)


def test_labels_missing_chunk_stops(tmp_path, work):  # noqa: F811
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 199), chunk_s=5, labels=True)
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    next((work / "runs" / plan["name"] / "labels_raw" / "CamEV").glob("*.json")).unlink()
    with pytest.raises(RuntimeError, match="注釈のコマ"):
        isaac_bridge.finish_plan(plan)


def test_cull_keeps_everyone_in_view(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(0, 399), chunk_s=10, cull=True)
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    for _, job in plan["parts"]:
        cam = Camera(gt["cameras"][job["cameras"][0]])
        a, b = job["frames"]
        for name, p in gt["people"].items():
            s0, tr = p["start_frame"], gt["tracks"][name]
            for f in range(max(a, s0), min(b, s0 + len(tr) - 1) + 1):
                bx = cam.person_box(tr[f - s0][0], tr[f - s0][1], p["height_m"])
                if bx and bx[4] > 0:
                    assert name in job["people"], (name, f, job["cameras"])
    assert sum(len(j["people"]) for _, j in plan["parts"]) < len(plan["parts"]) * len(gt["people"])  # 実際に減る


def test_hidden_spawn_and_exit_walk_in_and_out(tmp_path):
    r = twinsim.simulate({**CONFIG, "duration_s": 90}, out_dir=tmp_path / "r")  # 入口から南の出口まで約 50 m
    sp = load_space("office")
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    hidden_in, hidden_out = sp.pois["entrance"]["hidden"], sp.pois["south_exit"]["hidden"]
    starts = [gt["tracks"][n][0][:2] for n in gt["people"]]
    assert all(np.hypot(x - hidden_in[0], y - hidden_in[1]) < 0.6 for x, y in starts)  # 扉の向こうに現れる
    done = [n for n, p in gt["people"].items() if p.get("events", {}).get("end")]
    assert done and all(np.hypot(gt["tracks"][n][-1][0] - hidden_out[0], gt["tracks"][n][-1][1] - hidden_out[1]) < 0.6 for n in done)
    with gzip.open(r.out_dir / "frames.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    off = [x for x in rows if not sp.walkable(float(x["x"]), float(x["y"]))]
    assert off and all(sp.in_portal(float(x["x"]), float(x["y"])) for x in off)  # 歩ける所の外は出入り口の範囲だけ
    from twinsim.quality import check
    assert check(r.out_dir)["not_walkable_frac"] < 0.005


def test_elevator_cabin_and_overflow(tmp_path):
    cfg = twinsim.template("hospital_gate_ev")
    for s in cfg["streams"]:  # 人の量を 2.5 倍（ベンチマークの素材の A の hospital の mid と同じ）
        r = s.get("rate")
        if isinstance(r, dict) and r.get("type") == "constant":
            r["per_min"] *= 2.5
        elif isinstance(r, dict) and r.get("type") == "piecewise":
            r["per_min"] = [[t, v * 2.5] for t, v in r["per_min"]]
        elif isinstance(r, (int, float)):
            s["rate"] = r * 2.5
    if "demand" in cfg:
        cfg["demand"]["population"] = round(cfg["demand"]["population"] * 2.5)
    cfg.update({"duration_s": 120, "seed": 1})
    res = twinsim.simulate(cfg, out_dir=tmp_path / "h")
    gt = json.loads((res.out_dir / "ground_truth.json").read_text())
    # 待つ場所が埋まっても、立って待つ人どうしは重ならない
    by = {}
    with gzip.open(res.out_dir / "frames.csv.gz", "rt") as f:
        for x in csv.DictReader(f):
            if x["state"] == "ev_wait" and x["moving"] == "0" and int(x["frame"]) % 10 == 0:
                by.setdefault(x["frame"], []).append((float(x["x"]), float(x["y"])))
    waiting = [len(v) for v in by.values()]
    assert max(waiting) > 15  # 待つ場所（15 か所）より多い
    for pts in by.values():
        p = np.array(pts)
        d = np.hypot(*(p[:, None] - p[None]).transpose(2, 0, 1)) + np.eye(len(p)) * 9
        assert d.min() > 0.3
    # office の EV は、乗る人がかごの中まで歩いてから消える
    cfg = twinsim.template("office_ev_hall")
    cfg.update({"duration_s": 120, "seed": 1})
    res = twinsim.simulate(cfg, out_dir=tmp_path / "o")
    gt = json.loads((res.out_dir / "ground_truth.json").read_text())
    sp = load_space("office")
    cabins = {k: np.add(p["xy"], np.subtract(p["face"], p["xy"]) / np.hypot(*np.subtract(p["face"], p["xy"])) * p["cabin_m"])
              for k, p in sp.pois.items() if p.get("kind") == "elevator"}
    boarded = [n for n, p in gt["people"].items() if p.get("events", {}).get("board")]
    assert boarded
    for n in boarded:
        car = gt["people"][n]["events"]["car"]
        assert np.hypot(*(np.array(gt["tracks"][n][-1][:2]) - cabins[car])) < 0.2
