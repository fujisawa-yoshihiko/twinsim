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
    """偽の描画の注釈（render.py の labels と同じ形）: 計算の枠を画面で切ったものを loose、その真ん中 6 割を tight、
    見えている画素 px = tight の面積の 0.3 倍、全身の画素 full = loose の面積の 0.4 倍（10 コマごと）。"""
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
                    lo = [int(x0), int(y0), int(x1), int(y1)]
                    ti = [int(x0 + mx), int(y0 + my), int(x1 - mx), int(y1 - my)]
                    got[name] = {"loose": lo, "tight": ti, "px": int(0.3 * (ti[2] - ti[0] + 1) * (ti[3] - ti[1] + 1))}
                    if (f - f0) % 10 == 0:
                        got[name]["full"] = int(0.4 * (lo[2] - lo[0] + 1) * (lo[3] - lo[1] + 1))
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
        src = {x["occ_source"] for x in rows}
        assert "silhouette" in src and "silhouette_interp" in src
        for x in rows:  # 偽の注釈では、全身の画素 ÷ 全身の枠の面積が 0.4 で一定なので、補ったコマも測ったコマと同じ式になる
            if x["occ_source"] in ("silhouette", "silhouette_interp") and float(x["tight_x0"]) > 0:
                t = [float(x[f"tight_{k}"]) for k in ("x0", "y0", "x1", "y1")]
                px = int(x["visible_px"])  # すりガラスの奥の分は除く（glass）
                assert px == pytest.approx(0.3 * (t[2] - t[0]) * (t[3] - t[1]) * (1 - float(x["glass"])), abs=2)
        assert any(float(x["glass"]) > 0 for x in rows) or cam == "CamEV"
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


def test_alighting_people_appear_inside_portal(tmp_path):
    """かごのない EV（hospital の見立て）で降りる人は、出入り口の範囲の中に現れる（範囲の外に現れると、画面の中で急に現れる人を採点する）。"""
    r = twinsim.simulate({**twinsim.template("hospital_gate_ev"), "duration_s": 240, "seed": 3}, out_dir=tmp_path / "r")
    sp = load_space("hospital")
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    first = [gt["tracks"][n][0][:2] for n, p in gt["people"].items() if any(s[2] == "alight" for s in p.get("states", [])[:1])]
    assert len(first) >= 5
    assert all(sp.in_portal(x, y) == "EV" for x, y in first)


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
        assert np.hypot(*(np.array(gt["tracks"][n][-1][:2]) - cabins[car])) < 0.45  # 2 列で入る（真ん中から左右 0.35 m、motion_model "cfsm"）


def test_empty_labels_stop_and_keep_old_table(tmp_path, work):  # noqa: F811
    """描画の注釈が空の区間（Replicator が誰も返さない）があれば止まり、前の正解の表は残す（2026-11-04 のガラスの版）。"""
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 299), chunk_s=10, labels=True)
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    isaac_bridge.finish_plan(plan)
    before = {p.name: p.read_bytes() for p in (r.out_dir / "labels").glob("*.csv")}
    raws = sorted((work / "runs" / plan["name"] / "labels_raw").glob("*/*.json"))
    big = max(raws, key=lambda p: sum(len(fr["people"]) for fr in json.loads(p.read_text())["rows"]))
    d = json.loads(big.read_text())
    assert sum(len(fr["people"]) for fr in d["rows"]) >= labels.EMPTY_MIN_ROWS
    for fr in d["rows"]:
        fr["people"] = {}
    big.write_text(json.dumps(d))
    with pytest.raises(RuntimeError, match="注釈が空"):
        isaac_bridge.finish_labels(plan, work / "runs" / plan["name"], r.out_dir)
    assert {p.name: p.read_bytes() for p in (r.out_dir / "labels").glob("*.csv")} == before


def test_wrong_names_from_replicator_are_fixed(tmp_path, work):  # noqa: F811
    """Replicator が、その時刻にいない人の名前で返した注釈は、枠の合う人に付け直す（labels.fix_names、2026-11-04）。"""
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 299), chunk_s=10, labels=True)
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    later = max(gt["people"], key=lambda n: gt["people"][n]["start_frame"])
    raw_path = next(p for p in sorted((work / "runs" / plan["name"] / "labels_raw").glob("*/*.json"))
                    if any(fr["people"] for fr in json.loads(p.read_text())["rows"]))
    d = json.loads(raw_path.read_text())
    fr = next(fr for fr in d["rows"] if fr["people"] and int(fr["frame"]) < gt["people"][later]["start_frame"])
    real = next(iter(fr["people"]))
    fr["people"] = {later if n == real else n: v for n, v in fr["people"].items()}
    raw_path.write_text(json.dumps(d))
    isaac_bridge.finish_labels(plan, work / "runs" / plan["name"], r.out_dir)
    ident = json.loads((r.out_dir / "labels" / "identity.json").read_text())["cameras"][d["camera"]]
    assert ident["renamed"] >= 1 and ident["dropped"] == 0
    rows = list(csv.DictReader(open(r.out_dir / "labels" / f"{d['camera']}.csv")))
    at = {x["name"]: x for x in rows if int(x["frame"]) == int(fr["frame"]) + 1}
    assert at[real]["tight_x0"] != "" and (later not in at or at[later]["tight_x0"] == "")


def test_late_replicator_rows_are_unlabeled(tmp_path, work):  # noqa: F811
    """区間の途中で現れた人を Replicator がしばらく返さないとき、最初の注釈までの行は hidden ではなく unlabeled（2026-11-04）。"""
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 299), chunk_s=10, labels=True)
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    cut = []  # (カメラ, 名前, 消したコマ)
    for p in sorted((work / "runs" / plan["name"] / "labels_raw").glob("*/*.json")):
        d = json.loads(p.read_text())
        a, b = d["frames"]
        mid = [n for n, pp in gt["people"].items() if a < pp["start_frame"] <= b - 40 and any(n in fr["people"] for fr in d["rows"])]
        if not mid:
            continue
        n = mid[0]
        gone = [int(fr["frame"]) for fr in d["rows"] if n in fr["people"]][:30]  # 現れてから 30 コマを抜く
        for fr in d["rows"]:
            if int(fr["frame"]) in gone:
                del fr["people"][n]
        p.write_text(json.dumps(d))
        cut.append((d["camera"], n, set(gone)))
    assert cut
    isaac_bridge.finish_labels(plan, work / "runs" / plan["name"], r.out_dir)
    for cam, n, gone in cut:
        rows = [x for x in csv.DictReader(open(r.out_dir / "labels" / f"{cam}.csv")) if x["name"] == n]
        src = {int(x["frame"]) - 1: x["occ_source"] for x in rows}
        assert all(src[f] == labels.UNLABELED for f in gone if f in src)
        assert any(v != labels.UNLABELED for f, v in src.items() if f > max(gone))  # 最初の注釈からあとは普通の行
    # 区間の始めからいる人は、隠れていても unlabeled にしない
    for cam in {c for c, _, _ in cut}:
        rows = list(csv.DictReader(open(r.out_dir / "labels" / f"{cam}.csv")))
        early = {n for n, pp in gt["people"].items() if pp["start_frame"] <= 100}
        assert not any(x["occ_source"] == labels.UNLABELED for x in rows if x["name"] in early)


def test_people_inside_dropped_stale_box_are_unlabeled(tmp_path, work):  # noqa: F811
    """出番の終わった人の名前で 2 人分の体をまとめた枠が返ったとき（office ゲート前 mid、2026-11-04）、その枠は捨て、中の 2 人は unlabeled。"""
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(100, 299), chunk_s=10, labels=True)
    isaac_bridge.start_render(plan)
    fake_labels(work)
    fake_worker(work)
    gt = json.loads((r.out_dir / "ground_truth.json").read_text())
    ended = [n for n, p in gt["people"].items() if p["start_frame"] + len(gt["tracks"][n]) < 100]
    absent = ended[0] if ended else "P9999"  # この範囲にいない人の名前
    for p in sorted((work / "runs" / plan["name"] / "labels_raw").glob("*/*.json")):
        d = json.loads(p.read_text())
        fr = next((fr for fr in d["rows"] if len(fr["people"]) >= 2), None)
        if fr is None:
            continue
        two = sorted(fr["people"])[:2]
        lo = [fr["people"][n]["loose"] for n in two]
        union = [min(b[0] for b in lo), min(b[1] for b in lo), max(b[2] for b in lo), max(b[3] for b in lo)]
        fr["people"] = {n: v for n, v in fr["people"].items() if n not in two}
        fr["people"][absent] = {"loose": union, "tight": union, "px": 100}
        p.write_text(json.dumps(d))
        break
    isaac_bridge.finish_labels(plan, work / "runs" / plan["name"], r.out_dir)
    rows = list(csv.DictReader(open(r.out_dir / "labels" / f"{d['camera']}.csv")))
    at = {x["name"]: x for x in rows if int(x["frame"]) == int(fr["frame"]) + 1}
    assert absent not in at
    ident = json.loads((r.out_dir / "labels" / "identity.json").read_text())["cameras"][d["camera"]]
    assert ident["dropped"] >= 1
    # 2 人の計算の枠は太いので、まとめた枠に半分以上入る方だけが unlabeled になる。少なくとも 1 人
    assert sum(at[n]["occ_source"] == labels.UNLABELED for n in two) >= 1
    assert all(at[n]["occ_source"] in (labels.UNLABELED, "hidden") for n in two)
