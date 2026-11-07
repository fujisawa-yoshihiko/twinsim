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


def test_hospital_elevator_car_is_blocked_and_portal():
    """hospital の EV は描画で置くかご（levels の blocked）。かごの所は歩けず、扉の点は歩ける。乗る人が消える所はかごの中（出入り口の範囲）。"""
    sp = load_space("hospital")
    assert sp.walkable(-28.5, 13.2) and not sp.walkable(-28.5, 14.2) and not sp.walkable(-29.3, 15.0)
    assert sp.in_portal(-28.5, 14.2) == "EV"


def test_door_has_separate_lane_for_people_leaving():
    """扉の向こう（hidden）がある入口は、入る人と出る人で 2 本の線。入る人は元の線、出る人はその横 0.6 m（左側通行で左、壁なら右）。
    1 本の線では、入る人が続くあいだ出る人が線に入れず、扉の横の角で止まった（hospital のロビーの入口、2026-11-06）。"""
    from twinsim.scenario import Builder, load_scenario
    o_in, o_out, n = load_space("hospital").door_lanes("lobby_entrance")
    assert o_in == 0.0 and abs(o_out - 0.6) < 1e-9 and n[1] > 0.99  # 出る向き（東）の左 = 北
    office = load_space("office")
    assert office.door_lanes("entrance")[:2] == (0.0, -0.6)  # 出る向き（北）の左（西）は壁なので右
    assert office.door_lanes("south_exit")[:2] == (0.0, 0.0)  # 出口だけの扉は 1 本
    steps = Builder(load_scenario({"space": "hospital"})).plan_for("lobby_entrance")
    assert steps[0][0] == "walk" and abs(steps[0][1][1] - (-0.4)) < 1e-9 and steps[1] == ("straight", (11.8, -0.4), "pass")
    lane = Builder(load_scenario({"space": "hospital", "people": {"motion_model": "lane"}})).plan_for("lobby_entrance")
    assert lane[1] == ("straight", (11.8, -1.0), "pass")  # 前のモデルは 1 本のまま
    portal = next(q for q in load_space("hospital").portals() if q["name"] == "lobby_entrance")
    assert portal["a"] == (8.5, -0.7)  # 出入り口の範囲は 2 本の真ん中


def test_people_leave_against_entering_stream(tmp_path):
    """入る人が 50 人/分続く入口へ、ロビーから出ていく人が止まらずに出られる（1 本の線では止まった）。"""
    cfg = {"space": "hospital", "seed": 1, "duration_s": 90, "outputs": ["ground_truth"],
           "streams": [{"name": "in", "origin": "lobby_entrance", "rate": {"type": "constant", "per_min": 50, "unit": "persons"},
                        "destinations": [{"to": "west_room", "p": 1.0}]},
                       {"name": "out", "origin": {"xy": [4.0, 0.5]}, "rate": {"type": "constant", "per_min": 8, "unit": "persons"},
                        "destinations": [{"to": "lobby_entrance", "p": 1.0}]}]}
    gt = twinsim.simulate(cfg, out_dir=tmp_path / "r").ground_truth()
    out = [p for p in gt["people"].values() if p["stream"] == "out" and p["start_frame"] < 60 * 30]
    assert len(out) >= 5
    assert all(p["arrive_frame"] < gt["total_frames"] - 1 for p in out), [(p["start_frame"], p["arrive_frame"]) for p in out]


def _gate_sim():
    from twinsim.scenario import build, load_scenario
    sim, _ = build(load_scenario({**twinsim.template("verify_gate_capacity"), "streams": []}))
    g = next(iter(sim.gates.values()))
    return sim, g


def _queued(sim, g, name, lane, xy, mode="to_gate"):
    a = Agent(name, [("gate", g.name)], 0.0, 1.3, 0.0, info={"origin_xy": (-3.4, 23.5)})
    sim.add(a)
    a.k, a.mode, a.state, a.lane, a.gate_dir = 0, mode, "gate_queue", lane, g.in_dir
    a.xy = np.array(xy, float)
    sim.here[a.name] = a.xy.copy()
    lane.queue.append(a)
    from twinsim.engine import Path as EPath
    a.path, a.s = EPath([tuple(xy), tuple(lane.center)]), 0.0
    return a


def test_gate_walkers_swap_lanes_when_blocking_each_other():
    """隣のレーンへ斜めに向かう 2 人が互いにふさいだら、レーンを入れ替える（ゲートの手前はよけないので、2 人とも止まり、列が全部止まった）。"""
    sim, g = _gate_sim()
    west, east = sorted(g.lanes_in, key=lambda ln: ln.center[0])[:2]
    a = _queued(sim, g, "A", west, (east.center[0] - 0.2, 17.8))  # 東にいて西のレーンへ
    b = _queued(sim, g, "B", east, (west.center[0] + 0.35, 17.8))  # 西にいて東のレーンへ
    a.blocker, b.blocker = b, a
    sim.swap_crossing(g, 10.0)
    assert a.lane is east and b.lane is west and east.queue == [a] and west.queue == [b] and sim.lane_swaps == 1
    sim.swap_crossing(g, 10.5)  # すぐ後はもう一度入れ替えない
    assert a.lane is east and sim.lane_swaps == 1


def test_gate_head_swaps_with_later_person_in_its_way():
    """列の先頭が、列の順で後ろの人（先頭の場所の手前で立っている）にふさがれたら、順を入れ替える。横に並んで互いにふさいでいる 2 人は入れ替えない。"""
    sim, g = _gate_sim()
    lane = g.lanes_in[0]
    head = _queued(sim, g, "A", lane, (lane.center[0] + 0.36, 16.9))
    second = _queued(sim, g, "B", lane, (lane.center[0], 16.98), mode="gate_wait")
    head.blocker = second
    sim.swap_crossing(g, 10.0)
    assert lane.queue == [second, head] and sim.lane_swaps == 1
    sim2, g2 = _gate_sim()
    lane2 = g2.lanes_in[0]
    p = _queued(sim2, g2, "A", lane2, (lane2.center[0] - 0.17, 17.7))
    q = _queued(sim2, g2, "B", lane2, (lane2.center[0] + 0.18, 17.7))
    p.blocker, q.blocker = q, p
    sim2.swap_crossing(g2, 10.0)
    assert lane2.queue == [p, q] and sim2.lane_swaps == 0


def test_boarding_walker_progresses_at_inside_of_corner():
    """扉の向こうへ歩く人（かごに乗る人）が、線から横の上限（NO_WALL_LAT_M）にいて、経路の曲がり角（扉 → かごの奥）の内側にいても進む。
    前は線の点から横へ上限の所へ置き直していて、置き直した所が元の位置に重なり、扉の前で 7 人が 50 秒動けなかった（office、2026-11-06）。"""
    from twinsim.engine import Path as EPath
    from twinsim.scenario import build, load_scenario
    sim, _ = build(load_scenario({**twinsim.template("office_gate_ev"), "streams": []}))
    car = next(c for c in sim.cars if c.name == "EV2")
    a = Agent("P0001", [("exit",)], 0.0, 1.13, 0.0, info={"origin_xy": (-14.0, -0.3)})
    sim.add(a)
    a.path = EPath([(-14.01, -0.29), (-14.5, -1.75), (-15.5, -1.85)])
    a.s, a.l, a.mode, a.state, a.taper, a.no_walls, a.board_car, a.k = 1.06, 0.0, "board", "ev_wait", True, True, car, 0
    a.best_t = 1e9  # 安全弁を使わない
    a.xy = np.array([-14.679, -1.186])  # 線の右 0.35 m、曲がり角の内側（7 人が止まった所）
    s0 = a.s
    for f in range(30):
        sim.t = f / 30
        sim.step_agents(f, f / 30)
    assert a.mode == "done" or a.s > s0 + 0.5


def test_gridlock_does_not_count_round_trips():
    """止まった人の判定: 最後の 30 秒で 0.3 m 未満しか動いていない人。その間に 2 m より遠くへ行って戻った人は数えない
    （ゲートを通って引き返した人が、たまたま 30 秒前と同じ所にいた）。押されて前後に 1 m ほど動きながら進めない人は数える。"""
    from types import SimpleNamespace
    from twinsim.validity import gridlock
    t = np.arange(1200)
    stay = np.c_[np.minimum(t, 200) * 0.01, np.zeros(1200)]  # 2 m 歩いて止まる
    back = np.c_[np.where(t < 750, t * 0.01, (1500 - t) * 0.01), np.zeros(1200)]  # 7.5 m 行って戻る（30 秒前とほぼ同じ所）
    pushed = np.c_[2.0 + 0.5 * np.sin(2 * np.pi * t / 900), np.zeros(1200)]  # その場で前後に 1 m 押される（30 秒で 1 往復）
    run = SimpleNamespace(gt={"total_frames": 1200}, fps=30,
                          P={n: {"f0": 0, "xy": xy, "state": ["pass"] * 1200} for n, xy in (("S", stay), ("B", back), ("X", pushed))})
    assert sorted(gridlock(run)["people"]) == ["S", "X"]


@pytest.mark.parametrize("mates", [False, True])
def test_side_by_side_pair_in_same_lane_does_not_freeze(mates):
    """同じレーンの列の先頭と 2 番目が横に並んで（横 0.35 m）互いを前の人とみても、先頭は前へ進む（列の順が後ろの人は真横なら前の人と見ない）。
    前はレーンが 150 秒止まった（verify_gate_capacity の種 2。グループの仲間どうしでも、2026-11-06）。"""
    sim, g = _gate_sim()
    lane = g.lanes_in[0]
    head = _queued(sim, g, "A", lane, (lane.center[0] + 0.17, 17.2))  # ゲートの 2 m 手前より内側（経路の上をまっすぐ歩き、よけない所）
    second = _queued(sim, g, "B", lane, (lane.center[0] - 0.18, 17.2))
    head.gate_slot, second.gate_slot = 0, 1
    if mates:
        head.group = second.group = "G1"
    y0 = float(head.xy[1])
    for f in range(30):
        sim.t = f / 30
        sim.step_agents(f, f / 30)
    assert y0 - float(sim.where(head)[0][1]) > 0.3


def test_entrance_first_come_first_served(tmp_path):
    """入口で待つ人は着いた順に入る（グループはまとめて）。前は待つ人が 0.2 秒ごとにしか確かめず、あとから着いた人が空いた一瞬を取って、
    2 人連れの 2 人目が外で 47 秒待った。入る人の線がふさがっていれば、出る人の線からも入る（2026-11-06）。"""
    from twinsim.scenario import build, load_scenario
    sim, _ = build(load_scenario({**twinsim.template("verify_gate_capacity"), "duration_s": 90, "seed": 2}))
    sim.run()
    came = sorted((a for a in sim.agents if getattr(a, "door", None) == "entrance" and "start" in a.events), key=lambda a: a.entry_key)
    starts = [a.events["start"] for a in came]
    assert len(came) > 60 and all(b >= a - 1e-9 for a, b in zip(starts, starts[1:]))
    assert sim.entry_alt > 0
    late = [a for a in sim.agents if getattr(a, "door", None) == "entrance" and a.mode == "pending" and a.t0 < 90]
    assert all(a.entry_key > came[-1].entry_key for a in late)  # まだ外で待つ人は、入った人より後に着いた人だけ


def test_group_mates_do_not_appear_on_top_of_each_other(tmp_path):
    """グループの仲間は同じコマに同じ点に現れない（一人が押し出されて扉の柱の外へ回り込んだ、office_gate_ev、2026-11-06）。"""
    from twinsim.scenario import build, load_scenario
    sim, _ = build(load_scenario({**twinsim.template("verify_gate_capacity"), "duration_s": 90, "seed": 2}))
    sim.run()
    by = {}
    for a in sim.agents:
        if a.group is not None and a.frames:
            by.setdefault(a.group, []).append(a)
    pairs = [g for g in by.values() if len(g) == 2]
    assert pairs
    for a, b in pairs:
        f = max(a.frames[0][0], b.frames[0][0])
        pa = next((x, y) for ff, x, y, *_ in a.frames if ff == f)
        pb = next((x, y) for ff, x, y, *_ in b.frames if ff == f)
        assert math.hypot(pa[0] - pb[0], pa[1] - pb[1]) >= 0.3


def test_reroute_keeps_part_beyond_walkable_area():
    """経路を引き直すとき、行き先が歩ける所の外（EV のかごの中）なら、歩ける所の最後の点まで探し、その先は元の経路のまま足す
    （前は歩ける所の手前で終わる経路になり、乗る人が扉の外で「乗った」ことになって消えた、office_ev_hall、2026-11-06）。"""
    from twinsim.engine import Path as EPath
    from twinsim.scenario import build, load_scenario
    sim, _ = build(load_scenario({**twinsim.template("office_ev_hall"), "streams": []}))
    car = next(c for c in sim.cars if c.name == "EV1")
    door, cabin = tuple(map(float, car.door)), tuple(map(float, car.cabin))
    assert sim.space.walkable(*door) and not sim.space.walkable(*cabin)
    pts = sim.reroute_pts((-12.7, -3.7), EPath([(-13.1, -3.0), door, cabin]))
    assert math.hypot(pts[-1][0] - cabin[0], pts[-1][1] - cabin[1]) < 1e-6
    assert all(sim.space.walkable(*q) for q in pts[:-4])


def test_group_member_waits_for_mate_at_stop():
    """止まる段取り（受付など）を先に済ませたグループの人は、同じ段取りの仲間が済むまで待つ（着く時刻がずれて先に歩き出し、
    受付へ行く 2 人連れが 10 m 離れて歩いた、hospital_gate_ev、2026-11-06）。"""
    sp = load_space("corridor")
    sim = Sim(sp, 30, 30 * 40)
    plan = [("walk", (20.0, 0.0), "pass"), ("stop", 5.0, None, "dwell", 0.0), ("walk", (40.0, 0.0), "pass")]
    a = Agent("P0001", list(plan), 0.0, 1.3, 0.0, group="G1", info={"origin_xy": (18.0, 0.0)})  # 先に着く
    b = Agent("P0002", list(plan), 0.0, 1.3, 0.0, group="G1", info={"origin_xy": (5.0, 0.0)})  # 11 秒ほど後に着く
    sim.add(a)
    sim.add(b)
    sim.run()
    at = {f: x for f, x, _y, _yaw, _m in a.frames}
    assert abs(at[30 * 12] - 20.0) < 0.6  # 自分の 5 秒が済んだ後も、仲間が済むまで受付にいる
    assert a.mode == "done" and b.mode == "done"


def test_stalled_walker_asks_standing_people_to_step_aside():
    """前の人はいないのに 3 秒以上進めずにいる歩く人は、行き先の向きの前側 0.9 m 以内に立つ人に、横へよけてもらう
    （EV を待つ人たちのあいだで、押される向きが毎コマ変わって降りた人が 28 秒進めなかった、2026-11-06）。"""
    sp = load_space("corridor")
    sim = Sim(sp, 30, 30 * 10)
    stand = Agent("P0001", [("stop", 60.0, None, "dwell", 0.0)], 0.0, 1.3, 0.0, info={"origin_xy": (20.5, 0.55)})
    walk = Agent("P0002", [("walk", (40.0, 0.0), "pass")], 0.0, 1.3, 0.0, info={"origin_xy": (20.0, 0.0)})
    for a in (stand, walk):
        sim.add(a)
        sim.next_step(a, 0.0, a.info["origin_xy"])
        a.events["start"] = 0.0
    walk.xy = np.array([20.0, 0.0])
    sim.here[walk.name] = walk.xy.copy()
    sim.t = 4.0
    walk.best_t, walk.best_path = 0.0, walk.path  # 4 秒進めずにいる
    sim.step_agents(120, 4.0)
    assert getattr(stand, "nudge", None) is not None and stand.nudge[0][1] > 0  # 歩く人の左（北）へよける


def _run_frames(sim, t0, f0, seconds):
    n = int(round(seconds / sim.dt))
    for k in range(n):
        sim.t = t0 + k * sim.dt
        sim.step_agents(f0 + k, sim.t)
    return t0 + n * sim.dt, f0 + n


def test_person_who_stepped_aside_returns_to_spot():
    """道をあけた人は、歩く人が離れたら元の立つ場所へ戻る（よけた先で隣の人と体が触れたまま 30 秒立っていた、hospital の EV 前 mid の v4、2026-11-07）。"""
    sim = Sim(load_space("corridor"), 30, 30 * 20)
    stand = Agent("P0001", [("stop", 60.0, None, "dwell", 0.0)], 0.0, 1.3, 0.0, info={"origin_xy": (20.5, 0.55)})
    sim.add(stand)
    sim.next_step(stand, 0.0, stand.info["origin_xy"])
    stand.events["start"] = 0.0
    home = sim.here[stand.name].copy()
    stand.nudge = (np.array([0.0, 1.0]), 1.5)  # 1.5 秒、北へよける
    t, f = _run_frames(sim, 0.0, 0, 1.5)
    assert float(np.hypot(*(sim.here[stand.name] - home))) > 0.3
    _run_frames(sim, t, f, 4.0)
    assert float(np.hypot(*(sim.here[stand.name] - home))) < 0.05


@pytest.mark.parametrize("mates", [False, True])
def test_waiting_strangers_in_contact_move_apart(mates):
    """EV を待つ人は、隣の知らない立つ人と 0.45 m より近ければ、空いていれば少し離れる（グループの仲間とは離れない）。"""
    sim = Sim(load_space("corridor"), 30, 30 * 20)
    people = [Agent(f"P000{k + 1}", [("stop", 60.0, None, "dwell", 0.0)], 0.0, 1.3, 0.0, info={"origin_xy": (20.0 + 0.36 * k, 0.0)},
                    group="G001" if mates else None) for k in range(2)]
    for a in people:
        sim.add(a)
        sim.next_step(a, 0.0, a.info["origin_xy"])
        a.events["start"] = 0.0
        a.mode = "wait"
        sim.stand(a, 0.0, sim.here[a.name], "ev_wait")
    _run_frames(sim, 0.0, 0, 3.0)
    d = float(np.hypot(*(sim.here["P0001"] - sim.here["P0002"])))
    assert (abs(d - 0.36) < 1e-6) if mates else (0.449 <= d <= 0.36 + 2 * 0.4)


@pytest.mark.parametrize("lat", [0.4, 0.55])
def test_walker_held_back_by_standing_pair_stands_still(lat):
    """並んで立つ 2 人の間へ向かう歩く人は、行き先へ引く向きと 2 人から離れる向きが釣り合う所で止まる。前は和の向きが毎コマ逆になり、
    その向きの空きの速さ（1.3 m/s）で前後に跳ね、歩く姿勢のままその場で揺れた（素材 v5 の EV の前、2026-11-08）。"""
    sim = Sim(load_space("corridor"), 30, 30 * 10)
    stand = [Agent(f"P000{k + 1}", [("stop", 60.0, None, "dwell", 0.0)], 0.0, 1.3, 0.0, info={"origin_xy": (20.0, s * lat)})
             for k, s in enumerate((1, -1))]
    walk = Agent("P0003", [("walk", (40.0, 0.0), "pass")], 0.0, 1.34, 0.0, info={"origin_xy": (17.0, 0.0)})
    for a in stand + [walk]:
        sim.add(a)
        sim.next_step(a, 0.0, a.info["origin_xy"])
        a.events["start"] = 0.0
    _run_frames(sim, 0.0, 0, 2.9)  # 3 秒進めないと立つ人に道をあけてもらうので、その前まで
    fr = np.array([(x, y, yaw, m) for _, x, y, yaw, m in walk.frames])
    step = np.diff(fr[:, :2], axis=0)
    big = np.flatnonzero(np.hypot(*step.T) > 0.005)
    reversals = sum(float(step[i] @ step[j]) < 0 for i, j in zip(big[:-1], big[1:]))
    assert fr[-1, 0] < 20.0 - 0.6  # 2 人の手前で止まる
    assert reversals <= 2
    assert float(np.hypot(*step[-30:].T).sum()) < 0.1  # 最後の 1 秒はほとんど動かない
    assert np.ptp(fr[-30:, 2]) < 5 and not fr[-30:, 3].any()  # 体の向きは振れず、立つ姿勢


def test_boarder_waiting_for_alighting_people_steps_aside():
    """扉の前で降りる人を待つ乗る人も、進めずにいる人に頼まれたら横へよける（前は扉の前に立ったままで、降りる人が揺れながら抜けていた。
    揺れをなくすと降りるのに 20〜50 秒かかり、乗る人も待ち続けた、hospital_gate_ev の種 13、2026-11-08）。"""
    sp = load_space("corridor")
    sim = Sim(sp, 30, 30 * 10)
    walk = Agent("P0002", [("walk", (40.0, 0.0), "pass")], 0.0, 1.3, 0.0, info={"origin_xy": (20.0, 0.0)})
    board = Agent("P0001", [("walk", (10.0, 0.55), "pass")], 0.0, 1.3, 0.0, info={"origin_xy": (20.5, 0.55)})
    for a in (walk, board):  # 歩く人が先に動く
        sim.add(a)
        sim.next_step(a, 0.0, a.info["origin_xy"])
        a.events["start"] = 0.0
    board.mode, board.waiting_alight = "board", True
    sim.t = 4.0
    walk.best_t, walk.best_path = 0.0, walk.path  # 4 秒進めずにいる
    sim.step_agents(120, 4.0)
    assert getattr(board, "nudge", None) is not None and board.nudge[0][1] > 0  # 歩く人の左（北）へよける
