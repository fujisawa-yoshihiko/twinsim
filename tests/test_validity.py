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


def test_mopf_synthetic(tmp_path):
    # 正解から作った MOPF の形の追跡（誤りなし）で評価すると MOTA・IDF1 が 1、見逃し 20% で再現率が約 0.8
    from twinsim import mopf
    run = tmp_path / "r"
    api.run("office_gate_ev", run, overrides={"duration_s": 60, "outputs": ["ground_truth", "graph", "mot", "aicity"]})
    clean = mopf.synthetic_tracks(run, "CamGate", tmp_path / "clean", jitter_px=1.0, miss=0.0)
    r = mopf.evaluate(run, clean)["cameras"]["CamGate"]
    assert r["mota"] == pytest.approx(1.0) and r["idf1"] == pytest.approx(1.0) and r["num_switches"] == 0
    miss = mopf.synthetic_tracks(run, "CamGate", tmp_path / "miss", jitter_px=1.0, miss=0.2, seed=3)
    assert mopf.evaluate(run, miss)["cameras"]["CamGate"]["recall"] == pytest.approx(0.8, abs=0.05)
    g = mopf.graph(run, clean)
    assert "gate_area" in g["CamGate"]["zones_compared"]
    mopf.write(run, "CamGate")
    e = mopf.expect(run, "CamGate")
    assert e["lines"][0]["to_pos"] > 0
    assert (run / "aicity/gt.txt").read_text().split("\n")[0].count(" ") == 8


def test_identities_synthetic(tmp_path):
    # 正解から作った追跡（誤りなし）では、2 台に映った人はどちらのカメラでも ID が 1 本で、カメラの間の移動が出る
    from twinsim import mopf
    run = tmp_path / "r"
    api.run("office_gate_ev", run, overrides={"duration_s": 90, "outputs": ["ground_truth", "graph", "mot"]})
    for cam in ("CamGate", "CamEV"):
        mopf.synthetic_tracks(run, cam, tmp_path / "t", jitter_px=1.0, miss=0.0)
    res, _ = mopf.identities(run, tracks_dir=tmp_path / "t")
    both = [p for p in res["persons"].values() if p["handovers"]]
    assert both and all(len({s["mopf_id"] for s in p["cams"][c]}) == 1 for p in both for c in p["cams"])
    assert all(len({s["person"] for s in segs}) == 1 for c in res["cameras"] for segs in res["mopf_ids"][c].values())
    assert (run / "mopf_eval/identities.csv").exists()


def test_linking_synthetic(tmp_path):
    # 正解から作った追跡（動画なし = 色なし）でも推論と採点が通り、時間の方式がつながない場合より IDF1 を下げない
    from twinsim import mopf
    run = tmp_path / "r"
    api.run("office_gate_ev", run, overrides={"duration_s": 90, "outputs": ["ground_truth", "graph", "mot"]})
    for cam in ("CamGate", "CamEV"):
        mopf.synthetic_tracks(run, cam, tmp_path / "t", jitter_px=1.0, miss=0.0)
    out = mopf.link(run, tracks_dir=tmp_path / "t")
    m = out["metrics"]
    assert m["none"]["cross_links"] == 0 and "color" not in m  # 動画がないので色の方式は除く
    assert m["time"]["idf1"] >= m["none"]["idf1"] - 1e-9
    # 階層クラスタリング（hc:）も通る: 同じカメラで同時に映るトラックレットは同じ番号にならない
    out2 = mopf.link(run, tracks_dir=tmp_path / "t", apps=["color"], methods=["none", "time", "hc:time"], best="hc:time")
    assert "hc:time" in out2["metrics"]
    by_g = {}
    for t in out2["tracklets"]:
        by_g.setdefault((t["global_id"], t["camera"]), []).append((t["t0"], t["t1"]))
    for spans in by_g.values():
        spans.sort()
        assert all(b0 >= a1 - 0.5 for (_, a1), (b0, _) in zip(spans, spans[1:]))
    assert all(c["cost"] <= 0 for c in out["cross_links"])
    assert (run / "mopf_eval/links.json").exists() and (run / "mopf_eval/links.csv").exists()


def test_reid_embedder():
    # OSNet x0.25（MOPF と同じ重み）の特徴: L2 で正規化され、同じ画像は同じ特徴、違う色の画像は離れる。重みがなければ飛ばす
    pytest.importorskip("torch")
    import numpy as np

    from twinsim.reid import MODELS, Embedder
    if not MODELS["osnet_x0_25_msmt17"]["weights"].exists():
        pytest.skip("OSNet の重みがない")
    e = Embedder("osnet_x0_25_msmt17", threads=2)
    red = np.zeros((160, 64, 3), np.uint8)
    red[..., 2] = 220
    blue = np.zeros((160, 64, 3), np.uint8)
    blue[..., 0] = 220
    f = e([red, red, blue])
    assert f.shape == (3, 512) and np.allclose(np.linalg.norm(f, axis=1), 1.0, atol=1e-4)
    assert float(f[0] @ f[1]) > 0.999 and float(f[0] @ f[2]) < float(f[0] @ f[1])
    if MODELS["clipreid_vitb16_msmt17"]["weights"].exists():  # CLIP-ReID（1280 次元）も同じ約束
        g = Embedder("clipreid_vitb16_msmt17", threads=2)([red, red, blue])
        assert g.shape == (3, 1280) and float(g[0] @ g[1]) > 0.999 and float(g[0] @ g[2]) < 0.999


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
