"""空間を多角形・dict から作る（1.2 の 4）の確かめ（CPU だけ、数秒）。"""

import json
import random
import shutil

import numpy as np
import pytest
import yaml

import twinsim
from twinsim.space import _shape_mask, load_space, point_in_poly, rasterize


def room(holes=(), name="poly_room", **walk):
    """20 m × 8 m の部屋（西に入口、東に出口）。"""
    return {
        "name": name,
        "levels": [{"name": "1F", "z": 0.0, "walkable": {"res": 0.25, "outline": [[0, 0], [20, 0], [20, 8], [0, 8]], "holes": list(holes), **walk}}],
        "pois": {"west": {"kind": "spawn", "xy": [0.5, 4.0], "line": [[0.5, 2.0], [0.5, 6.0]]},
                 "east": {"kind": "exit", "xy": [19.5, 4.0]}},
        "zones": {"all": {"polygon": [[0, 0], [20, 0], [20, 8], [0, 8]]}},
        "cameras": {"CamRoom": {"eye": [1.0, 1.0, 2.7], "target": [10.0, 4.0, 0.8]}},
    }


def config(space, **kw):
    return {"name": "poly_test", "space": space, "duration_s": 30, "seed": 2,
            "streams": [{"name": "s", "origin": "west", "rate": {"type": "constant", "per_min": 30, "unit": "persons"},
                         "destinations": [{"to": "east"}]}],
            "cameras": [{"name": "CamRoom"}], "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"], **kw}


def test_grid_from_polygons_counts_cells_by_area():
    # res の倍数で書いた長方形は、マスの数 × res² がそのまま面積。穴（長方形・円）の分だけ減り、まわりの 1 列は歩けない
    g, x0, y0, res = rasterize({"res": 0.25, "outline": [[0, 0], [10, 0], [10, 4], [0, 4]],
                                "holes": [{"rect": [4, 1, 5, 2]}, {"circle": [8, 2, 0.3]}]})
    assert (x0, y0, res) == (-0.125, -0.125, 0.25)
    assert g.sum() == 10 * 4 * 16 - 16 - 4  # 円（半径 0.3）は中心のまわりの 4 マス
    assert not (g[0].any() or g[-1].any() or g[:, 0].any() or g[:, -1].any())
    # 外形は重ねてよく、合わせた所が歩ける（L 字）
    g2, *_ = rasterize({"outline": [{"rect": [0, 0, 10, 2]}, {"rect": [0, 0, 2, 8]}]})
    assert g2.sum() * 0.25 ** 2 == 10 * 2 + 2 * 6


def test_polygon_cells_follow_point_in_poly():
    # 斜めの辺の多角形も、マスの中心を point_in_poly（ゾーンと同じ数え方）で決める
    rng = random.Random(3)
    poly = [(rng.uniform(-5, 5), rng.uniform(-5, 5)) for _ in range(7)]
    X, Y = np.arange(-6, 6, 0.25) + 0.125, np.arange(-6, 6, 0.25) + 0.125
    m = _shape_mask("polygon", poly, X, Y)
    assert all(m[i, j] == point_in_poly(poly, X[j], Y[i]) for i in range(len(Y)) for j in range(len(X)))


@pytest.mark.parametrize("walk, msg", [
    ({"res": 0.25, "outline": [[0, 0], [10, 0], [10, 4], [0, 4]], "holes": [{"rect": [4.9, 0, 5.1, 4]}]}, "1 つも含まない"),  # res より薄い壁
    ({"res": 0.0, "outline": [[0, 0], [10, 0], [10, 4]]}, "res"),
    ({"outline": [[0, 0], [10, 0]]}, "3 点以上"),
    ({"outline": [{"rect": [5, 0, 1, 4]}]}, "x0 < x1"),
    ({"outline": [{"circle": [0, 0, -1]}]}, "半径は正"),
    ({"outline": [{"rect": [0, 0, 1, 1], "polygon": [[0, 0], [1, 0], [1, 1]]}]}, "1 つ"),
    ({"outline": [[0, 0], [10, 0], [10, 4]], "hole": []}, "知らないキー hole"),
    ({"holes": []}, "outline"),
    ({"res": 0.05, "outline": [{"rect": [0, 0, 200, 200]}]}, "大きすぎる"),
    ({"outline": [{"rect": [0, 0, 4, 4]}], "holes": [{"rect": [-1, -1, 5, 5]}]}, "歩けるマスがない"),
])
def test_bad_polygons_are_errors(walk, msg):
    with pytest.raises(ValueError, match=msg):
        rasterize(walk)


def test_space_written_in_the_config_runs(tmp_path):
    # 設定の space に空間そのもの（dict）を書くと、その空間で計算する。結果の設定に空間が残り、あとから読み直せる
    space = room(holes=[{"circle": [10.0, 4.0, 0.5]}])
    r = twinsim.simulate(config(space), out_dir=tmp_path / "run")
    gt = r.ground_truth()
    assert gt["space"] == "poly_room" and r.summary["people"] >= 10
    assert json.loads((r.out_dir / "scenario_resolved.json").read_text())["space"] == space
    sp = load_space(r.config["space"])
    pts = np.concatenate([np.array(t)[:, :2] for t in gt["tracks"].values()])
    assert all(sp.walkable(x, y) for x, y in pts[::7])
    assert all(np.hypot(x - 10.0, y - 4.0) > 0.5 for x, y in pts)  # 柱の中は歩かない
    assert r.mot("CamRoom").shape[0] > 0
    # 結果を読む道具（妥当性の group_formation など）も、設定に書いた空間を使う
    from twinsim.validity import Run, group_formation
    group_formation(Run(r.out_dir), {})
    # USD がないので描画はできない（分かる誤りにする。前は KeyError: 'usd'）
    from twinsim.isaac_bridge import plan_render
    with pytest.raises(ValueError, match="USD がない"):
        plan_render(r.out_dir)


def test_space_from_python_and_from_a_file(tmp_path):
    # Python で組み立てた空間を確かめてから渡せる（twinsim.load_space）。YAML のファイルの場所でもよい（中のファイルはそのフォルダから）
    sp = twinsim.load_space(room())
    assert sp.name == "poly_room" and sp.walkable(10.0, 4.0) and not sp.walkable(21.0, 4.0)
    assert twinsim.load_space(sp) is sp
    folder = tmp_path / "spaces"
    folder.mkdir()
    shutil.copy(load_space("corridor").folder / "walkable_1f.txt", folder / "grid.txt")
    spec = {**load_space("corridor").spec, "levels": [{"name": "1F", "z": 0.0, "walkable": "grid.txt"}]}
    spec.pop("name")
    (folder / "my_corridor.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    mine = load_space(str(folder / "my_corridor.yaml"))
    assert mine.name == "my_corridor" and np.array_equal(mine.grid, load_space("corridor").grid)
    r = twinsim.simulate({**config(str(folder / "my_corridor.yaml")), "cameras": [],
                          "streams": [{"name": "s", "origin": "west", "rate": {"type": "constant", "per_min": 30, "unit": "persons"},
                                       "destinations": [{"to": "east"}]}]}, out_dir=tmp_path / "run")
    assert r.summary["people"] >= 10


def test_errors_in_a_space_dict_reach_validate():
    with pytest.raises(ValueError, match="1 つも含まない"):
        twinsim.validate(config(room(holes=[{"rect": [9.9, 0.0, 10.1, 8.0]}])))
    with pytest.raises(ValueError, match="levels"):
        twinsim.validate(config({"name": "x", "pois": {}}))
    with pytest.raises(ValueError, match="name"):
        twinsim.validate(config(room(name="a b")))
    with pytest.raises(ValueError, match="歩ける所の外"):  # 入口が穴の中
        twinsim.validate(config(room(holes=[{"rect": [0.0, 0.0, 2.0, 8.0]}])))


def test_show_space_draws_a_plan_without_a_top_image(tmp_path):
    # 真上の図のない空間（dict・合成の廊下）は、歩ける所の格子から平面図を描く
    from PIL import Image

    from twinsim.spaceview import draw
    out = draw(room(holes=[{"circle": [10.0, 4.0, 0.5]}]), out=tmp_path / "room.png")
    img = np.asarray(Image.open(out).convert("L"))
    assert img.shape[1] > img.shape[0] > 200
    assert draw("corridor_door", out=tmp_path / "cd.png").exists()
