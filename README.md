# twinsim — 建物・工場の人流のデジタルツインのシミュレータ

研究計画（竹芝 VLM × QUBO、10/4 版）とデジタルツインの構想を確かめるための 3D のシミュレータ。
空間（USD）・人の分布・カメラ・イベント（EV・ゲート）をシナリオのファイルで決め、人の動きを CPU で計算し、
正解・集計・GNN 向けのグラフ・カメラの枠を書き出す。映像が要るときは Isaac Sim で描く。仕様は [docs/spec.md](docs/spec.md)。

## 起動

```bash
cd ~/twinsim
./run.sh serve                 # GUI（127.0.0.1:8770）。別の端末で ./run.sh serve --url を実行すると、開く URL が出る
./run.sh templates             # テンプレートの一覧
./run.sh run office_gate_ev    # 計算（CPU、5 分・約 100 人で 20 秒ほど）
./run.sh check ~/dt-data/twinsim/runs/office_gate_ev   # 確かめ（文献との比べ validity.md・png も書く）
./isaac_up.sh 2                # 描画するときだけ: Isaac Sim を GPU 2 で起動（止めるのは isim down）
./run.sh render ~/dt-data/twinsim/runs/office_gate_ev --frames 7395 7544   # 試し撮り
```

手元の PC のブラウザで GUI を開くには、手元の PC で `ssh -N -L 8770:localhost:8770 ampb` を実行したまま、`./run.sh serve --url` の URL を開く。

結果は `~/dt-data/twinsim/runs/<名前>/`（`preview.png` で軌跡を確かめられる）。描画は docs/spec.md の「描画」。

## 構成

| 場所 | 中身 |
|---|---|
| `twinsim/space.py` | 空間（歩ける所の格子・意味の地図・経路 A*） |
| `twinsim/engine.py` | 人の動き（段取り・よけ合い・ゲートの列・複数台の EV）。hospital-sim の flow_scene2_lib を広げたもの |
| `twinsim/scenario.py`・`dists.py` | シナリオと分布 → 人の発生・行き先・EV・ゲート |
| `twinsim/literature.py`・`validity.py` | 文献に基づく人の分布（出典つき、`people.profile`・`demand`）と、計算のあとの文献との比べ（[docs/validity.md](docs/validity.md)） |
| `twinsim/outputs.py`・`camera.py`・`quality.py` | 正解・集計・グラフ・枠・確かめ |
| `twinsim/api.py`・`__main__.py` | Python の API とコマンド |
| `twinsim/isaac_bridge.py`・`isaac/` | Isaac Sim での描画と、USD から空間を作る部品（`isaac/vendor/` は hospital-sim から写した人物の部品） |
| `spaces/` | 空間（office・hospital・warehouse・simple_room・warehouse_small・corridor（確かめ用の廊下）） |
| `templates/` | テンプレート（下の表） |
| `tests/` | 動作確認（`$U --with pytest pytest -q tests`） |

| テンプレート | 確かめること |
|---|---|
| `office_smoke` | 動作確認（30 秒） |
| `office_gate_ev` | ゲート → EV（UC1・UC2、研究 2 の 2 地点の流れ）。朝のいちばん混む 5 分（在館 600 人、人の分布は文献の値）、カメラ 2 台 |
| `office_ev_hall` | EV 前の紛らわしい状態（研究 1 の RQ1）。EV 待ち・同行者待ち・案内確認・受付 |
| `office_signage_ab` | サイネージの比較（UC3）。同じ到着で、見る人の割合を A・B で変える（効果を測る方法の確かめ。効果そのものは確かめられない） |
| `hospital_gate_ev` | 病院のロビー → 西の広間の EV（hospital-sim の sim-gate と同じ配置・カメラ。前の評価のデータと比べられる） |
| `warehouse_picking` | 倉庫のピッキング（工場の図の「作業・待ち・移動」）。荷受け → 棚 → 梱包 → 待ち → 棚 → 梱包 → 帰る |
| `simple_room_smoke` | 動作確認（小部屋、20 秒） |
| `verify_corridor_speed`・`verify_fundamental_diagram`・`verify_groups`・`verify_gate_capacity` | エンジンの確かめ（まっすぐ歩けるか・速さと密度・グループ・混んだゲート）。結果は docs/validity.md の 5 |

## 欲しい機能（Notion の「シミュレータ」）との対応（2026-10-22 夜）

| 欲しい機能 | 状態 |
|---|---|
| PDF の内容を確かめられる 3D のシミュレータ | 人の動き・正解・集計・描画まで通った（オフィス・病院・倉庫で試し撮り済み） |
| 空間を選べる（オフィス・病院・倉庫・小部屋） | オフィス・病院・倉庫は使える。小部屋は計算だけ（描画は真っ暗）。小さい倉庫は材料だけ |
| オープンな USD・自分でアップロード | `export-space`（URL か場所の USD から材料とひな形）＋`show-space`（意味の地図を描く図）。画面からのアップロードは未 |
| 人の分布を制御 | 済（到着の率・まとまり・種類・行き先・速さ・止まる時間）。文献の値の組（`people.profile`）と建物の人数からの EV の利用者（`demand`）、計算ごとの文献との比べと根拠の台帳（`validity.md`）。文献のない値は「仮」と明示 |
| カメラ・発生・移動・イベントの制御（GUI・文書） | 済: シナリオのファイル・文書・GUI（真上の図でカメラをドラッグ、値を変えて計算・描画） |
| テンプレート | 7 つ（上の表） |
| API（MOPF・GNN） | 済: REST API・Python の API・グラフの書き出し・MOPF の人流モニターの設定の自動作成（MOPF への送信は未確認） |

GUI: `$U python -m twinsim serve`（URL は `--url`）。画面の確かめは `tools/gui_shot.py`。
