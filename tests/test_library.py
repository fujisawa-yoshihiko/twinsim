"""Python のライブラリとして使う入口（設定は JSON）の確かめ（CPU だけ、数秒）。"""

import gzip
import json
import shutil
import subprocess

import numpy as np
import pytest

import twinsim

CONFIG = {
    "name": "lib_test", "space": "office", "duration_s": 30, "seed": 5,
    "people": {"profile": "office_commute_jp"},
    "streams": [{"name": "commuters", "origin": "entrance", "rate": {"type": "constant", "per_min": 30, "unit": "persons"},
                 "destinations": [{"to": "south_exit", "via": ["gate"]}]}],
    "cameras": [{"name": "CamGate"}],
    "outputs": ["ground_truth", "frames", "tasks", "mot"],
}


def frames_of(result):
    return gzip.decompress((result.out_dir / "frames.csv.gz").read_bytes())  # 圧縮の見出しには時刻が入るので、中身を比べる


def test_tie_break_does_not_depend_on_the_process():
    # 真正面の人をよける向きは名前だけで決まる（hash() は実行ごとに変わり、同じ種でも結果が変わっていた）
    from twinsim.engine import tie_side
    assert [tie_side(n) for n in ("P0001", "P0002", "P0003", "P0004")] == [-1.0, -1.0, -1.0, 1.0]


def test_public_names_load():
    for name in twinsim.__all__:
        assert callable(getattr(twinsim, name))
    assert "office" in twinsim.list_spaces() and "office_gate_ev" in twinsim.list_templates()
    with pytest.raises(AttributeError):
        getattr(twinsim, "no_such_name")  # noqa: B009


def test_same_result_from_dict_string_and_file(tmp_path):
    # dict・JSON の文字列・JSON のファイルのどれでも、同じ結果になる
    a = twinsim.simulate(CONFIG, out_dir=tmp_path / "a")
    b = twinsim.simulate(json.dumps(CONFIG), out_dir=tmp_path / "b")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
    c = twinsim.simulate(path, out_dir=tmp_path / "c")
    rows = list(a.frames())
    assert a.summary["people"] > 0 and rows
    assert rows == list(b.frames()) == list(c.frames())
    assert np.array_equal(a.mot("CamGate"), c.mot("CamGate"))


def test_result_reads_outputs(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    row = next(r.frames())
    assert set(row) == {"frame", "t", "person", "x", "y", "yaw", "moving", "state", "zone", "group", "type"}
    assert isinstance(row["x"], float) and isinstance(row["frame"], int)
    labels = r.mot("CamGate")
    assert labels.shape[1] == 9 and labels[:, 0].min() >= 1  # frame, id, x, y, w, h, conf, class, visibility
    assert r.cameras == ["CamGate"]
    assert set(r.ground_truth()["people"]) and "1_count" in r.tasks()
    assert r.config["duration_s"] == 30 and "lib_test" in repr(r)
    with pytest.raises(FileNotFoundError, match="CamGate"):
        r.mot("NoSuchCamera")


def test_open_result_reads_a_finished_run(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    opened = twinsim.open_result(tmp_path / "r")
    assert opened.summary == r.summary and opened.config["duration_s"] == 30
    assert opened.cameras == ["CamGate"] and opened.videos == {}
    with pytest.raises(FileNotFoundError, match="summary.json"):
        twinsim.open_result(tmp_path / "none")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg がない")
def test_video_frames_use_simulator_frame_numbers(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    cam = r.ground_truth()["cameras"]["CamGate"]
    with pytest.raises(FileNotFoundError, match="CamGate"):
        list(r.video_frames("CamGate"))
    (r.out_dir / "video").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={cam['width']}x{cam['height']}:rate=30:duration=1",
                    "-c:v", "libx264", "-g", "10", "-pix_fmt", "yuv420p", str(r.out_dir / "video/CamGate.mp4")], check=True)
    (r.out_dir / "render_log.json").write_text(json.dumps({"frames": [100, 129]}))  # 一部だけ描いた動画
    assert r.video_first_frame == 100
    all_frames = list(r.video_frames("CamGate"))
    assert [f for f, _ in all_frames] == list(range(100, 130))
    assert all_frames[0][1].shape == (cam["height"], cam["width"], 3)
    assert [f for f, _ in r.video_frames("CamGate", step=10)] == [100, 110, 120]
    part = list(r.video_frames("CamGate", frames=(117, 119)))
    assert [f for f, _ in part] == [117, 118, 119]
    assert np.abs(part[0][1].astype(int) - all_frames[17][1].astype(int)).mean() < 1  # 途中からでも同じコマ


def test_render_needs_isaac_sim(tmp_path, monkeypatch):
    from twinsim import isaac_bridge
    monkeypatch.setattr(isaac_bridge, "ready", lambda: False)
    with pytest.raises(RuntimeError, match="isaac_up"):
        twinsim.render(tmp_path)


def test_origin_by_coordinates(tmp_path):
    xy = [-3.0, 20.0]
    config = {**CONFIG, "streams": [{**CONFIG["streams"][0], "origin": {"xy": xy}}]}
    r = twinsim.simulate(config, out_dir=tmp_path / "xy")
    gt = r.ground_truth()
    first = [t[0] for t in gt["tracks"].values()]  # 全員が置いた点の近くから歩き始める
    assert first and all(np.hypot(p[0] - xy[0], p[1] - xy[1]) < 1.0 for p in first)
    assert r.config["streams"][0]["name"] == "commuters"
    assert {p["flow"].split("->")[0] for p in gt["people"].values()} == {"commuters"}  # 出発地の名前は流れの名前
    again = twinsim.simulate(r.config, out_dir=tmp_path / "again")  # 書き出した設定でやり直せる
    assert frames_of(again) == frames_of(r)


def test_destinations_can_be_plain_names(tmp_path):
    named = {**CONFIG, "streams": [{"name": "a", "origin": "entrance", "rate": 8, "destinations": ["south_exit"]}]}
    written = {**CONFIG, "streams": [{"name": "a", "origin": "entrance", "rate": 8, "destinations": [{"to": "south_exit"}]}]}
    assert frames_of(twinsim.simulate(named, out_dir=tmp_path / "a")) == frames_of(twinsim.simulate(written, out_dir=tmp_path / "b"))


def test_origin_by_line_spreads_people_and_names_the_stream(tmp_path):
    line = [[-4.0, 20.0], [-2.0, 20.0]]
    stream = {k: v for k, v in CONFIG["streams"][0].items() if k != "name"}
    config = {**CONFIG, "streams": [{**stream, "origin": {"line": line, "name": "north_door"}}]}
    r = twinsim.simulate(config, out_dir=tmp_path / "line")
    gt = r.ground_truth()
    assert r.config["streams"][0]["name"] == "north_door"
    assert {p["flow"].split("->")[0] for p in gt["people"].values()} == {"north_door"}
    xs = [t[0][0] for t in gt["tracks"].values()]
    assert len(xs) >= 3 and max(xs) - min(xs) > 0.4


def test_meet_from_coordinates(tmp_path):
    dest = {"to": "lounge_1", "dwell": 3, "meet": {"p": 1.0, "delay": 1.0, "from": {"xy": [-3.0, 20.0], "name": "friend"}}, "then": "south_exit"}
    config = {**CONFIG, "streams": [{**CONFIG["streams"][0], "destinations": [dest]}]}
    gt = twinsim.simulate(config, out_dir=tmp_path / "meet").ground_truth()
    assert any(p["flow"].startswith("friend->") for p in gt["people"].values())


@pytest.mark.parametrize("origin, message", [
    ({"xy": [-100.0, 0.0]}, "歩ける所の外"),
    ({"xy": [1, 2, 3]}, "座標が正しくない"),
    ({"line": [[-4.0, 20.0]]}, "座標が正しくない"),
    ({"xy": [-3.0, 20.0], "line": [[-4.0, 20.0], [-2.0, 20.0]]}, "形が正しくない"),
    ({"point": [-3.0, 20.0]}, "形が正しくない"),
    ("no_such_place", "origin no_such_place がない"),
])
def test_origin_errors_before_simulating(origin, message):
    with pytest.raises(ValueError, match=message):
        twinsim.validate({**CONFIG, "streams": [{**CONFIG["streams"][0], "origin": origin}]})


def test_custom_camera_position_changes_the_labels(tmp_path):
    placed = {"name": "MyCam", "eye": [-1.0, 8.0, 3.0], "target": [-3.0, 14.0, 0.8], "focal_mm": 8.0}
    moved = {"name": "CamGate", "eye": [-1.0, 8.0, 3.0]}  # 候補の一部だけ変える
    r = twinsim.simulate({**CONFIG, "cameras": [placed, moved]}, out_dir=tmp_path / "cam")
    cams = r.ground_truth()["cameras"]
    assert r.cameras == ["CamGate", "MyCam"] and len(r.mot("MyCam")) > 0
    assert cams["MyCam"]["focal_mm"] == 8.0 and cams["MyCam"]["eye"] == placed["eye"]
    assert cams["CamGate"]["eye"] == moved["eye"]


@pytest.mark.parametrize("camera, message", [
    ({"name": "MyCam", "eye": [0, 0, 3]}, "eye・target がなく"),
    ({"name": "MyCam", "eye": [0, 0], "target": [1, 1, 1]}, r"\[x, y, z\]"),
    ({"name": "MyCam", "eye": [1, 1, 1], "target": [1, 1, 1]}, "同じ点"),
    ({"name": "CamGate", "eyes": [1, 1, 1]}, "知らないキー eyes"),
    ({"eye": [1, 1, 1], "target": [2, 2, 2]}, "name がない"),
])
def test_camera_errors_before_simulating(camera, message):
    with pytest.raises(ValueError, match=message):
        twinsim.validate({**CONFIG, "cameras": [camera]})


def test_render_tint_comes_from_the_config(tmp_path, monkeypatch):
    from twinsim import isaac_bridge
    r = twinsim.simulate({**CONFIG, "render": {"tint": False}}, out_dir=tmp_path / "r")
    seen = []
    monkeypatch.setattr(isaac_bridge, "WORK", tmp_path / "work")
    monkeypatch.setattr(isaac_bridge, "fix_perms", lambda: None)
    monkeypatch.setattr(isaac_bridge, "submit", lambda script, job, name: seen.append(job["tint"]) or "")
    monkeypatch.setattr(isaac_bridge, "finish_render", lambda *a: {"log": "", "videos": {}})
    isaac_bridge.render(r.out_dir)
    isaac_bridge.render(r.out_dir, tint=True)  # 引数が優先
    assert seen == [False, True]
    with pytest.raises(ValueError, match="render.tint"):
        twinsim.validate({**CONFIG, "render": {"tint": "blue"}})


def test_resolved_config_is_json_and_reruns_the_same(tmp_path):
    # 既定の値を足した設定を JSON にして渡し直しても、同じ結果になる（設定を残せば再現できる）
    a = twinsim.simulate(CONFIG, out_dir=tmp_path / "a")
    assert a.config == json.loads((a.out_dir / "scenario_resolved.json").read_text(encoding="utf-8"))
    b = twinsim.simulate(a.out_dir / "scenario_resolved.json", out_dir=tmp_path / "b")
    assert list(a.frames()) == list(b.frames())


def test_template_as_a_starting_point(tmp_path):
    cfg = twinsim.template("office_smoke")
    json.dumps(cfg)  # テンプレートも JSON にできる
    cfg["duration_s"] = 20
    r = twinsim.simulate(cfg, out_dir=tmp_path / "t", overrides={"seed": 2})
    assert r.summary["duration_s"] == 20 and r.summary["seed"] == 2
    with pytest.raises(FileNotFoundError, match="office_smoke"):
        twinsim.template("no_such_template")


def test_elevator_policy_from_code(tmp_path):
    # docs/library.md の例: 待つ人がいて、着く予定がなければ EV を呼ぶ
    cfg = {"space": "office", "duration_s": 90, "seed": 1, "outputs": ["ground_truth"],
           "streams": [{"name": "s", "origin": "entrance", "rate": {"type": "constant", "per_min": 30, "unit": "persons"},
                        "destinations": [{"to": "elevator", "via": ["gate"]}]}],
           "elevator": {"cars": ["EV1", "EV2"], "capacity": 8, "schedule": {"type": "times", "times": {"EV1": [], "EV2": []}}}}

    def policy(sim, t):
        if sim.queue and not any(x >= t for c in sim.cars for x in c.arrivals):
            sim.cars[0].arrivals.append(round(t + 10.0, 2))

    assert twinsim.simulate(cfg, out_dir=tmp_path / "off").summary["elevator"]["arrivals"] == 0
    called = twinsim.simulate(cfg, out_dir=tmp_path / "on", elevator_policy=policy).summary["elevator"]
    assert called["arrivals"] > 0 and called["boarded"] > 0


@pytest.mark.parametrize("bad, message", [
    ({**CONFIG, "duraton_s": 30}, "知らないキー duraton_s"),
    ({**CONFIG, "duration_s": 0}, "duration_s"),
    ({**CONFIG, "outputs": ["movie"]}, "outputs"),
    ({**CONFIG, "streams": [{**CONFIG["streams"][0], "origin": "nowhere"}]}, "origin nowhere"),
    ({k: v for k, v in CONFIG.items() if k != "space"}, "space"),
    ('{"space": "office",}', "JSON の誤り"),
])
def test_config_errors_are_reported(bad, message):
    with pytest.raises(ValueError, match=message):
        twinsim.validate(bad)


def test_missing_config_and_space():
    with pytest.raises(FileNotFoundError, match="office_gate_ev"):
        twinsim.validate("no_such_config.json")
    with pytest.raises(FileNotFoundError, match="空間"):
        twinsim.validate({**CONFIG, "space": "no_such_space"})


def test_custom_space_from_a_folder(tmp_path):
    # 自分の空間は、フォルダの場所を space に書くと使える（space.json も読める）
    import shutil

    from twinsim.space import load_space
    src = load_space("corridor").folder
    dst = tmp_path / "my_corridor"
    shutil.copytree(src, dst)
    spec = load_space(str(dst)).spec
    (dst / "space.yaml").unlink()
    (dst / "space.json").write_text(json.dumps(spec), encoding="utf-8")
    assert load_space(str(dst)).name == "my_corridor"
