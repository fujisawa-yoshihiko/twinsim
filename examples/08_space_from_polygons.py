"""自分の空間を多角形で書いて計算する（CPU だけ、数秒）。

空間（歩ける所・場所・ゾーン・カメラ）を Python の dict で組み立て、設定の space にそのまま渡す。
歩ける所は、格子のファイルの代わりに多角形で書く:
    walkable: {"res": 0.25,                 格子の刻み（m）
               "outline": [形, ...],         外形（重なってよく、合わせた所が歩ける）
               "holes": [形, ...]}           穴（柱・壁・机など、歩けない所）
    形は点の一覧 [[x, y], ...] か {"rect": [x0, y0, x1, y1]}・{"circle": [x, y, 半径]}。
res より細い形（0.25 m 刻みなら 0.25 m より薄い壁）は格子から消えてしまうので、誤りになる。

同じ中身を YAML か JSON のファイルに書いて、space にそのファイルの場所を書いてもよい（docs/spec.md の 1）。
描画（Isaac Sim）には USD が要るので、この空間では動画は作れない。正解ラベル（mot）と集計は作れる。

実行（リポジトリの最上段のフォルダで）:
    uv run python examples/08_space_from_polygons.py

結果は runs/tutorial_polygon/ に書く。空間の図は runs/tutorial_polygon_space.png（明るい所が歩ける所）。
"""

from pathlib import Path

import twinsim

# 30 m × 14 m の広間。北に幅 3 m の廊下（建物の入口）、東は間仕切りの壁（幅 2 m の出入口）の奥の部屋
pillars = [{"circle": [x, y, 0.4]} for x in (6.0, 12.0) for y in (4.0, 10.0)]  # 柱 4 本（Python なら繰り返しで作れる）
space = {
    "name": "tutorial_hall",
    "levels": [{
        "name": "1F",
        "z": 0.0,
        "walkable": {
            "res": 0.25,
            "outline": [{"rect": [0.0, 0.0, 30.0, 14.0]}, {"rect": [12.0, 14.0, 15.0, 20.0]}],
            "holes": pillars + [
                {"rect": [19.75, 0.0, 20.25, 6.0]},    # 間仕切りの壁（厚さ 0.5 m）。y = 6〜8 が出入口
                {"rect": [19.75, 8.0, 20.25, 14.0]},
                {"rect": [15.0, 10.5, 18.0, 11.5], "note": "受付の机"},
            ],
        },
    }],
    "pois": {
        "entrance":    {"kind": "spawn", "xy": [13.5, 19.5], "line": [[12.5, 19.5], [14.5, 19.5]]},
        "west_door":   {"kind": "spawn", "xy": [0.5, 7.0], "line": [[0.5, 6.0], [0.5, 8.0]]},
        "east_exit":   {"kind": "exit", "xy": [29.5, 7.0]},
        "reception_1": {"kind": "spot", "xy": [15.8, 9.8], "face": [15.8, 11.0]},
        "reception_2": {"kind": "spot", "xy": [17.2, 9.8], "face": [17.2, 11.0]},
    },
    "zones": {
        "corridor":  {"polygon": [[12.0, 14.0], [15.0, 14.0], [15.0, 20.0], [12.0, 20.0]]},
        "hall":      {"polygon": [[0.0, 0.0], [20.0, 0.0], [20.0, 14.0], [0.0, 14.0]]},
        "east_room": {"polygon": [[20.0, 0.0], [30.0, 0.0], [30.0, 14.0], [20.0, 14.0]]},
    },
    "cameras": {"CamHall": {"eye": [1.0, 1.0, 2.7], "target": [12.0, 8.0, 0.8]}},
}

# 空間だけを読んで確かめる（歩ける所の面積、図）
sp = twinsim.load_space(space)
print(f"空間 {sp.name}: 格子 {sp.nx} × {sp.ny}（{sp.res} m）、歩ける所 {sp.grid.sum() * sp.res ** 2:.1f} m²")
Path("runs").mkdir(exist_ok=True)
from twinsim.spaceview import draw  # noqa: E402

print("空間の図:", draw(space, out="runs/tutorial_polygon_space.png"))

config = {
    "name": "tutorial_polygon",
    "space": space,
    "duration_s": 120,
    "seed": 1,
    "streams": [
        {"name": "from_north", "origin": "entrance", "rate": {"type": "constant", "per_min": 20, "unit": "persons"},
         "destinations": [{"to": "east_exit", "p": 0.7},
                          {"to": "reception", "p": 0.3, "dwell": {"type": "uniform", "min": 10, "max": 30}, "then": "west_door"}]},
        {"name": "from_west", "origin": "west_door", "rate": {"type": "constant", "per_min": 10, "unit": "persons"},
         "destinations": [{"to": "entrance"}]},
    ],
    "cameras": [{"name": "CamHall"}],
    "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"],
}
result = twinsim.simulate(config, out_dir="runs/tutorial_polygon")
print(f"{result.summary['people']} 人、同時に最大 {result.summary['max_present']} 人")
labels = result.mot("CamHall")
print(f"CamHall: 枠 {len(labels)} 個")

# 細すぎる壁は、計算の前に分かる
thin = {**space, "levels": [{**space["levels"][0], "walkable": {**space["levels"][0]["walkable"], "holes": [{"rect": [19.9, 0.0, 20.1, 6.0]}]}}]}
try:
    twinsim.validate({**config, "space": thin})
except ValueError as e:
    print("誤りの例:", e)
