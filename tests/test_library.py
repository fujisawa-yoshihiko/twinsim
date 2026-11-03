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


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg がない")
@pytest.mark.parametrize("n", [60, 300])
def test_encode_keeps_every_frame_in_order(tmp_path, n):
    from PIL import Image

    from twinsim import isaac_bridge
    frames = tmp_path / "frames"
    frames.mkdir()
    first = 1717
    for k in range(n):  # コマごとに違う画像（明るい帯の位置でコマが分かる）
        img = np.zeros((90, 160, 3), np.uint8)
        img[:, 4 + 2 * (k % 70):8 + 2 * (k % 70)] = 255
        Image.fromarray(img).save(frames / f"f.{first + k}.png")
    mp4 = tmp_path / "out.mp4"
    assert isaac_bridge.encode(frames, mp4, 30) == n
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    video = np.frombuffer(raw, np.uint8).reshape(-1, 90, 160)
    assert len(video) == n
    left = [int(np.nonzero(v[45] > 128)[0].min()) for v in video]
    assert all(abs(x - (4 + 2 * (k % 70))) <= 1 for k, x in enumerate(left))  # 同じコマが続かず、順に進む


def test_encode_refuses_missing_frames(tmp_path):
    from PIL import Image

    from twinsim import isaac_bridge
    for k in (0, 1, 3):
        Image.new("RGB", (16, 16)).save(tmp_path / f"f.{k}.png")
    with pytest.raises(RuntimeError, match="抜けている"):
        isaac_bridge.encode(tmp_path, tmp_path / "o.mp4", 30)


def test_rerun_in_the_same_place_replaces_old_outputs(tmp_path):
    two = {**CONFIG, "cameras": [{"name": "CamGate"}, {"name": "CamEV"}]}
    twinsim.simulate(two, out_dir=tmp_path)
    assert (tmp_path / "mot/CamEV.txt").exists()
    r = twinsim.simulate({**CONFIG, "cameras": [{"name": "CamGate"}], "seed": 9}, out_dir=tmp_path)
    assert r.cameras == ["CamGate"] and not (tmp_path / "mot/CamEV.txt").exists()
    none = twinsim.simulate({**CONFIG, "cameras": []}, out_dir=tmp_path)  # カメラをなくしても落ちない
    assert none.cameras == []


def test_rerun_keeps_files_in_a_folder_that_is_not_a_result(tmp_path):
    (tmp_path / "mot").mkdir()
    (tmp_path / "mot/mine.txt").write_text("keep")
    twinsim.simulate(CONFIG, out_dir=tmp_path)
    assert (tmp_path / "mot/mine.txt").read_text() == "keep"


def test_custom_space_folder_works_for_check(tmp_path):
    import shutil as sh

    from twinsim.quality import check
    from twinsim.space import find_space
    folder = tmp_path / "myroom"
    sh.copytree(find_space("office"), folder)
    r = twinsim.simulate({**CONFIG, "space": str(folder)}, out_dir=tmp_path / "r")
    assert check(r.out_dir) is not None


def test_written_distribution_is_used_as_written(tmp_path):
    r = twinsim.simulate({**CONFIG, "people": {"speed": {"type": "normal", "mean": 0.6, "sd": 0.01}}}, out_dir=tmp_path)
    assert "min" not in r.config["people"]["speed"]  # 既定の min 0.8・max 1.9 を混ぜない
    assert abs(np.mean([p["speed_m_s"] for p in r.ground_truth()["people"].values()]) - 0.6) < 0.05


def test_labels_follow_the_floor_height(tmp_path):
    from twinsim.camera import RADIUS_M, Camera
    r = twinsim.simulate("simple_room_smoke", out_dir=tmp_path)
    gt, labels = r.ground_truth(), r.mot("CamRoom")
    cam = Camera(gt["cameras"]["CamRoom"])
    z = -0.77  # この空間の床
    assert len(labels)
    names = {v: k for k, v in json.loads((r.out_dir / "mot/ids.json").read_text()).items()}
    for f, pid, x, y, _, h, *_ in labels[::20]:
        name = names[int(pid)]
        px, py, _ = gt["tracks"][name][int(f) - 1 - gt["people"][name]["start_frame"]]
        height = gt["people"][name]["height_m"]
        uv, _ = cam.project([(px + a, py + b, c) for a in (-RADIUS_M, RADIUS_M) for b in (-RADIUS_M, RADIUS_M) for c in (z, z + height)])
        assert abs(uv[:, 0].min() - x) < 0.1 and abs(uv[:, 1].min() - y) < 0.1 and abs(uv[:, 1].max() - (y + h)) < 0.1


@pytest.mark.parametrize("change, message", [
    ({"elevator": {"cars": ["EV1"], "schedule": {"type": "interval", "interval": 0}}}, "正の値"),
    ({"elevator": {"cars": ["EV1"], "schedule": {"type": "interval", "interval": {"type": "uniform", "min": 0, "max": 0}}}}, "正の値"),
])
def test_endless_schedule_is_an_error(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        twinsim.simulate({**CONFIG, **change}, out_dir=tmp_path)


def test_zero_lambda_group_size_finishes(tmp_path):
    stream = {**CONFIG["streams"][0], "group_size": {"type": "zero_truncated_poisson", "lam": 0}}
    assert twinsim.simulate({**CONFIG, "streams": [stream]}, out_dir=tmp_path).summary["groups"] == 0


def test_group_size_of_zero_means_one_person(tmp_path):
    stream = {**CONFIG["streams"][0], "group_size": {"type": "poisson", "lam": 1.5}}
    assert twinsim.simulate({**CONFIG, "streams": [stream]}, out_dir=tmp_path).summary["people"] > 0


def test_numpy_values_and_paths_are_accepted(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path, overrides={"duration_s": np.float64(10), "seed": np.int64(3)})
    assert r.config["duration_s"] == 10.0 and type(r.config["duration_s"]) is float and type(r.config["seed"]) is int


def test_empty_labels_keep_their_columns(tmp_path):
    r = twinsim.simulate({**CONFIG, "streams": []}, out_dir=tmp_path)
    assert r.mot("CamGate").shape == (0, 9)


def test_elevator_policy_replaces_the_schedule(tmp_path):
    ev = {"cars": ["EV1"], "schedule": {"type": "times", "times": {"EV1": [3, 6, 9]}}}
    r = twinsim.simulate({**CONFIG, "elevator": ev}, out_dir=tmp_path, elevator_policy=lambda sim, t: None)
    assert r.ground_truth()["elevator_times"] == []


def test_people_getting_off_at_the_very_end_are_not_in_the_events(tmp_path):
    ev = {"cars": ["EV1"], "schedule": {"type": "times", "times": {"EV1": [29.9]}},
          "alight": {"count": 4, "destinations": ["south_exit"]}}
    gt = twinsim.simulate({**CONFIG, "elevator": ev}, out_dir=tmp_path).ground_truth()
    assert all(n in gt["people"] for e in gt["elevator_events"] for n in e["alighted"])


def test_camera_above_a_wall_still_sees_people(tmp_path):
    camera = {"name": "OnWall", "eye": [6.5, 2.5, 2.8], "target": [-4.0, 7.0, 0.5]}
    stream = {"origin": {"xy": [-2.0, 6.0]}, "rate": 30, "destinations": ["south_exit"]}
    labels = twinsim.simulate({**CONFIG, "cameras": [camera], "streams": [stream]}, out_dir=tmp_path).mot("OnWall")
    assert (labels[:, 8] >= 0.4).sum() > 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg がない")
def test_video_frames_before_the_rendered_part_keep_their_numbers(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    cam = r.ground_truth()["cameras"]["CamGate"]
    (r.out_dir / "video").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={cam['width']}x{cam['height']}:rate=30:duration=1",
                    "-pix_fmt", "yuv420p", str(r.out_dir / "video/CamGate.mp4")], check=True)
    (r.out_dir / "render_log.json").write_text(json.dumps({"frames": [100, 129]}))
    assert [f for f, _ in r.video_frames("CamGate", frames=(50, 104))] == [100, 101, 102, 103, 104]


@pytest.mark.parametrize("change, message", [
    ({"fps": 29.97}, "fps は正の整数"),
    ({"seed": None}, "seed は整数"),
    ({"variant": "C", "variants": {"A": {}}}, "variant C"),
    ({"gates": {"gatee": {"service_s": 2}}}, "gatee"),
    ({"outputs": ["aicity"]}, "aicity"),
    ({"mot_stride": 0}, "mot_stride"),
    ({"graph": {"cell_m": 0.75}}, "cell_m"),
    ({"render": {"props": ["nope"]}}, "render.props"),
    ({"cameras": "CamGate"}, "cameras は"),
    ({"streams": [{"origin": "entrance", "destinations": ["south_exit"]}]}, "rate がない"),
    ({"streams": [{"origin": "entrance", "rate": 5}]}, "destinations がない"),
    ({"streams": [{"origin": "entrance", "rate": {"type": "piecewies", "per_min": [[0, 5]]}, "destinations": ["south_exit"]}]}, "piecewies"),
    ({"streams": [{"origin": "entrance", "rate": 5, "destinations": [{"to": "south_exit", "via": ["lounge_1"]}]}]}, "ゲート lounge_1"),
    ({"streams": [{"origin": "entrance", "rate": 5, "destinations": ["elevator"]}]}, "elevator の設定が要る"),
    ({"streams": [{"origin": "entrance", "rate": 5, "destinations": [{"to": "lounge_1", "then": {"to": "lounge_2", "meet": {"delay": 3}}}]}]}, "meet は一番上"),
    ({"elevator": {"cars": ["EV1"], "schedule": {"type": "on-demand"}}}, "on-demand"),
    ({"elevator": {"cars": ["lounge_1"]}}, "扉 lounge_1"),
    ({"elevator": {}, "streams": [{"origin": "entrance", "rate": 5, "destinations": ["south_exit"]}]}, None),
])
def test_more_mistakes_are_found_before_simulating(change, message):
    if message is None:
        twinsim.validate({**CONFIG, **change})
        return
    with pytest.raises(ValueError, match=message):
        twinsim.validate({**CONFIG, **change})


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
    placed = {"name": "MyCam", "eye": [-1.0, 8.0, 2.8], "target": [-3.0, 14.0, 0.8], "focal_mm": 8.0}
    moved = {"name": "CamGate", "eye": [-1.0, 8.0, 2.8]}  # 候補の一部だけ変える
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
    ({"name": "Roof", "eye": [-1.0, 8.0, 3.5], "target": [-3.0, 14.5, 0.8]}, "天井（3.0 m）以上"),  # 天井の上から撮ることになる
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
    monkeypatch.setattr(isaac_bridge, "enqueue", lambda script, job, name: seen.append(job["tint"]))
    monkeypatch.setattr(isaac_bridge, "wait_render", lambda plan: None)
    monkeypatch.setattr(isaac_bridge, "finish_plan", lambda *a: {"log": "", "videos": {}})
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
