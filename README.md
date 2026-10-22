# twinsim — 建物・工場の人流のデジタルツインのシミュレータ

研究計画（竹芝 VLM × QUBO、10/4 版）とデジタルツインの構想を確かめるための 3D のシミュレータ。
空間（USD）・人の分布・カメラ・イベント（EV・ゲート）をシナリオのファイルで決め、人の動きを CPU で計算し、
正解・集計・GNN 向けのグラフ・カメラの枠を書き出す。映像が要るときは Isaac Sim で描く。仕様は [docs/spec.md](docs/spec.md)。

## すぐ試す

```bash
cd ~/twinsim
U="uv run --no-project --with numpy --with scipy --with pyyaml --with pillow --with networkx"
$U python -m twinsim templates
$U python -m twinsim run office_gate_ev          # 5 分・約 100 人、計算 6 秒＋書き出し 11 秒
$U python -m twinsim check ~/dt-data/twinsim/runs/office_gate_ev
```

結果は `~/dt-data/twinsim/runs/<名前>/`（`preview.png` で軌跡を確かめられる）。描画は docs/spec.md の「描画」。

## 構成

| 場所 | 中身 |
|---|---|
| `twinsim/space.py` | 空間（歩ける所の格子・意味の地図・経路 A*） |
| `twinsim/engine.py` | 人の動き（段取り・よけ合い・ゲートの列・複数台の EV）。hospital-sim の flow_scene2_lib を広げたもの |
| `twinsim/scenario.py`・`dists.py` | シナリオと分布 → 人の発生・行き先・EV・ゲート |
| `twinsim/outputs.py`・`camera.py`・`quality.py` | 正解・集計・グラフ・枠・確かめ |
| `twinsim/api.py`・`__main__.py` | Python の API とコマンド |
| `twinsim/isaac_bridge.py`・`isaac/` | Isaac Sim での描画と、USD から空間を作る部品（`isaac/vendor/` は hospital-sim から写した人物の部品） |
| `spaces/` | 空間（今は `office`） |
| `templates/` | テンプレート（下の表） |
| `tests/` | 動作確認（`$U --with pytest pytest -q tests`） |

| テンプレート | 確かめること |
|---|---|
| `office_smoke` | 動作確認（30 秒） |
| `office_gate_ev` | ゲート → EV（UC1・UC2、研究 2 の 2 地点の流れ）。朝の到着の山、カメラ 2 台 |
| `office_ev_hall` | EV 前の紛らわしい状態（研究 1 の RQ1）。EV 待ち・同行者待ち・案内確認・受付 |
| `office_signage_ab` | サイネージの比較（UC3）。同じ到着で、見る人の割合を A・B で変える（効果を測る方法の確かめ。効果そのものは確かめられない） |

## 欲しい機能（Notion の「シミュレータ」）との対応（2026-10-22）

| 欲しい機能 | 状態 |
|---|---|
| PDF の内容を確かめられる 3D のシミュレータ | 人の動き・正解・集計は済。描画は部品を作った（試し撮りは GPU が空いてから） |
| 空間を選べる（オフィス・病院・倉庫・小部屋） | オフィスは済。ほかは `export-space` で材料を作り、意味の地図を描く（未） |
| オープンな USD・自分でアップロード | `export-space`（USD の URL か場所から材料とひな形を作る）は作った。画面からのアップロードは未 |
| 人の分布を制御 | 済（到着の率・まとまり・種類・行き先・速さ・止まる時間） |
| カメラ・発生・移動・イベントの制御（GUI・文書） | シナリオのファイルと文書は済。GUI（真上の図の上で編集する Web 画面）は未 |
| テンプレート | 4 つ（上の表） |
| API（MOPF・GNN） | Python の API・コマンドは済。グラフの書き出し（GNN）は済。MOPF への自動の設定（床の図・線・エリア）と REST は未 |
