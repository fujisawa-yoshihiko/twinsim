# twinsim — 建物・工場の人流のデジタルツインのシミュレータ

[English](README.en.md)

このブランチ `with-mopf` は、検出・追跡の MOPF との連携と人物照合を含む版。シミュレータだけの版は `main`。

研究計画（竹芝 VLM × QUBO、10/4 版）とデジタルツインの構想を確かめるための 3D のシミュレータ。
空間（USD）・人の分布・カメラ・イベント（EV・ゲート）をシナリオのファイルで決め、人の動きを CPU で計算し、
正解・集計・GNN 向けのグラフ・カメラの枠を書き出す。映像が要るときは Isaac Sim で描く。仕様は [docs/spec.md](docs/spec.md)。

**進捗の報告（画面・動画つき）**: [docs/report/2026-10-24](docs/report/2026-10-24/README.md)　**検知と 2 地点の紐付けの仕組み（図つき）**: [docs/methods.md](docs/methods.md)

## 起動

```bash
cd ~/twinsim
./run.sh serve                 # GUI（127.0.0.1:8770）。別の端末で ./run.sh serve --url を実行すると、開く URL が出る
./run.sh templates             # テンプレートの一覧
./run.sh run office_gate_ev    # 計算（CPU、5 分・約 100 人で 20 秒ほど）
./run.sh check ~/dt-data/twinsim/runs/office_gate_ev   # 確かめ（文献との比べ validity.md・png も書く）
./isaac_up.sh                  # 描画するときだけ: Isaac Sim を起動（MOPF と同じ GPU 1 枚に載せる。止めるのは isim down）
./run.sh render ~/dt-data/twinsim/runs/office_gate_ev --frames 7395 7544   # 試し撮り
./run.sh mopf-process ~/dt-data/twinsim/runs/office_gate_ev   # 動画を MOPF で検出・追跡（MOPF を起動してから。GPU）
./run.sh mopf-eval ~/dt-data/twinsim/runs/office_gate_ev      # MOPF の追跡を正解と比べる・中間層のグラフ
./run.sh calibrate office_gate_ev --gate-log gate_log.csv --ev-log ev_log.csv   # 実データで合わせる
./run.sh mopf-sync ~/dt-data/twinsim/runs/office_gate_ev      # 2 台を時刻でそろえた動画と、同じ人の各カメラの ID の対応表
./run.sh mopf-link ~/dt-data/twinsim/runs/office_gate_ev      # 正解を使わずに 2 台の間の対応を推論して採点（予測の動画も。人物照合の重みは tools/fetch_reid_weights.sh）
```

手元の PC のブラウザで GUI を開くには、手元の PC で `ssh -N -L 8770:localhost:8770 ampb` を実行したまま、`./run.sh serve --url` の URL を開く
（MOPF の画面も見るなら `ssh -N -L 8770:localhost:8770 -L 5174:localhost:5174 ampb`）。起動状況は `./status.sh`（GUI のサーバー・MOPF・Isaac Sim・GPU）。
画面は「設定」（シナリオ・人の分布・カメラ）、「結果」（要約・確認の図・文献との比べ・動画・MOPF との比べ・ダウンロード）、「MOPF」（起動・ライブ・停止）の 3 つのタブ。
右上で表示を日本語・English に切り替えられる（ブラウザに覚える）。結果の図・動画の中の文字と validity.md は日本語のまま。
構成と開発の手順は [docs/architecture.md](docs/architecture.md)。

結果は `~/dt-data/twinsim/runs/<名前>/`（`preview.png` で軌跡を確かめられる）。描画は docs/spec.md の「描画」。

## 出力の形（学習データ・正解ラベル）

ほかの目的（検出・追跡・複数カメラの追跡・人物照合・人流の予測・GNN・VLM）で使う人向けの要約。詳しくは [docs/formats.md](docs/formats.md)。
置き場所は `~/dt-data/twinsim/runs/<結果の名前>/`。座標は世界の m（Z が上）、シミュレータのコマは 0 始まり（秒 = コマ ÷ 30）。

| ファイル | 形 | 中身 |
|---|---|---|
| `ground_truth.json` | JSON | 人ごとの軌跡 `tracks[名前] = [[x, y, yaw], …]`・歩いているか・状態の区間・出来事（ゲート・EV）・属性（人物モデル・背の高さ・種類・グループ）、カメラ（4×4 の行列と画角）、ゾーン |
| `frames.csv.gz` | CSV | 1 コマ 1 人 1 行: `frame, t, person, x, y, yaw, moving, state, zone, group, type` |
| `mot/<カメラ>.txt`・`mot/ids.json` | MOTChallenge | `frame, id, x, y, w, h, 1, 1, visibility`（コマは 1 始まり、id はカメラをまたいで同じ） |
| `aicity/gt.txt` | AI City の MTMC | `camera_id obj_id frame_id xmin ymin width height xworld yworld` |
| `video/<カメラ>.mp4` | H.264 | 描いた映像（1280×720・30 fps）。k コマ目 = `render_log.json` の `frames[0]` ＋ k |
| `tasks.json` | JSON | 計画書 p7 の 6 タスクの正解（人数・ゲートの通過・滞留・グループ・混雑・行き先、EV の待ち） |
| `graph/` | JSON・CSV・NPZ・GraphML | ゾーンのグラフ・2 m の格子のグラフ、秒ごとの人数・1 分ごとの流れ、カメラから見える所 |
| `logs/` | CSV | ゲートの通過記録・EV の運行記録（実データと同じ形） |
| `~/dt-data/twinsim/ward/<空間>_ward_layout.json` | JSON | 病棟のベッド・ナースステーションの置き方と、その間の歩ける所の上の道のりと道の点の列（`./run.sh ward-layout`。MedGym ワークベンチの病棟の実施の遅れが使う） |

状態: `pass`・`gate_queue`・`ev_approach`・`ev_wait`・`alight`・`reception`・`dwell`・`sign_check`・`companion_wait`（倉庫は `work`・`wait`）。
注意: 枠は人を囲む箱を映した近似（輪郭にぴったりではない）、見えている割合も近似。人物モデルは 10 種類で、服の色を人ごとに変えている。

## 止め方

手順書（起動・停止・確認・困ったとき）は [docs/operations.md](docs/operations.md)。

GPU は他の利用者と共有なので、使い終わったら止める。止めたあと `nvidia-smi` で空いたかを確かめる（`./stop.sh` は最後に表示する）。

| 止めるもの | 方法 | 補足 |
|---|---|---|
| GUI のサーバー（ポート 8770） | 起動した端末で `Ctrl+C`、または `./stop.sh gui` | CPU だけ。`setsid` などで裏で起動したときは `./stop.sh gui` |
| MOPF（Isaac Sim と同じ GPU 1 枚に載る） | GUI の「MOPF」のタブの「止める」、または `./stop.sh mopf`（= `~/MOPF_ALL_video/stop_ampb.sh`） | データとイメージは残る |
| Isaac Sim（描画、MOPF と同じ GPU 1 枚に載る） | `./stop.sh isaac`（= `isim down`） | 描画の途中なら描画も止まる。次に描くときは `./isaac_up.sh` |
| 夜間の描画と比べる処理（`tools/night_b.sh`） | `pgrep -af night_b` で番号を見て `kill <番号>` | 描画（Isaac Sim の中）はそのまま続くので、止めるなら `./stop.sh isaac` も。描画が済んでいれば `tools/night_b.sh --resume` で続きから |
| まとめて | `./stop.sh`（GUI と MOPF）、`./stop.sh all`（Isaac Sim も） | 止める前後の状態は `./status.sh` |

## 映像を作るのにかかる時間（2026-10-23 の実測、GPU は RTX PRO 6000 1 枚）

| 段 | office_gate_ev（5 分・94 人・カメラ 2 台、1280×720） | 映像の長さに対して |
|---|---|---|
| 人の動きの計算（CPU） | 約 15 秒 | 0.05 倍 |
| 描画（Isaac Sim、RAY_TRACE） | 1 台 42 分、2 台で 89 分（読み込み 1 分を含む。カメラは 1 台ずつ順に描く） | 1 台あたり約 8.5 倍 |
| mp4 にする | 2 台で約 3 分 | |
| MOPF で検出・追跡（yolo11m・BoostTrack） | 1 台 約 3 分 | 0.6 倍 |
| 比べる・重ねた動画・並べた動画（CPU） | 数秒・1 台 2〜3 分・3〜4 分 | |

- 空間で描画の速さが違う（試し撮りの値）: オフィス 1 秒に 3.5〜5.7 コマ、倉庫 1.9 コマ（約 16 倍）、病院 1.1 コマ（約 27 倍。照明が多い）。
- 速くする方法: 解像度を下げる、コマ数を 15 にする（MOPF の追跡への影響は要確認）。急ぐときだけ、カメラごとに別の GPU で同時に描く（2 枚なら半分。既定は全部を GPU 1 枚に載せる形で、分けるのは 2 枚まで）。

## 構成

| 場所 | 中身 |
|---|---|
| `twinsim/space.py` | 空間（歩ける所の格子・意味の地図・経路 A*） |
| `twinsim/engine.py` | 人の動き（段取り・よけ合い・ゲートの列・複数台の EV）。hospital-sim の flow_scene2_lib を広げたもの |
| `twinsim/scenario.py`・`dists.py` | シナリオと分布 → 人の発生・行き先・EV・ゲート |
| `twinsim/literature.py`・`validity.py` | 文献に基づく人の分布（出典つき、`people.profile`・`demand`）と、計算のあとの文献との比べ（[docs/validity.md](docs/validity.md)） |
| `twinsim/calibrate.py` | 実データ（ゲートの通過記録・EV の運行記録）で値を合わせる。シミュレータの結果を記録の形に書き出す（`export-logs`） |
| `twinsim/mopf/` | MOPF との連携（[docs/integration.md](docs/integration.md)）: `monitor`（人流モニターの設定）・`process`（動画の検出・追跡）・`evaluate`（正解との比べ）・`graph`（中間層のグラフ）・`crossings`（線の数え方）・`overlay`（重ねた動画）・`identity`（2 台を時刻でそろえる）・`linking`（2 台の間の対応の推論）・`control`（起動・停止）・`synthetic`（確かめ用）・`io` |
| `twinsim/config.py` | 置き場所と接続先（`TWINSIM_DATA`・`TWINSIM_MOPF_HOME`・`TWINSIM_MOPF_URL`・`TWINSIM_ISAAC_WORK` などの環境変数で変えられる） |
| `twinsim/outputs.py`・`camera.py`・`quality.py` | 正解・集計・グラフ・枠・確かめ |
| `twinsim/api.py`・`__main__.py` | Python の API とコマンド |
| `twinsim/isaac_bridge.py`・`isaac/` | Isaac Sim での描画と、USD から空間を作る部品（`isaac/vendor/` は hospital-sim から写した人物の部品） |
| `spaces/` | 空間（office・hospital・warehouse・simple_room・warehouse_small・corridor（確かめ用の廊下）） |
| `templates/` | テンプレート（下の表） |
| `tests/` | 動作確認（`uv run --group dev pytest -q`、書き方の確かめは `uv run --group dev ruff check`） |
| `pyproject.toml`・`uv.lock` | 依存（`./run.sh` は `uv run twinsim`。初回に `.venv` を作る） |

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

## 欲しい機能（Notion の「シミュレータ」）との対応（2026-10-22 夜）

| 欲しい機能 | 状態 |
|---|---|
| PDF の内容を確かめられる 3D のシミュレータ | 人の動き・正解・集計・描画まで通った（オフィス・病院・倉庫で試し撮り済み） |
| 空間を選べる（オフィス・病院・倉庫・小部屋） | オフィス・病院・倉庫は使える。小部屋は計算だけ（描画は真っ暗）。小さい倉庫は材料だけ |
| オープンな USD・自分でアップロード | `export-space`（URL か場所の USD から材料とひな形）＋`show-space`（意味の地図を描く図）。画面からのアップロードは未 |
| 人の分布を制御 | 済（到着の率・まとまり・種類・行き先・速さ・止まる時間）。文献の値の組（`people.profile`）と建物の人数からの EV の利用者（`demand`）、計算ごとの文献との比べと根拠の台帳（`validity.md`）。文献のない値は「仮」と明示 |
| カメラ・発生・移動・イベントの制御（GUI・文書） | 済: シナリオのファイル・文書・GUI（真上の図でカメラをドラッグ、値を変えて計算・描画） |
| テンプレート | 7 つ（上の表） |
| API（MOPF・GNN） | 済: REST API・Python の API・グラフの書き出し・MOPF の人流モニターの設定の自動作成と数えるはずの値。動画を MOPF で検出・追跡して正解と比べる（`mopf-process`・`mopf-eval`）、MOPF の追跡から同じ形の中間層のグラフ、研究のコードから読める、AI City の形。実データで合わせる（`calibrate`）。MOPF を GPU で動かしての確かめは未 |

GUI: `./run.sh serve`（URL は `./run.sh serve --url`）。画面の確かめは `uv run --group gui-test python tools/gui_shot.py`。
