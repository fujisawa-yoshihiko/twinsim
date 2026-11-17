"""グループの組み方（1.2、motion_model "cfsm"）の確かめ（CPU だけ、数十秒）。値の根拠は docs/validity.md の 5.8・docs/roadmap.md の 1.2。"""

import math

import numpy as np
import pytest

import twinsim
from twinsim.engine import FORM_FILE_GAP, Agent, Sim, group_slots
from twinsim.literature import GROUP_DENSITY, GROUP_RELATIONS, group_lateral_scale
from twinsim.space import load_space


def test_group_slots_follow_literature():
    """持ち場: 2 人連れは関係ごとの横の間隔で横に並び、3 人組は V 字（真ん中が 0.14 m 後ろ）、密度で横が狭まり、狭すぎると縦 1 列。"""
    d = group_slots(2, "colleagues")
    assert d[0][0] - d[1][0] == pytest.approx(GROUP_RELATIONS["colleagues"]["dyad"]["x"]) and d[0][1] == d[1][1] == 0.0
    t = group_slots(3, "family")
    assert t[0][0] - t[2][0] == pytest.approx(GROUP_RELATIONS["family"]["triad"]["x"])
    assert t[1] == (0.0, -GROUP_DENSITY["triad_v_m"])
    # Zanlungo ら 2015: 0.3 人/m² で 2 人連れの横は 0.646 − 0.538 × 0.3 の 0.646 に対する比
    s = group_lateral_scale(2, 0.3)
    assert s == pytest.approx((0.646 - 0.538 * 0.3) / 0.646)
    d3 = group_slots(2, "friends", scale=s)
    assert d3[0][0] - d3[1][0] == pytest.approx(0.662 * s)
    file_ = group_slots(3, "friends", scale=group_lateral_scale(3, 0.6))
    assert [lat for lat, _ in file_] == [0.0, 0.0, 0.0] and file_[2][1] == pytest.approx(-2 * FORM_FILE_GAP)
    assert group_slots(2, "friends", lateral_m=0.5)[0][0] == pytest.approx(0.25)  # 設定の group_lateral_m


def _pair(sim, rel, start=(5.0, 0.0), goal=(45.0, 0.0), t0=0.0, names=("P0001", "P0002"), group="G1", speed=1.2):
    slots = group_slots(2, rel, sim.group_lateral_m)
    made = []
    step = ("walk", goal, "pass")  # 仲間は同じ段取りの要素を共有する（scenario.Builder と同じ。持ち場へ寄るのは同じ段取りを歩く間だけ）
    for k, n in enumerate(names):
        a = Agent(n, [step], t0 + 0.2 * k, speed, slots[k][0], group=group,
                  info={"origin_xy": (start[0], start[1] + slots[k][0]), "relation": rel})
        sim.add(a)
        made.append(a)
    return made


def test_pair_walks_abreast_at_literature_spacing():
    """仲間は先導の人からの持ち場へ寄り、廊下を横に並んで歩く（前は仲間がそれぞれ自分の経路を歩き、2〜4 m 離れることがあった）。"""
    sim = Sim(load_space("corridor"), 30, 30 * 40)
    a, b = _pair(sim, "friends")
    sim.run()
    pa = {f: (x, y) for f, x, y, *_ in a.frames}
    lat, lon = [], []
    for f, x, y, *_ in b.frames:
        if f in pa and 15.0 < pa[f][0] < 35.0:
            lat.append(abs(y - pa[f][1]))
            lon.append(abs(x - pa[f][0]))
    assert lat
    assert np.mean(lat) == pytest.approx(GROUP_RELATIONS["friends"]["dyad"]["x"], abs=0.1)
    assert np.mean(lon) < 0.7  # 前後は揺らぐが、離れない


def test_stranger_does_not_walk_between_pair():
    """後ろから来る速い知らない人は、横に並ぶ 2 人の間に割り込まず、外側から追い越す（仲間を結ぶ線をよける。1.1 では混んだ流れで、
    知らない人が仲間の間に入ったまま歩いた）。2 人の間は 1.0 m あけ、線をよけなければ真ん中を抜ける場面にする（間が 0.7 m ほどなら、体の幅で
    もともと抜けられない）。正面から来る人には、間の広い 2 人が左右に開いて通すことがある（人でもある動きなので、そのままにしている）。"""
    sim = Sim(load_space("corridor"), 30, 30 * 50, group_lateral_m=1.0)
    a, b = _pair(sim, "colleagues", start=(10.0, 0.0), speed=0.9)
    c = Agent("P0003", [("walk", (45.0, 0.0), "pass")], 3.0, 1.7, 0.0, info={"origin_xy": (5.0, 0.0)})
    sim.add(c)
    sim.run()
    assert c.mode == "done" and a.mode == "done" and b.mode == "done"
    pa = {f: np.array((x, y)) for f, x, y, *_ in a.frames}
    pb = {f: np.array((x, y)) for f, x, y, *_ in b.frames}
    pc = {f: np.array((x, y)) for f, x, y, *_ in c.frames}
    crossed = 0
    for f in sorted(pc):
        if f - 1 not in pc or f not in pa or f not in pb:
            continue
        A, B = pa[f], pb[f]
        side = [(B - A)[0] * (p - A)[1] - (B - A)[1] * (p - A)[0] for p in (pc[f - 1], pc[f])]
        if side[0] * side[1] < 0:
            u = float((pc[f] - A) @ (B - A) / ((B - A) @ (B - A)))
            crossed += 0.1 < u < 0.9
    assert crossed == 0


def test_stand_spot_is_in_sight_of_the_target():
    """立つ場所は、行き先の点から見通せる所だけ（受付の机の向こう側に立つ場所を取り、仲間と逆向きに歩き出した、hospital_gate_ev の種 7）。"""
    sp = load_space("hospital")
    sim = Sim(sp, 30, 30)
    target = (2.0, 3.0)
    for k in range(30):
        a = Agent(f"P{k:04d}", [], 0.0, 1.3, 0.0)
        xy = sim.alloc_stand(a, target)
        if xy != target:
            assert sp.los(target, xy, 0.0), xy


@pytest.fixture(scope="module")
def hospital_run(tmp_path_factory):
    return twinsim.simulate({**twinsim.template("hospital_gate_ev"), "seed": 12, "cameras": [], "outputs": ["ground_truth", "validity"]},
                            out_dir=tmp_path_factory.mktemp("h") / "r")


def test_group_boards_the_same_car(hospital_run):
    """グループは同じ EV のかごに乗る（定員で全員が乗れなければ、一緒に次を待つ）。"""
    gt = hospital_run.ground_truth()
    board_t = {n: e["t"] for e in gt["elevator_events"] for n in e["boarded"]}
    checked = 0
    for g in gt["groups"].values():
        ts = {board_t.get(n) for n in g["members"] if gt["people"][n]["events"].get("board")}
        if len([n for n in g["members"] if gt["people"][n]["events"].get("board")]) >= 2:
            checked += 1
            assert len(ts) == 1, g
    assert checked >= 3


def test_ground_truth_groups(hospital_run):
    """正解の groups: 仲間・関係・先導の人・分かれていた区間。仲間は EV の待つ場所でも離れない（分かれていた区間は短い）。"""
    gt = hospital_run.ground_truth()
    assert gt["groups"]
    for name, g in gt["groups"].items():
        assert g["relation"] in GROUP_RELATIONS and g["leader"] in g["members"]
        assert all(gt["people"][n]["group"] == name and gt["people"][n]["relation"] == g["relation"] for n in g["members"])
    apart = sum((b if b is not None else gt["total_frames"] / gt["fps"]) - a for g in gt["groups"].values() for a, b in g["apart"])
    together = sum(len(gt["tracks"][n]) / gt["fps"] for g in gt["groups"].values() for n in g["members"])
    assert apart / together < 0.05


def test_mates_wait_beyond_the_gate(tmp_path):
    """ゲートを先に通った人は、通った先で仲間を待つ（状態 group_wait、events の regroup）。"""
    r = twinsim.simulate({**twinsim.template("verify_gate_capacity"), "duration_s": 120, "cameras": [], "outputs": ["ground_truth"]},
                         out_dir=tmp_path / "r")
    gt = r.ground_truth()
    waits = [w for p in gt["people"].values() for w in p["events"].get("regroup", [])]
    assert waits and all(w[1] is None or w[1] - w[0] <= 30.0 + 1e-6 for w in waits)
    assert any(s == "group_wait" for p in gt["people"].values() for _a, _b, s in p["states"])


def test_validity_judges_group_formation(tmp_path):
    """判定: 2 人連れの距離は関係ごとの文献の値と、横の広がりは密度ごとに文献の式（Zanlungo ら 2015）と比べる。"""
    r = twinsim.simulate({**twinsim.template("verify_groups"), "duration_s": 150, "cameras": [], "outputs": ["ground_truth", "validity"]},
                         out_dir=tmp_path / "r")
    em = r.validity()["emergent"]
    dy, gf = em["dyad_distance"], em["group_formation"]
    assert dy["verdict"] == "合う" and dy["literature"]["relation"] == "友人"
    low = [b for b in gf["dyad"]["bins"] if b["judged"]]
    assert low and all(abs(b["diff_m"]) <= 0.1 for b in low)
    assert gf["passes_between"]["count"] == 0 and gf["passes_between"]["link_minutes"] > 1
    assert not math.isnan(gf["dyad"]["bins"][0]["mean_x_m"])


def test_a_companion_between_mates_is_not_a_stranger():
    """仲間の間を横切った回数: 待ち合わせで合流した同行者（グループの人数には数えない）は、同じグループなら知らない人に数えない。
    前は同行者を知らない人に数え、office_ev_hall の種 14 で、合流した 4 人目が仲間の 2 人の間を 1.5 秒歩いた分が 45 回になった。"""
    from types import SimpleNamespace

    from twinsim.validity import passes_between
    n = 30
    x = np.linspace(0.0, 3.0, n)
    walk = lambda y: {"xy": np.c_[x, np.broadcast_to(y, (n,))], "state": ["pass"] * n, "f0": 0}  # noqa: E731
    cross = np.c_[3.05 - x, np.full(n, 0.5)]  # 横に並んで歩く 2 人（y = 0 m・1 m）の間を、向かいから抜ける
    for group, role, want in (("G1", "companion", 0), ("G2", None, 1), (None, None, 1)):
        P = {"A": {**walk(0.0), "group": "G1", "info": {}}, "B": {**walk(1.0), "group": "G1", "info": {}},
             "C": {"xy": cross, "state": ["pass"] * n, "f0": 0, "group": group, "info": {"role": role}}}
        run = SimpleNamespace(fps=10, gt={"total_frames": n}, P=P, at=lambda m, f, P=P: f if 0 <= f < len(P[m]["xy"]) else None)
        assert passes_between(run, {"G1": ["A", "B"]})["count"] == want, (group, role)


def test_group_eval_counts_like_setti2015(hospital_run):
    """グループを見つける課題の評価: 正解そのものは F1 = 1。2 組を 1 つにまとめると、T = 2/3 でも当たらない（まちがいの人が多い）。
    3 人組の 2 人だけ（2/3）は T = 2/3 で当たり、T = 1 で外れ。"""
    from twinsim import group_eval as E
    gt = hospital_run.ground_truth()
    res = E.evaluate(gt, E.perfect(gt))
    assert res["frames"] > 0 and res["groups"]["T=0.667"]["f1"] == 1.0 and res["groups"]["T=1"]["f1"] == 1.0 and res["pairs"]["f1"] == 1.0
    assert E.match([{"a", "b"}, {"c", "d"}], [{"a", "b", "c", "d"}]) == (0, 2, 1)
    assert E.match([{"a", "b", "c"}], [{"a", "b"}], T=2 / 3) == (1, 0, 0)
    assert E.match([{"a", "b", "c"}], [{"a", "b"}], T=1.0) == (0, 1, 1)
    assert E.match([{"a", "b", "c"}], [{"a", "b", "x"}], T=2 / 3) == (1, 0, 0)  # まちがい 1 人まで
    assert E.match([{"a", "b"}], [{"a"}, {"b"}]) == (0, 1, 0)  # 1 人の組は数えない
