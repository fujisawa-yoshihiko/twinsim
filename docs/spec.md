# twinsim の仕様（v0.1、2026-10-22）

建物・工場の人流のデジタルツインのシミュレータ。研究計画（竹芝 VLM × QUBO、10/4 版）と、デジタルツインの構想の図（Observe → Understand → Predict & simulate → Optimize）を確かめるための環境。
人の動きは CPU で計算し（数秒〜数十秒）、映像が要るときだけ Isaac Sim で描く（GPU、数分〜数時間）。

```
シナリオ（YAML） ──> 人の動きの計算（CPU）──> 正解・表・集計・グラフ・枠 ──> 研究・MOPF・GNN
   空間（space pack）                    └──> Isaac Sim で描画（GPU）──> 動画 ──> MOPF・VLM
```

## 1. 空間（spaces/<名前>/space.yaml）

USD のシーン 1 つ分。USD に入っていない「意味」（入口・ゲート・EV の扉・待つ場所・ゾーン）をここに書く。

| キー | 中身 |
|---|---|
| `usd` | シーンの URL（Isaac Sim の素材など） |
| `license` | 素材の利用条件（配布するデータを作るときに確かめる） |
| `navmesh_region` | ナビメッシュを焼く範囲 `[x0, x1, y0, y1, z0, z1]`（1 つの階） |
| `levels[]` | 階: `z`、`walkable`（歩ける所の格子。`.txt` か `.npz`）、`top_image`・`top_view`（真上の図とその視点） |
| `pois` | 場所（下の表） |
| `zones` | ゾーン（多角形）。正解の集計とグラフのノード。上から順に当てはめる |
| `cameras` | カメラの候補（`eye`・`target`。シナリオで名前を指定して使う） |

場所（`pois`）の種類:

| kind | 意味 | キー |
|---|---|---|
| `spawn` | 人が現れる・消える所（建物の入口など） | `xy` |
| `exit` | 出ていく所 | `xy` |
| `gate` | 入館のゲート | `line`（両端）、`lanes`、`lanes_in`・`lanes_out`（向きごとに使うレーン）、`in_dir`（入館の向き） |
| `elevator` | EV の扉 | `xy`（扉の前）、`face`（かごの中の点） |
| `wait_zone` | EV 待ちの場所の範囲 | `zone`、`spacing`（間隔 m）、`door_aisle`（扉の前に空ける通り道の半分の幅 m） |
| `spot` | 止まる場所（受付・待ち合わせ・案内板の前） | `xy`、`face`（向く点）。名前の頭（`reception_`・`lounge_`）でまとめて行き先にできる |
| `prop` | シミュレータが置く物（USD にない物） | `xy`、`face`、`prop`（`signage`） |

空間を新しく作るとき: `python -m twinsim export-space <名前> --usd URL --region ...`（Isaac Sim で、歩ける所の格子・真上の図・
エレベーターや扉らしい prim の一覧を作り、space.yaml のひな形を置く）→ 真上の図と一覧を見て `pois`・`zones`・`cameras` を書く。

今ある空間: `office`（Isaac Sim 付属のオフィスの 1 階のロビー。入口の廊下 → ゲート → ロビー → 受付・EV 2 基・待ち合わせ・南の出口）。

## 2. シナリオ（templates/<名前>.yaml）

| キー | 中身（既定） |
|---|---|
| `space` | 空間の名前 |
| `seed`・`fps`・`duration_s` | 乱数の種（0）、1 秒のコマ数（30）、長さ（120 秒） |
| `people` | `speed`（歩く速さの分布、既定は平均 1.34 m/秒・標準偏差 0.26）、`models`（人物モデル。`all`）、`group_lateral_m`（グループの横の間隔 0.45） |
| `streams[]` | 人の流れ: `origin`（現れる場所）、`rate`（到着の率）、`group_size`、`types`、`destinations[]`、`start_s` |
| `elevator` | `cars`（扉の名前）、`capacity`、`schedule`、`alight`（降りる人: `count`・`types`・`destinations`） |
| `gates` | ゲートごとの `service_s`（1 レーンで 1 人を通す間隔、既定 1.5 秒） |
| `cameras[]` | `name`（空間の候補の名前）と、上書きする `eye`・`target`・`focal_mm`・`width`・`height`・`clock_offset_s`・`drop_rate` |
| `render` | `width`・`height`（1280×720）、`tint`（人ごとに服の色を変える）、`props`（置く物の場所の名前） |
| `outputs` | 書き出すもの（`ground_truth`・`frames`・`tasks`・`graph`・`mot`・`preview`） |
| `variants`・`variant` | A/B の比較: `variants: {A: {名前: 値}}` と、行き先の `variant_p: 名前` で `p` を差し替える |
| `graph` | `cell_m`（格子のグラフの大きさ、2 m） |

行き先（`destinations[]` の要素）:

| キー | 中身 |
|---|---|
| `to` | `elevator`（EV を待って乗る）、場所の名前（`exit`・`spawn` なら出ていく、`spot` なら止まる）、場所の名前の頭（`reception` → `reception_*` のどれか） |
| `p` | 選ばれる重み |
| `types` | この行き先を選ぶ人の種類（`[visitor]` など。なければ全員） |
| `via` | 途中で通るゲート（`[gate]`）。向き（入館・退館）は位置から決まる |
| `dwell` | 止まる時間（分布、秒） |
| `state` | 止まる間の状態（既定: 受付 `reception`、待ち合わせ `dwell`、案内板 `sign_check`） |
| `meet` | 待ち合わせ: `p`、`delay`（同行者が遅れて来る時間）、`from`（同行者の現れる場所）、`via`。待つ間の状態は `companion_wait` |
| `then` | 止まったあとの行き先（同じ形） |

EV の運行（`elevator.schedule`）:
- `{type: interval, offset: 分布, interval: 分布}` 号機ごとに、間隔の分布で着く
- `{type: times, times: {EV1: [秒, ...]}}` 着く時刻を指定
- `{type: on_demand, travel_s: 分布, max_wait_s: 60}` 待つ人がいて、予定がなければ呼ぶ（簡単な例）
- API の `elevator_policy(sim, t)` で自分の運行を差し込める（UC2 の最適化）

## 3. 分布の書き方（twinsim/dists.py）

`1.34`（定数）、`{type: normal, mean, sd, min, max}`、`{type: uniform, min, max}`、`{type: lognormal, median, sigma, min, max}`、
`{type: poisson, lam}`、`{type: zero_truncated_poisson, lam}`（0 を除いたポアソン。まとまりの人数）、`{type: choice, values: {名前: 重み}}`。
到着の率: `{type: constant, per_min: 8}`、`{type: piecewise, per_min: [[秒, 人/分], ...]}`（時間帯で変わるポアソン過程。間引き法で引く）。

## 4. 状態（1 コマごとの正解）

| 状態 | 意味 |
|---|---|
| `pass` | 歩いて通る・行き先へ向かう |
| `gate_queue` | ゲートの列に並ぶ |
| `ev_approach` | EV 待ちの場所へ向かう（EV 待ちのゾーンの中） |
| `ev_wait` | EV を待つ（乗り込みに歩く間も含む） |
| `alight` | EV から降りる（扉から 3 m・EV 待ちのゾーンの中） |
| `reception` | 受付で止まる |
| `dwell` | そのほかの場所で止まる |
| `sign_check` | 案内板・サイネージを見る |
| `companion_wait` | 同行者を待つ |

## 5. 出力（結果の場所。既定は ~/dt-data/twinsim/runs/<シナリオの名前>）

| ファイル | 中身 |
|---|---|
| `ground_truth.json` | 研究側（`~/MOPF_ALL_video/research` の `cctv_eval_lib`・`flow_tasks`）が読める正解（`tracks`・`moving`・`people`・`cameras`）に、状態の区間（`people[].states`）・グループ・EV とゲートの出来事・ゾーンを足したもの |
| `frames.csv.gz` | 1 コマ 1 人 1 行（frame, t, person, x, y, yaw, moving, state, zone, group, type） |
| `tasks.json` | 計画書 p7 の 6 タスクの正解の集計: 1 人数（秒ごと・ゾーンごと・状態ごと）、2 ゲートの通過（1 分ごと・向き）、3 滞留（3 秒以上止まった区間）、4 グループ、5 混み具合（ゾーンの密度と段階）、6 出発地 → 行き先（1 分ごと）、EV の待ち時間 |
| `graph/` | GNN 向け: `graph.json`（ゾーンのグラフ・2 m の格子のグラフ・カメラから見えるノード）、`zone_counts.csv`（秒ごとのゾーンの人数）、`zone_flows.csv`（1 分ごとのゾーン間の移動）、`grid_counts.npz`（counts[秒, 格子]）、`zone_graph.graphml` |
| `mot/<カメラ>.txt` | MOTChallenge の形式の枠（frame, id, x, y, w, h, 1, 1, 見えている割合）。見えている割合は近似（壁は床の上の線で、人は手前の枠との重なりで数える） |
| `preview.png` | 真上の図に、人の軌跡（流れごとの色）・ゾーン・カメラの向きを重ねた確認の図 |
| `summary.json` | 人数・状態ごとの時間・EV の待ち時間・ゲートの通過の向き・かかった時間 |
| `video/<カメラ>.mp4` | 描画した動画（`render` のあと） |

## 6. 使い方（API）

```bash
cd ~/twinsim
U="uv run --no-project --with numpy --with scipy --with pyyaml --with pillow --with networkx"
$U python -m twinsim templates                                # テンプレートの一覧
$U python -m twinsim run office_gate_ev --set duration_s=120   # 計算（CPU）。--set でシナリオの値を上書き
$U python -m twinsim check ~/dt-data/twinsim/runs/office_gate_ev   # 確かめ
$U python -m twinsim render ~/dt-data/twinsim/runs/office_gate_ev --frames 3000 3149   # 試し撮り（GPU）
```

Python から: `from twinsim import api; api.run("office_gate_ev", out_dir, overrides={...}, elevator_policy=f)`。

## 7. 描画（Isaac Sim、GPU）

```bash
isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
```

（2026-10-22 時点、ホストのドライバーが 615.71.10 で `--vnc` の画面は作れない。上の WebRTC 方式で動く。）
`render` は、計算の結果の人を人物モデル（10 種類、服の色は人ごとに変える）で置き、カメラごとに描いて mp4 にする。
描画の速さの目安（hospital-sim の記録）: 1280×720、人が 30〜90 人で、1 秒に 2.5〜3.5 コマ（GPU 1 枚）。5 分 × 2 台で 1.5〜2 時間。
長い描画は、始める前に所要時間と GPU を示して確認を取る（GPU は他の利用者と共有）。

## 8. 妥当性（今の段階と、合わせ方）

| 項目 | 今の値 | 根拠 | 実データでの合わせ方 |
|---|---|---|---|
| 歩く速さ | 平均 1.34 m/秒・標準偏差 0.26（0.8〜1.9 で切る）。グループは遅い人に合わせる | 文献の目安（Weidmann 1993） | MOPF の床の上の軌跡 |
| 到着 | 時間帯で率が変わるポアソン過程。値はテンプレートの仮の値 | 形は一般的な仮定、値は仮 | ゲートの通過記録（時刻の集計） |
| まとまり | 0 を除いたポアソン | 形は Coleman & James 1961、値は仮 | 実映像で一緒に歩く人数を数える |
| 行き先・止まる時間 | テンプレートの仮の値 | 仮 | 実映像の短い区間に手でラベル、研究 2 の流れの推定 |
| EV | 号機ごとの到着の間隔・定員 8 | 仮 | 運行記録（東急不動産に依頼） |
| ゲート | 1 レーンで 1.5〜1.6 秒に 1 人 | 仮 | ゲートの通過記録 |

`check` で見る目安（office_gate_ev、104 人・5 分）: 壁の中のコマ 0.006%、グループ以外の 2 人の最も近い距離の 1 パーセンタイル 0.12 m、
0.4 m 未満に近づくコマ 10%（ほとんどが 0.25〜0.4 m のすれ違い）、歩く速さの中央値 1.24 m/秒。

## 9. 既知の限界

- 歩き方は「経路から横へずれてよける」簡単なモデル（hospital-sim と同じ）。すれ違いで 0.25〜0.4 m まで近づく。速さと密度の関係（混むと遅くなる）は入っていない。
  歩行者シミュレータの標準の検証（RiMEA のテストケース、ISO 20414）はまだしていない。
- 見えている割合（MOT の 9 列目）は近似。正確な値は描画の深度から取る（未実装）。
- 1 つの階だけ。EV は扉で人が消える・現れるだけで、かごや他の階はない。扉の開閉のアニメーションは使っていない。
- 人物モデルは 10 種類（服の色で人を区別できるようにしている）。荷物・車いす・子ども・ロボット・台車はない。
- カメラの時計のずれ・コマ落ち（`clock_offset_s`・`drop_rate`）は記録するだけで、まだ動画と正解に反映していない。
