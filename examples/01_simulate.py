"""最初の一歩: JSON の設定で人の動きを計算し、結果を読む。

映像（動画）は出力しない。
    この例は人の動きを計算し、正解ラベルなどのファイルを書くだけで、mp4 はできない。
    動画は計算の結果を Isaac Sim で描画して作る。この例を実行したあとに 04_get_video.py を実行する（GPU を使う）。

処理の流れ:
    1. 同じフォルダの minimal.json を読み、誤りがないかを計算の前に確かめる（twinsim.validate）。
    2. 人の動きを計算し、結果を runs/tutorial/ に書き出す（twinsim.simulate）。
    3. 人数、書き出したファイル、枠があるカメラを画面に表示する。

設定（minimal.json）:
    オフィスの空間（office）で 60 秒。毎分 20 人が入口からゲートを通って南の出口へ歩く。カメラは CamGate と CamEV の 2 台。
    値を変える方法は 02_change_settings.py、設定の項目は docs/library.md と docs/spec.md を参照。

書き出すファイル（runs/tutorial/ の下。形の説明は docs/formats.md）:
    summary.json             要約（人数、同時に最大の人数、書き出したファイルの一覧など）
    ground_truth.json        正解（人ごとの軌跡・状態・出来事、カメラ、ゲートと EV の記録）
    frames.csv.gz            1 コマ 1 人 1 行の位置・向き・状態
    mot/<カメラ>.txt         検出と追跡の正解ラベル（カメラごとの人の枠。MOTChallenge の形）
    mot/ids.json             ラベルの数の ID と、人の名前（P0001 など）の対応
    tasks.json               場所ごとの人数・通過・滞留などの集計
    validity.json・.md・.png 歩く速さや密度などを文献の値と比べた結果
    scenario_resolved.*      既定の値を足した設定（JSON と YAML）。同じ計算をやり直すときに使う

実行（リポジトリの最上段のフォルダで）:
    uv run python examples/01_simulate.py

    GPU は使わず、数秒で終わる。同じ場所に書くので、実行し直すと結果は上書きする。
    04 で作った動画があれば、新しい結果と合わなくなるので runs/tutorial/before_<日時>/ に移す（消さない）。

03 からあとの例はこの結果を読むので、最初に実行する。
"""

from pathlib import Path

import twinsim

config = Path(__file__).with_name("minimal.json")
twinsim.validate(config)  # 誤りがあれば、計算の前に ValueError

result = twinsim.simulate(config, out_dir="runs/tutorial")
print(result)
print("人数:", result.summary["people"], "／ 同時に最大:", result.summary["max_present"])
print("書き出したファイル:", ", ".join(result.files))
print("枠があるカメラ:", ", ".join(result.cameras))
