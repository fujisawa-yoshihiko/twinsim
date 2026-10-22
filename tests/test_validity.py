"""文献に基づく分布・実データで合わせる・MOPF との連携の確かめ（CPU だけ、十数秒）:
  uv run --no-project --with numpy --with scipy --with pyyaml --with pillow --with networkx --with matplotlib --with motmetrics --with pytest pytest -q tests"""

import json
import math

import pytest

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


def test_mopf_link_synthetic(tmp_path):
    # 正解から作った MOPF の形の追跡（誤りなし）で評価すると MOTA・IDF1 が 1、見逃し 20% で再現率が約 0.8
    from twinsim import mopf, mopf_link
    run = tmp_path / "r"
    api.run("office_gate_ev", run, overrides={"duration_s": 60, "outputs": ["ground_truth", "graph", "mot", "aicity"]})
    clean = mopf_link.synthetic_tracks(run, "CamGate", tmp_path / "clean", jitter_px=1.0, miss=0.0)
    r = mopf_link.evaluate(run, clean)["cameras"]["CamGate"]
    assert r["mota"] == pytest.approx(1.0) and r["idf1"] == pytest.approx(1.0) and r["num_switches"] == 0
    miss = mopf_link.synthetic_tracks(run, "CamGate", tmp_path / "miss", jitter_px=1.0, miss=0.2, seed=3)
    assert mopf_link.evaluate(run, miss)["cameras"]["CamGate"]["recall"] == pytest.approx(0.8, abs=0.05)
    g = mopf_link.graph(run, clean)
    assert "gate_area" in g["CamGate"]["zones_compared"]
    mopf.write(run, "CamGate")
    e = mopf_link.expect(run, "CamGate")
    assert e["lines"][0]["to_pos"] > 0
    assert (run / "aicity/gt.txt").read_text().split("\n")[0].count(" ") == 8
