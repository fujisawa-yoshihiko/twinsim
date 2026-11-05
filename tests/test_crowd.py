"""人の動き（motion_model "cfsm"、Collision-Free Speed Model）の確かめ（CPU だけ、数秒）。"""

import math

import numpy as np
import pytest

import twinsim
from twinsim.engine import Agent, Sim
from twinsim.space import load_space


def min_distance(a, b):
    fa = {f: (x, y) for f, x, y, _, _ in a.frames}
    ds = [math.hypot(x - fa[f][0], y - fa[f][1]) for f, x, y, _, _ in b.frames if f in fa]
    return min(ds) if ds else math.inf


def test_walker_goes_around_standing_person():
    """廊下の真ん中に立っている人を、歩く人は体が重ならないようによけて通る（前のモデルが通り抜けたのは、混んだ所で横へずれきれないとき）。"""
    sp = load_space("corridor")
    sim = Sim(sp, 30, 30 * 45)
    stand = Agent("P0001", [("walk", (20.0, 0.0), "pass"), ("stop", 60.0, None, "dwell", 0.0)], 0.0, 1.3, 0.0, info={"origin_xy": (19.0, 0.0)})
    walk = Agent("P0002", [("walk", (40.0, 0.0), "pass")], 3.0, 1.3, 0.0, info={"origin_xy": (5.0, 0.0)})
    sim.add(stand)
    sim.add(walk)
    sim.run()
    assert walk.mode == "done"
    assert min_distance(stand, walk) >= 0.33


def test_head_on_pair_passes():
    """向かい合って歩く 2 人は、同じ側（左）へよけてすれ違い、止まらない。"""
    sp = load_space("corridor")
    sim = Sim(sp, 30, 30 * 40)
    a = Agent("P0001", [("walk", (45.0, 0.0), "pass")], 0.0, 1.3, 0.0, info={"origin_xy": (5.0, 0.0)})
    b = Agent("P0002", [("walk", (5.0, 0.0), "pass")], 0.0, 1.3, 0.0, info={"origin_xy": (45.0, 0.0)})
    sim.add(a)
    sim.add(b)
    sim.run()
    assert a.mode == "done" and b.mode == "done"
    assert min_distance(a, b) >= 0.33


def test_counterflow_has_no_overlap_or_gridlock(tmp_path):
    r = twinsim.simulate({**twinsim.template("verify_counterflow"), "duration_s": 90}, out_dir=tmp_path / "r")
    em = r.validity()["emergent"]
    assert em["gridlock"]["n_stuck"] == 0
    gt = r.ground_truth()
    P = {n: {f: xy for f, xy in zip(range(p["start_frame"], p["start_frame"] + len(gt["tracks"][n])), gt["tracks"][n])} for n, p in gt["people"].items()}
    close = 0
    for f in range(0, int(gt["total_frames"]), 5):
        xy = np.array([v[f][:2] for v in P.values() if f in v])
        if len(xy) > 1:
            d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
            close += int((d[np.triu_indices(len(xy), 1)] < 0.3).sum())
    assert close == 0


def test_lane_model_still_available(tmp_path):
    """前のモデル（lane）も選べる。知らない名前・知らない cfsm のキーは誤り。"""
    r = twinsim.simulate({**twinsim.template("verify_corridor_speed"), "people": {"motion_model": "lane"}}, out_dir=tmp_path / "r")
    assert r.summary["motion"]["model"] == "lane"
    with pytest.raises(ValueError, match="motion_model"):
        Sim(load_space("corridor"), 30, 10, motion_model="social_force")
    with pytest.raises(ValueError, match="people.cfsm"):
        Sim(load_space("corridor"), 30, 10, cfsm={"strength": 1.0})
