# チュートリアルの例

[English](README.en.md)

`twinsim` をコードから使う例。上から順に実行すると、計算から動画の取得、学習データの書き出しまでがひと通り動く。リポジトリの最上段のフォルダで実行する。

```bash
uv run python examples/01_simulate.py      # 計算（結果は runs/tutorial/。git には入らない）
uv run python examples/03_read_labels.py   # 正解ラベルを読む

./isaac_up.sh                              # 動画を作るときだけ（GPU）
uv run python examples/04_get_video.py     # 動画を取得する
isim down                                  # 終わったら GPU を返す

uv run python examples/05_frames_with_boxes.py
uv run python examples/06_detection_dataset.py
```

| 例 | できること | GPU | 時間の目安 |
|---|---|---|---|
| [minimal.json](minimal.json) | いちばん小さい設定（オフィス、60 秒、カメラ 2 台） | | |
| [01_simulate.py](01_simulate.py) | JSON の設定で計算して、結果を読む | なし | 数秒 |
| [02_change_settings.py](02_change_settings.py) | テンプレートから設定を作る、`overrides` で値を変えて何度も回す、誤りを計算の前に確かめる | なし | 10 秒ほど |
| [03_read_labels.py](03_read_labels.py) | 検出と追跡の正解ラベル、人ごとの位置と状態、場所ごとの集計を読む | なし | 数秒 |
| [04_get_video.py](04_get_video.py) | Isaac Sim で描画して mp4 を取得する。人がいちばん多い区間だけ、カメラを絞る、服の色を変えない、などを選べる | 1 枚 | 2 秒・2 台で 1〜2 分 |
| [05_frames_with_boxes.py](05_frames_with_boxes.py) | 動画のコマを取り出し、正解の枠を重ねて画像にする | なし | 数秒 |
| [06_detection_dataset.py](06_detection_dataset.py) | 動画と正解ラベルから、物体検出の学習データ（YOLO の形）を作る | なし | 数秒 |
| [07_move_origin_and_camera.py](07_move_origin_and_camera.py) | 人の現れる場所を座標で変える、カメラを動かす・足す | なし | 数秒 |

## コマの番号

3 つの番号の関係に気をつける。

| 番号 | 始まり | 関係 |
|---|---|---|
| シミュレータのコマ | 0 | 秒 = コマ ÷ fps（既定 30） |
| 正解ラベル（`result.mot`）の `frame` | 1 | シミュレータのコマ ＋ 1 |
| 動画の何コマ目か | 0 | シミュレータのコマ − `result.video_first_frame` |

`result.video_frames(camera)` はシミュレータのコマを返すので、ラベルとは `frame + 1` で突き合わせる（05・06 を参照）。

## 動画を描くときの注意

- GPU は共用なので、使う前に `nvidia-smi` で空きを確かめ、終わったら `isim down` で止める。
- 全部の長さを描くと、1 台あたり映像の長さの約 8.5 倍かかる（`--all`）。まず短い区間で確かめる。
- 04 の既定は、人が見分けやすいように服の色を人ごとに変える。評価に使う動画は `--plain` で描く。
- 動画の置き場所は `runs/tutorial/video/<カメラ>.mp4`。動画は git に入れない。

関数の一覧は [docs/library.md](../docs/library.md)、ファイルの形は [docs/formats.md](../docs/formats.md)。JSON の設定は[チュートリアル](../docs/config-tutorial.md)と[リファレンス](../docs/config-reference.md)。
