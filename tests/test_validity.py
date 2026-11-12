"""文献に基づく分布・実データで合わせる・MOPF との連携の確かめ（CPU だけ、十数秒）:
  uv run --no-project --with numpy --with scipy --with pyyaml --with pillow --with networkx --with matplotlib --with motmetrics --with pytest pytest -q tests"""

import json
import math

import numpy as np
import pytest

import twinsim
from twinsim import api, dists
from twinsim.literature import GROUP_SHARE, lift_demand_per_min, person_share_to_group_mean, weidmann_speed, ztp_lambda_for_mean, ztp_person_share
from twinsim.scenario import load_scenario, resolve_rate


def test_weidmann_formula():
    # v = 1.34 (1 − exp(−1.913 (1/ρ − 1/5.4)))（Weidmann 1993、arXiv:1512.01426 の式 (1)・(7)–(9)）
    assert weidmann_speed(0.0) == 1.34
    assert weidmann_speed(1.0) == pytest.approx(1.34 * (1 - math.exp(-1.913 * (1 - 1 / 5.4))), rel=1e-9)
    assert weidmann_speed(5.4) == 0.0


def test_group_size_from_osaka_share():
    # 大阪の地下の歩行者空間: 人の割合 1 人 82%・2 人 15%・3 人 3%（Zanlungo ら 2014）→ λ ≈ 0.20、1 人の割合はほぼ再現
    lam = ztp_lambda_for_mean(person_share_to_group_mean(GROUP_SHARE["osaka_underground"]["share"]))
    assert lam == pytest.approx(0.20, abs=0.01)
    assert ztp_person_share(lam)[0] == pytest.approx(0.82, abs=0.01)
    assert dists.mean({"type": "zero_truncated_poisson", "lam": lam}) == pytest.approx(1.105, abs=0.005)


def test_lift_demand():
    # 600 人 × 12% / 5 分 × 朝の入る 85% = 12.24 人/分（Peters ら 2011）
    assert lift_demand_per_min({"population": 600, "peak_pct_5min": 12, "period": "morning"}, "incoming") == pytest.approx(12.24)
    assert lift_demand_per_min({"population": 600, "peak_pct_5min": 12, "period": "lunch"}, "outgoing") == pytest.approx(6.48)


def test_profile_and_rates():
    spec = load_scenario("office_gate_ev")
    pe = spec["people"]
    assert pe["group_size"]["lam"] == pytest.approx(0.20, abs=0.01) and pe["group_lateral_m"] == 0.72 and pe["speed_density"]["gamma"] == 1.913
    rate, note = resolve_rate(spec, spec["streams"][0]["rate"], pe["group_size"])
    assert note["persons_per_min"] == pytest.approx(12.24 * 0.90, rel=1e-3)
    assert rate["per_min"] == pytest.approx(note["persons_per_min"] / note["mean_group_size"], rel=1e-3)  # note は丸めた値
    # シナリオ・overrides の値が文献の既定より優先
    spec2 = load_scenario("office_gate_ev", {"people": {"group_lateral_m": 0.6}})
    assert spec2["people"]["group_lateral_m"] == 0.6 and spec2["people"]["group_size"]["lam"] == pe["group_size"]["lam"]


def test_corridor_speed(tmp_path):
    # RiMEA の試験 1 に相当: 40 m を 1.33 m/s → 30.1 秒
    api.run("verify_corridor_speed", tmp_path / "c")
    gt = json.loads((tmp_path / "c/ground_truth.json").read_text())
    (p,) = gt["people"].values()
    assert (p["arrive_frame"] - p["start_frame"]) / gt["fps"] == pytest.approx(40 / 1.33, abs=1.0)


def test_validity_outputs(tmp_path):
    api.run("office_gate_ev", tmp_path / "o", overrides={"duration_s": 90, "outputs": ["ground_truth", "frames", "tasks", "validity"]})
    v = json.loads((tmp_path / "o/validity.json").read_text())
    assert v["input_reproduction"]["elevator_boarding_interval"]["verdict"] in ("合う", "対象外")
    items = {r["item"]: r for r in v["ledger"]}
    assert items["歩く速さ"]["source"] == "weidmann1993"
    assert items["EV の着く間隔"]["status"].startswith("仮")
    assert (tmp_path / "o/validity.md").exists()


def test_calibrate_roundtrip(tmp_path):
    # シミュレータの記録（ゲート・EV）で元のシナリオを合わせると、到着の量・EV の間隔がおおむね元に戻る
    from twinsim.calibrate import calibrate, export_logs
    api.run("office_gate_ev", tmp_path / "r", overrides={"duration_s": 180, "outputs": ["ground_truth"]})
    logs = export_logs(tmp_path / "r")
    path, rep = calibrate("office_gate_ev", logs / "gate_log.csv", logs / "ev_log.csv", tmp_path / "cal", cid="t")
    ch = {c["item"]: c for c in rep["changes"]}
    assert ch["commuters: 到着の量"]["mean_per_min"] == pytest.approx(11.0, rel=0.35)
    assert 30 < ch["EV の着く間隔"]["fit"]["median"] < 65
    assert all(f["sha256"] for f in rep["files"])
    spec = load_scenario(str(path))
    assert spec["streams"][0]["rate"]["source"] == "data:t"


def test_output_formats_match_docs(tmp_path):
    # docs/formats.md に書いた列・キーと、実際の出力が合っているか（出力の形を変えたら文書も直す）
    import csv
    import gzip
    run = tmp_path / "r"
    api.run("office_gate_ev", run, overrides={"duration_s": 30})
    with gzip.open(run / "frames.csv.gz", "rt") as fh:
        assert next(csv.reader(fh)) == ["frame", "t", "person", "x", "y", "yaw", "moving", "state", "zone", "group", "type"]
    gt = json.loads((run / "ground_truth.json").read_text())
    assert {"fps", "total_frames", "seed", "space", "scenario", "people", "tracks", "moving", "cameras", "gate_events", "elevator_events",
            "gates", "zones"} <= set(gt)
    p = next(iter(gt["people"].values()))
    assert {"model", "kind", "height_m", "tint_index", "type", "stream", "origin", "destination", "flow", "group", "start_frame", "arrive_frame",
            "speed_m_s", "states", "events"} <= set(p)
    cam = next(iter(gt["cameras"].values()))
    assert {"world_to_camera_rowmajor", "fx_px", "fy_px", "cx_px", "cy_px", "width", "height", "eye", "target"} <= set(cam)
    mot = (run / "mot" / f"{next(iter(gt['cameras']))}.txt").read_text().splitlines()
    assert mot and all(len(line.split(",")) == 9 for line in mot[:20]) and int(mot[0].split(",")[0]) >= 1
    assert all(len(line.split()) == 9 for line in (run / "aicity/gt.txt").read_text().splitlines()[:20])
    tasks = json.loads((run / "tasks.json").read_text())
    assert {"1_count", "2_direction", "3_dwell", "4_group", "5_congestion", "6_trend", "elevator"} <= set(tasks)
    assert (run / "graph/zone_counts.csv").read_text().startswith("t,")
    assert (run / "graph/zone_flows.csv").read_text().startswith("minute,source,target,count")


def test_ward_layout_matches_docs():
    # docs/formats.md の 10（病棟の配置と道のり）のキーと、道のりの行列の大きさ
    from twinsim.ward import ward_layout
    w = ward_layout("hospital")
    assert {"space", "beds", "layouts", "points", "names", "dist_m", "source", "note"} <= set(w)
    n = len(w["names"])
    assert len(w["dist_m"]) == n and all(len(r) == n for r in w["dist_m"])
    assert all(w["dist_m"][i][i] == 0 for i in range(n)) and all(d >= 0 for r in w["dist_m"] for d in r)
    # 道の点の列: 両端がステーションとベッドで、長さは道のりと大きくは変わらない（間引いた分だけ短く、両端の分だけ長い）
    i = {k: x for x, k in enumerate(w["names"])}
    assert len(w["paths"]) == sum(len(s) for s in w["layouts"].values()) * len(w["beds"])
    for key, pts in w["paths"].items():
        st, bed = key.split("|")
        assert pts[0] == [round(v, 2) for v in w["points"][st]] and pts[-1] == [round(v, 2) for v in w["points"][bed]]
        length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        assert 0.85 * w["dist_m"][i[st]][i[bed]] - 0.5 <= length <= w["dist_m"][i[st]][i[bed]] + 0.5  # 両端は格子に寄せる前の点


def test_gate_headway_and_arrivals_when_queue_spills_outside(tmp_path):
    """ゲートで運べる量より多く入れる確かめ: 列ができたときの間隔を 10 回以上測れ（前の人が通る前に列で止まっていた人）、
    終わりまで外で待った人も到着に数え、列の人も含めて止まった人がいない（2026-11-06）。"""
    r = twinsim.simulate({**twinsim.template("verify_gate_capacity"), "seed": 2, "cameras": [], "outputs": ["ground_truth", "validity"]},
                         out_dir=tmp_path / "r")
    v = r.validity()
    gh = v["input_reproduction"]["gate_headway"]
    assert gh["n"] >= 10 and gh["verdict"] == "合う"
    arr = v["input_reproduction"]["arrivals"]["rush"]
    assert arr.get("outside_at_end", 0) > 0 and arr["verdict"] == "合う"
    assert v["emergent"]["gridlock"]["n_stuck"] == 0


def test_arrival_dispersion_from_group_sizes():
    """到着の人数の分散 ÷ 平均 = 人の側から見たグループの人数の平均（グループがなければ 1）。"""
    from types import SimpleNamespace

    from twinsim.literature import ztp_person_share
    from twinsim.validity import arrival_dispersion
    run = SimpleNamespace(spec={"people": {"group_size": {"type": "zero_truncated_poisson", "lam": 0.5}},
                                "streams": [{"name": "a"}, {"name": "b", "group_size": None}]})
    share = ztp_person_share(0.5, 5)
    assert abs(arrival_dispersion(run, "a") - sum((k + 1) * x for k, x in enumerate(share))) < 1e-9
    assert arrival_dispersion(SimpleNamespace(spec={"streams": [{"name": "c"}]}), "c") == 1.0


def test_free_speed_is_compared_with_given_speeds():
    """自由に歩く速さ: 前に人のいない人が遅い人に偏っていても、その人たちに与えた速さどおりに歩き、全員に与えた速さが文献の分布なら「合う」
    （混んだ流れでは速い人ほど前に人がいて測れず、前は文献の値とじかに比べて「注意」になった、2026-11-06）。"""
    from types import SimpleNamespace

    from twinsim.validity import free_speed
    rng = np.random.default_rng(0)
    given = np.clip(rng.normal(1.34, 0.26, 200), 0.8, 1.9)
    P = {f"P{i}": {"group": None, "info": {"speed_m_s": float(v)}} for i, v in enumerate(given)}
    slow = [n for n, d in P.items() if d["info"]["speed_m_s"] < 1.4]  # 測れるのは遅い人だけ
    rows = [(n, f, P[n]["info"]["speed_m_s"], 0.0, "pass", True, 0) for n in slow for f in range(3)]
    res, _ = free_speed(SimpleNamespace(P=P, spec={}), rows)
    assert res["mean_m_s"] < 1.25 and res["verdict"] == "合う"
    res2, _ = free_speed(SimpleNamespace(P=P, spec={}), [(n, f, 0.9 * v, rho, st, mv, k) for n, f, v, rho, st, mv, k in rows])
    assert res2["verdict"] == "注意"  # 与えた速さより 1 割遅い


def test_standing_spacing_counts_only_waiting_people():
    """待つ人どうしの距離: 横を歩いて通る人は数えない（歩く人との近さは重なりで見る、2026-11-06）。"""
    from types import SimpleNamespace

    from twinsim.validity import standing_spacing
    n = 30 * 40
    P = {"A": {"f0": 0, "xy": np.tile([0.0, 0.0], (n, 1)), "state": ["gate_queue"] * n, "group": None},
         "B": {"f0": 0, "xy": np.tile([1.0, 0.0], (n, 1)), "state": ["gate_queue"] * n, "group": None},
         "W": {"f0": 0, "xy": np.c_[np.linspace(-5, 5, n), np.full(n, 0.3)], "state": ["pass"] * n, "group": None}}
    run = SimpleNamespace(gt={"total_frames": n}, fps=30, P=P, at=lambda name, f: f if 0 <= f < n else None)
    res, _ = standing_spacing(run)
    assert res["share_below_0.45m"] == 0.0 and res["verdict"] == "合う"
