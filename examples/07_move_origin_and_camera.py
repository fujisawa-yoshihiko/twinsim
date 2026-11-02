"""人の現れる場所とカメラの位置を変える（CPU だけ、数秒）。

変えられるもの:
    人の現れる場所  streams[].origin に、場所の名前の代わりに座標を書く。
                    {"xy": [x, y]}                     その点から現れる
                    {"line": [[x0, y0], [x1, y1]]}     線の上のどこかから現れる（幅のある入口）
                    {"xy": [x, y], "name": "north"}    name は集計での呼び名（書かなければ流れの名前）
    カメラ          cameras[] の eye（位置）・target（見る点）・focal_mm（焦点距離）を書く。
                    空間の候補の名前なら、書いた値だけを上書きする。
                    新しい名前なら、eye と target が必須。

座標は世界の座標（m、Z が上）。座標の調べ方は 2 つある。
    - GUI の図の上にマウスを置くと、図の下に x・y が出る
    - twinsim show-space office で、目盛りつきの図（空間のフォルダの annotate.png）を作る

歩ける所の外の座標や、行き先まで歩いて行けない座標は、計算の前に ValueError になる。
GUI なら、図の緑の四角（現れる場所）と赤い印（カメラ）をドラッグして動かせる。

実行（リポジトリの最上段のフォルダで）:
    uv run python examples/07_move_origin_and_camera.py

結果は runs/tutorial_moved/ に書く。動画が要るときは、この結果を twinsim.render に渡す（04_get_video.py と同じ）。
"""

import json
from pathlib import Path

import numpy as np

import twinsim

config = json.loads(Path(__file__).with_name("minimal.json").read_text(encoding="utf-8"))

# 人の現れる場所: 北の廊下の幅 2 m の線にする
line = [[-4.0, 20.0], [-2.0, 20.0]]
config["streams"][0]["origin"] = {"line": line, "name": "north_door"}

# カメラ: 候補の CamGate は位置だけ変え、新しいカメラ MyCam を足す
config["cameras"] = [
    {"name": "CamGate", "eye": [-1.0, 8.0, 3.0]},
    {"name": "MyCam", "eye": [-6.0, 6.0, 2.7], "target": [-3.0, 14.5, 0.8], "focal_mm": 10.0},
]

result = twinsim.simulate(config, out_dir="runs/tutorial_moved")
gt = result.ground_truth()

starts = np.array([track[0][:2] for track in gt["tracks"].values()])
print(f"{len(starts)} 人が現れた。x {starts[:, 0].min():.2f}〜{starts[:, 0].max():.2f}、y {starts[:, 1].min():.2f}〜{starts[:, 1].max():.2f}")
print("出発地の呼び名:", sorted({p["flow"].split("->")[0] for p in gt["people"].values()}))

for camera in result.cameras:
    labels = result.mot(camera)
    print(f"{camera}: 位置 {gt['cameras'][camera]['eye']}、よく見えている枠 {(labels[:, 8] >= 0.4).sum()} 個")

# 歩ける所の外は、計算の前に分かる
try:
    twinsim.validate({**config, "streams": [{**config["streams"][0], "origin": {"xy": [-100.0, 0.0]}}]})
except ValueError as e:
    print("誤りの例:", e)
