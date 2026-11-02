# twinsim — 建物・工場の人流のシミュレータ

[English](README.en.md)

空間・人の分布・カメラ・イベント（EV・ゲート）を **JSON の設定**で決めて、人の動きを CPU で計算し、**物体検知・追跡の正解ラベル**・状態の正解・集計・グラフを書き出す。
Python のライブラリとして呼べる。映像が要るときは Isaac Sim で描く。

このブランチ `simulator-lib` は、シミュレータだけを切り出したもの（検出・追跡の MOPF との連携と人物照合は入っていない。全部入りは `main`）。

## 入れ方

```bash
pip install "git+https://github.com/fujisawa-yoshihiko/twinsim.git@simulator-lib"   # 非公開のリポジトリなので、読む権限が要る
```

Python 3.10 以上。依存は numpy・scipy・pyyaml・pillow・networkx・matplotlib だけ。GPU は要らない（描画するときだけ Isaac Sim と GPU）。
空間とテンプレートはパッケージに入っている。

## Python から使う

```python
import twinsim

config = {
    "name": "minimal", "space": "office", "duration_s": 60, "seed": 1,
    "people": {"profile": "office_commute_jp"},
    "streams": [{"name": "commuters", "origin": "entrance",
                 "rate": {"type": "constant", "per_min": 20, "unit": "persons"},
                 "destinations": [{"to": "south_exit", "via": ["gate"]}]}],
    "cameras": [{"name": "CamGate"}, {"name": "CamEV"}],
    "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"],
}

result = twinsim.simulate(config, out_dir="runs/minimal")   # dict・JSON の文字列・JSON のファイル・テンプレートの名前のどれでも
print(result.summary["people"])
labels = result.mot("CamGate")     # 物体検知の正解ラベル [frame, id, x, y, w, h, conf, class, visibility]
for row in result.frames():        # 1 コマ 1 人の行（位置・向き・状態）
    ...
```

関数・`Result`・設定の書き方は **[docs/library.md](docs/library.md)**、設定の全部の項目は [docs/spec.md](docs/spec.md)。例は [examples/](examples/)。

## コマンド

```bash
twinsim templates                        # テンプレートの一覧
twinsim template office_gate_ev --out config.json   # テンプレートを JSON で書き出す（設定のひな形）
twinsim validate config.json             # 設定の確かめ（計算しない）
twinsim run config.json --out runs/test  # 計算（CPU、5 分・約 100 人で 20 秒ほど）
twinsim check runs/test                  # 確かめ（壁の中・人の近さと、文献との比べ validity.md・png）
twinsim calibrate config.json --gate-log gate_log.csv --ev-log ev_log.csv   # 実データで合わせる
```

このリポジトリの中では `./run.sh <コマンド>`（結果の既定の置き場所は `~/dt-data/twinsim/runs/`）。

## 画面

`./run.sh serve` で GUI（127.0.0.1:8770）。開く URL は `./run.sh serve --url`。手元の PC からは `ssh -N -L 8770:localhost:8770 ampb` を実行したまま開く。
画面は「設定」（シナリオ・人の分布・カメラ）と「結果」（要約・確認の図・文献との比べ・動画・ダウンロード）の 2 つのタブ。右上で日本語・English を切り替えられる。

## 描画（GPU）

```bash
./isaac_up.sh 2                                    # Isaac Sim を GPU 2 で起動（止めるのは isim down）
./run.sh render runs/test --frames 7395 7544       # 試し撮り（コードからは twinsim.render）
```

| 段 | office_gate_ev（5 分・94 人・カメラ 2 台、1280×720） | 映像の長さに対して |
|---|---|---|
| 人の動きの計算（CPU） | 約 15 秒 | 0.05 倍 |
| 描画（Isaac Sim、RAY_TRACE） | 1 台 42 分、2 台で 89 分（読み込み 1 分を含む） | 1 台あたり約 8.5 倍 |
| mp4 にする | 2 台で約 3 分 | |

空間で描画の速さが違う（1 秒に オフィス 3.5〜5.7 コマ、倉庫 1.9 コマ、病院 1.1 コマ）。止め方は `./stop.sh`・[docs/operations.md](docs/operations.md)。

## 出力の形（学習データ・正解ラベル）

物体検知・追跡の正解ラベルと、人流の予測・GNN・VLM などの学習データ。詳しくは [docs/formats.md](docs/formats.md)。
座標は世界の m（Z が上）、シミュレータのコマは 0 始まり（秒 = コマ ÷ 30）。

| ファイル | 形 | 中身 |
|---|---|---|
| `scenario_resolved.json` | JSON | 既定の値を足した設定。そのまま渡すと同じ計算になる |
| `ground_truth.json` | JSON | 人ごとの軌跡 `tracks[名前] = [[x, y, yaw], …]`・歩いているか・状態の区間・出来事（ゲート・EV）・属性（人物モデル・背の高さ・種類・グループ）、カメラ（4×4 の行列と画角）、ゾーン |
| `frames.csv.gz` | CSV | 1 コマ 1 人 1 行: `frame, t, person, x, y, yaw, moving, state, zone, group, type` |
| `mot/<カメラ>.txt`・`mot/ids.json` | MOTChallenge | `frame, id, x, y, w, h, 1, 1, visibility`（コマは 1 始まり、id はカメラをまたいで同じ） |
| `aicity/gt.txt` | AI City の MTMC | `camera_id obj_id frame_id xmin ymin width height xworld yworld` |
| `video/<カメラ>.mp4` | H.264 | 描いた映像（1280×720・30 fps）。k コマ目 = `render_log.json` の `frames[0]` ＋ k |
| `tasks.json` | JSON | 計画書 p7 の 6 タスクの正解（人数・ゲートの通過・滞留・グループ・混雑・行き先、EV の待ち） |
| `graph/` | JSON・CSV・NPZ・GraphML | ゾーンのグラフ・2 m の格子のグラフ、秒ごとの人数・1 分ごとの流れ、カメラから見える所 |
| `logs/` | CSV | ゲートの通過記録・EV の運行記録（実データと同じ形） |
| `<TWINSIM_DATA>/ward/<空間>_ward_layout.json` | JSON | 病棟のベッド・ナースステーションの置き方と、その間の歩ける所の上の道のりと道の点の列（`twinsim ward-layout`） |

状態: `pass`・`gate_queue`・`ev_approach`・`ev_wait`・`alight`・`reception`・`dwell`・`sign_check`・`companion_wait`（倉庫は `work`・`wait`）。
注意: 枠は人を囲む箱を映した近似（輪郭にぴったりではない）、見えている割合も近似。人物モデルは 10 種類で、服の色を人ごとに変えている。

## 人の動きの根拠

歩く速さ・速さと密度・ついていく歩き・グループ・EV の利用量・ゲートの処理時間は文献の値で作り、計算のたびに文献と比べる（`validity.md`）。
値の出典、確かめの結果、仮の値は [docs/validity.md](docs/validity.md)。

## 構成

| 場所 | 中身 |
|---|---|
| `twinsim/api.py`・`__init__.py` | Python の入口（`simulate`・`Result` など） |
| `twinsim/__main__.py` | コマンド |
| `twinsim/scenario.py`・`dists.py` | 設定と分布 → 人の発生・行き先・EV・ゲート |
| `twinsim/space.py` | 空間（歩ける所の格子・意味の地図・経路 A*・道のり） |
| `twinsim/engine.py` | 人の動き（段取り・よけ合い・ゲートの列・複数台の EV） |
| `twinsim/literature.py`・`validity.py` | 文献に基づく人の分布（出典つき）と、計算のあとの文献との比べ |
| `twinsim/calibrate.py` | 実データ（ゲートの通過記録・EV の運行記録）で値を合わせる |
| `twinsim/outputs.py`・`camera.py`・`quality.py` | 正解・集計・グラフ・枠・確かめ |
| `twinsim/server.py`・`static/` | GUI と REST API |
| `twinsim/isaac_bridge.py`・`isaac/` | Isaac Sim での描画と、USD から空間を作る部品 |
| `twinsim/spaces/` | 空間（office・hospital・warehouse・simple_room・warehouse_small・corridor・corridor_door） |
| `twinsim/templates/` | テンプレート（下の表） |
| `twinsim/config.py` | 置き場所（`TWINSIM_DATA`・`TWINSIM_SPACES`・`TWINSIM_ISAAC_WORK` などの環境変数で変えられる） |
| `examples/` | 設定の JSON と、Python から呼ぶ例 |
| `tests/` | 動作確認（`uv run --group dev pytest -q`、書き方の確かめは `uv run --group dev ruff check`） |

| テンプレート | 確かめること |
|---|---|
| `office_smoke` | 動作確認（30 秒） |
| `office_gate_ev` | ゲート → EV（UC1・UC2、研究 2 の 2 地点の流れ）。朝のいちばん混む 5 分（在館 600 人、人の分布は文献の値）、カメラ 2 台 |
| `office_ev_hall` | EV 前の紛らわしい状態（研究 1 の RQ1）。EV 待ち・同行者待ち・案内確認・受付 |
| `office_signage_ab` | サイネージの比較（UC3）。同じ到着で、見る人の割合を A・B で変える（効果を測る方法の確かめ。効果そのものは確かめられない） |
| `hospital_gate_ev` | 病院のロビー → 西の広間の EV（hospital-sim の sim-gate と同じ配置・カメラ。前の評価のデータと比べられる） |
| `warehouse_picking` | 倉庫のピッキング（工場の図の「作業・待ち・移動」）。荷受け → 棚 → 梱包 → 待ち → 棚 → 梱包 → 帰る |
| `simple_room_smoke` | 動作確認（小部屋、20 秒） |
| `verify_corridor_speed`・`verify_fundamental_diagram`・`verify_groups`・`verify_gate_capacity`・`verify_counterflow`・`verify_bottleneck` | エンジンの確かめ（まっすぐ歩けるか・速さと密度・グループ・混んだゲート・すれ違い・幅 1 m の出入口）。結果は docs/validity.md の 5 |
