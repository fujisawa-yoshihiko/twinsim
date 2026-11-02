"""Python のライブラリとして使う入口（設定は JSON）の確かめ（CPU だけ、数秒）。"""

import json

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
    return (result.out_dir / "frames.csv.gz").read_bytes()


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
