"""行動の目的になる部品（1.2、twinsim/components.py）の確かめ（CPU だけ、1 分ほど）: 窓口の列・呼び出し・座る場所・部屋、グループ。"""

import csv
import gzip
import json
import math
import shutil

import numpy as np
import pytest

import twinsim
from twinsim.space import ROOT, load_space

SPACE = """
name: corridor_parts
title: 廊下に窓口・席・部屋を置いた試し
license: 自作（制限なし）
levels:
  - {name: 1F, z: 0.0, walkable: walkable_1f.txt}
pois:
  west:    {kind: spawn, xy: [0.5, 0.0], line: [[0.5, -1.6], [0.5, 1.6]]}
  east:    {kind: exit, xy: [49.5, 0.0], line: [[49.5, -1.6], [49.5, 1.6]]}
  counter: {kind: service, points: [[15.0, 1.45]], faces: [[15.0, 2.5]], line: [[15.0, 0.2], [24.0, 0.2]]}
  desk:    {kind: service, points: [[20.0, 1.45], [22.0, 1.45]], faces: [[20.0, 2.5], [22.0, 2.5]], wait: benches}
  benches: {kind: seats, row: {from: [26.0, -1.7], to: [32.0, -1.7], n: 10, yaw: 90}}
  room_1:  {kind: room, xy: [35.0, 1.5], inside: [35.0, 2.8]}
  sofa:    {kind: seats, furniture: [{asset: bench3, xy: [40.0, -1.6], rot: 180}]}
zones:
  all: {polygon: [[0.0, -2.0], [50.0, -2.0], [50.0, 2.0], [0.0, 2.0]]}
"""


@pytest.fixture(scope="module")
def space_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("sp") / "corridor_parts"
    d.mkdir()
    shutil.copy(ROOT / "spaces" / "corridor" / "walkable_1f.txt", d / "walkable_1f.txt")
    (d / "space.yaml").write_text(SPACE, encoding="utf-8")
    return d


def cfg(space_dir, dest, rate=4.0, duration=150, group=None, **extra):
    c = {"name": "parts", "space": str(space_dir), "seed": 3, "duration_s": duration,
         "streams": [{"name": "flow", "origin": "west", "rate": {"type": "constant", "per_min": rate}, "destinations": [dest]}],
         "outputs": ["ground_truth", "frames", "mot"], "cameras": [{"name": "c1", "eye": [25.0, -1.8, 2.7], "target": [25.0, 1.0, 0.0]}]}
    if group:
        c["people"] = {"group_size": group}
    c.update(extra)
    return c


def test_seats_are_furniture(space_dir):
    """席は歩ける所から外れ（経路が席の列を通らない）、席の前の点は歩ける。"""
    sp = load_space(str(space_dir))
    for x in np.linspace(26.0, 32.0, 10):
        assert not sp.walkable(x, -1.7) and sp.walkable(x, -1.1)


def test_line_queue_is_first_come_first_served(space_dir, tmp_path):
    """列の窓口: 着いた順に応対を受け、1 つの応対の場所で同時に 2 人が応対を受けない。状態 service_queue・service。"""
    r = twinsim.simulate(cfg(space_dir, {"to": "counter", "then": "east"}, rate=6.0,
                             services={"counter": {"service_s": {"type": "uniform", "min": 12, "max": 16}}}), out_dir=tmp_path / "r")
    gt = r.ground_truth()
    sv = sorted((p["events"]["service"][0] for p in gt["people"].values() if p["events"].get("service")), key=lambda e: e["join"])
    started = [e for e in sv if e.get("start") is not None]
    assert len(started) >= 6
    assert [e["start"] for e in started] == sorted(e["start"] for e in started)  # 着いた順
    for e0, e1 in zip(started, started[1:]):
        assert e1["start"] >= e0["end"] - 1e-6  # 前の人が済んでから
    states = {s for p in gt["people"].values() for _a, _b, s in p["states"]}
    assert {"service_queue", "service"} <= states


def test_called_waiting_sits_and_room_hides_people(space_dir, tmp_path):
    """呼び出しの窓口: 席に座って待ち（pose sit、状態 call_wait）、空いた順に呼ばれる。部屋: 定員 1 で 1 組ずつ入り、中の人は frames.csv・MOT に
    出ない（tracks には同じ番号で続く）。"""
    dest = {"to": "desk", "then": {"to": "room_1", "then": "east"}}
    r = twinsim.simulate(cfg(space_dir, dest, rate=4.0, duration=200,
                             services={"desk": {"service_s": {"type": "uniform", "min": 20, "max": 30}, "call": True}},
                             rooms={"room": {"stay_s": {"type": "uniform", "min": 15, "max": 20}}}), out_dir=tmp_path / "r")
    gt = r.ground_truth()
    ppl = gt["people"]
    assert any(s == "call_wait" for p in ppl.values() for _a, _b, s in p["states"])
    assert any(p.get("sit") for p in ppl.values())
    with gzip.open(r.out_dir / "frames.csv.gz", "rt") as f:
        rows = list(csv.DictReader(f))
    assert any(x["pose"] == "sit" and x["state"] == "call_wait" for x in rows)
    assert not any(x["state"] == "in_room" for x in rows)
    rooms = sorted((e["enter"], e["exit"]) for p in ppl.values() for e in p["events"].get("room", []) if e.get("enter") is not None)
    assert len(rooms) >= 3
    for (_e0, x0), (e1, _x1) in zip(rooms, rooms[1:]):
        assert e1 >= x0 - 1.0  # 定員 1: 前の人が出てから入る（扉の行き来の秒は見る）
    inside = [n for n, p in ppl.items() if any(s == "in_room" for _a, _b, s in p["states"])]
    for n in inside:
        p = ppl[n]
        assert len(gt["tracks"][n]) == p["arrive_frame"] - p["start_frame"] + 1  # 部屋の中もコマは続く
    mot = (r.out_dir / "mot" / "c1.txt").read_text().splitlines()
    ids = json.loads((r.out_dir / "mot" / "ids.json").read_text())
    in_room_frames = {(ids[n] if isinstance(ids, dict) and n in ids else None, f) for n in inside for a, b, s in ppl[n]["states"] if s == "in_room"
                      for f in range(a, b + 1)}
    for line in mot:
        f, i = (int(float(v)) for v in line.split(",")[:2])
        assert (i, f - 1) not in in_room_frames and (i, f) not in in_room_frames
    xy = np.array([q for n in ppl for q in gt["tracks"][n]])[:, :2]
    assert np.isfinite(xy).all()


def test_group_leader_is_served_and_party_enters_together(space_dir, tmp_path):
    """グループ: 窓口では先導の人だけが応対を受け、仲間は近くで待つ（companion_wait）。部屋には一緒に入って一緒に出る。"""
    dest = {"to": "counter", "then": {"to": "room_1", "then": "east"}}
    r = twinsim.simulate(cfg(space_dir, dest, rate=1.5, duration=240, group={"type": "constant", "value": 2},
                             services={"counter": {"service_s": {"type": "uniform", "min": 8, "max": 10}}},
                             rooms={"room": {"stay_s": {"type": "uniform", "min": 10, "max": 12}}}), out_dir=tmp_path / "r")
    gt = r.ground_truth()
    checked = 0
    for g in gt["groups"].values():
        lead, mate = g["leader"], [n for n in g["members"] if n != g["leader"]][0]
        pl, pm = gt["people"][lead], gt["people"][mate]
        if not pl["events"].get("room") or pl["events"]["room"][0].get("exit") is None:
            continue
        assert pl["events"].get("service") and not pm["events"].get("service")
        assert any(s == "companion_wait" for _a, _b, s in pm["states"])
        rl, rm = pl["events"]["room"][0], pm["events"]["room"][0]
        assert abs(rl["exit"] - rm["exit"]) < 1e-6 and abs(rl["enter"] - rm["enter"]) < 5.0
        checked += 1
    assert checked >= 2


def test_component_config_errors(space_dir):
    """設定の確かめ: 窓口でない場所・知らないキー・待つ場所でない名前・名前の頭で種類の違う場所が混ざる行き先は誤り。"""
    base = cfg(space_dir, {"to": "counter"})
    for extra, word in (({"services": {"room_1": {}}}, "service の場所でない"), ({"services": {"counter": {"seconds": 3}}}, "知らないキー"),
                        ({"rooms": {"room": {"wait": "east"}}}, "席（seats）の場所かゾーン")):
        with pytest.raises(ValueError, match=word):
            twinsim.validate({**base, **extra})
    sp = load_space("hospital")
    assert {p["kind"] for k, p in sp.pois.items() if k.startswith("reception_")} == {"spot"}  # 1.1 の受付の spot と、1.2 の窓口の名前は重ならない


def test_hospital_outpatient_runs(tmp_path):
    """病院の外来のテンプレート（5 分）: 受付・診察室・会計の段取りを通り、跳び（1 コマ 0.2 m より大きい一歩）がない。"""
    r = twinsim.simulate({**twinsim.template("hospital_outpatient"), "duration_s": 300, "cameras": [], "outputs": ["ground_truth"]},
                         out_dir=tmp_path / "h")
    gt = r.ground_truth()
    ev = [p["events"] for p in gt["people"].values()]
    assert any(e.get("service") and e["service"][0].get("start") is not None for e in ev)
    assert any(e.get("room") and e["room"][0].get("enter") is not None for e in ev)
    for n in gt["people"]:
        xy = np.array(gt["tracks"][n])[:, :2]
        if len(xy) > 1:
            assert float(np.hypot(*np.diff(xy, axis=0).T).max()) <= 0.2, n
    assert math.isfinite(gt["total_frames"])


def test_sit_motion_follows_the_clip(space_dir, tmp_path):
    """座る・立つ動作: 素材（SitAndStandChair）のコマ数どおりに動き、座ったコマで席の点・席の向きに着く。跳びがない。
    正解の sit は [座り始め, 座った, 立ち始め, 立ち終わり]、frames.csv の pose に sit_down・sit・stand_up
    （描画は素材の体の前後の動きを外し、この軌跡で動かす）。"""
    from twinsim.components import SIT_CLIP
    from twinsim.scenario import seats_of
    dest = {"to": "desk", "then": "east"}
    r = twinsim.simulate(cfg(space_dir, dest, rate=4.0, duration=240,
                             services={"desk": {"service_s": {"type": "uniform", "min": 8, "max": 10}, "call": True}}), out_dir=tmp_path / "r")
    gt = r.ground_truth()
    fps = gt["fps"]
    seats = seats_of(load_space(str(space_dir)).pois["benches"])
    n_down = round((SIT_CLIP["down"][1] - SIT_CLIP["down"][0]) / SIT_CLIP["fps"] * fps)
    n_up = round((SIT_CLIP["up"][1] - SIT_CLIP["up"][0]) / SIT_CLIP["fps"] * fps)
    assert gt["sit_clip"]["down"] == SIT_CLIP["down"]
    stood = 0
    for n, p in gt["people"].items():
        tr = np.array(gt["tracks"][n])
        if len(tr) > 1:
            assert float(np.hypot(*np.diff(tr[:, :2], axis=0).T).max()) < 0.1, n
        for d0, s0, s1, u1 in p.get("sit", []):
            assert s0 - d0 == n_down
            x, y, yaw = tr[s0 - p["start_frame"]]
            (sx, sy), syaw = min(seats, key=lambda q: math.hypot(q[0][0] - x, q[0][1] - y))
            assert math.hypot(sx - x, sy - y) < 0.02 and abs((yaw - syaw + 180) % 360 - 180) < 5.0
            if u1 < p["arrive_frame"]:
                assert u1 - s1 == n_up
                stood += 1
    assert stood >= 2
    with gzip.open(r.out_dir / "frames.csv.gz", "rt") as f:
        poses = {x["pose"] for x in csv.DictReader(f)}
    assert {"sit_down", "sit", "stand_up", "walk"} <= poses


def test_furniture_seats(space_dir):
    """家具の席（space.FURNITURE の bench3）: 家具の真ん中と回転から 3 席（正面の向き）。USD にない家具は床の上の大きさの分を歩ける所から外す。"""
    from twinsim.scenario import seats_of
    sp = load_space(str(space_dir))
    seats = seats_of(sp.pois["sofa"])
    assert len(seats) == 3
    for (_x, y), yaw in seats:
        assert y == pytest.approx(-1.6) and yaw == pytest.approx(90.0)  # rot 180: 正面（回す前の -y）が +y
    assert sorted(round(x, 3) for (x, _), _ in seats) == [39.215, 40.0, 40.785]
    assert not sp.walkable(40.0, -1.6) and not sp.walkable(38.9, -1.3) and sp.walkable(40.0, -0.9)


def test_door_open_spans():
    """扉を開ける区間: 中の点に着く 2.0 秒前〜0.3 秒後、中の点に現れてから 3.0 秒後まで。閉じ切る前にまた開けるなら、つなぐ。"""
    from twinsim.isaac_bridge import component_props, door_keys
    gt = {"fps": 30, "total_frames": 3000, "people": {
        "P1": {"events": {"room": [{"name": "r", "enter": 10.0, "exit": 20.0}]}},
        "P2": {"events": {"room": [{"name": "r", "enter": 21.5, "exit": 200.0}, {"name": "other", "enter": 50.0}]}}}}
    assert door_keys(gt, "r", gt["total_frames"]) == [[240, 309], [585, 690]]  # P2 が入る区間と P1 が出る区間がつながる
    hosp = load_space("hospital")
    props = component_props(hosp, {**gt, "people": {}})
    assert sum(p["kind"] == "furniture" for p in props) == 5  # ロビーの壁ぎわ 2 つ・診察室の前 3 つ（ロビーの島の長椅子は USD にある）
    assert {p["prim"] for p in props if p["kind"] == "door"} == {"/Root/SM_Door_01b9", "/Root/SM_Door_01b7", "/Root/SM_Door_01b8",
                                                                  "/Root/SM_Door_01b5_8", "/Root/SM_Door_01b6"}
