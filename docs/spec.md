# twinsim の仕様（v0.2、2026-10-22）

[English](spec.en.md)

建物・工場の人流のデジタルツインのシミュレータ。研究計画（竹芝 VLM × QUBO、10/4 版）と、デジタルツインの構想の図（Observe → Understand → Predict & simulate → Optimize）を確かめるための環境。
人の動きは CPU で計算し（数秒〜数十秒）、映像が要るときだけ Isaac Sim で描く（GPU、数分〜数時間）。

```
シナリオ（JSON か YAML） ──> 人の動きの計算（CPU）──> 正解・表・集計・グラフ・枠 ──> 検知・追跡・GNN の学習と評価
   空間（space pack）                    └──> Isaac Sim で描画（GPU）──> 動画 ──> 検知・追跡・VLM
```

## 1. 空間（twinsim/spaces/<名前>/space.yaml か space.json）

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

今ある空間（どれも Isaac Sim 6.1 付属、CC BY 4.0）:

| 空間 | 中身 | 意味の地図 | 描画 |
|---|---|---|---|
| `office` | オフィスの 1 階のロビー（入口の廊下 → ゲート 3 レーン → ロビー → 受付・EV 2 基・待ち合わせ・南の出口） | 済 | 済 |
| `hospital` | 病院の 1 階（ロビー → 廊下 → 西の広間。EV は階段室の前の見立て）。hospital-sim の sim-gate と同じ点・カメラ | 済 | 済 |
| `warehouse` | 倉庫（北に棚 8 列の通路、南に作業の床。荷受け・梱包・待つ場所は見立て） | 済 | 済 |
| `simple_room` | 10 m 四方の小部屋（床 z = -0.77） | 済（動作確認用） | 未対応（中から撮ると真っ暗、原因未調査） |
| `warehouse_small` | 小さい倉庫（棚・扉・ゲートの部品） | 材料だけ（未） | 未 |

空間の確かめ: `python -m twinsim show-space <名前>` で、真上の図に歩ける所・目盛り・候補・場所・ゾーンを重ねた図（空間のフォルダの annotate.png）を作る。

## 2. シナリオ（JSON か YAML。テンプレートは twinsim/templates/<名前>.yaml）

| キー | 中身（既定） |
|---|---|
| `space` | 空間の名前 |
| `seed`・`fps`・`duration_s` | 乱数の種（0）、1 秒のコマ数（30）、長さ（120 秒） |
| `people` | `profile`（文献の値の組。`office_commute_jp`・`leisure_low_density`。docs/validity.md）、`speed`（歩く速さの分布、既定は 1.34 ± 0.26 m/s、Weidmann 1993）、`models`（人物モデル。`all`）、`group_size`（流れに書かないときのまとまりの人数）、`group_speed`（既定 `{model: moussaid2010, slope_m_s: 0.04}`。`{model: min}` で遅い人に合わせる）、`group_lateral_m`（2 人連れの横の間隔、既定 0.66、Zanlungo ら 2017）、`speed_density`（速さと密度の関係、既定 Weidmann 1993。`null` で切る）、`lateral_max_m`（経路から横へよけられる幅、1.0） |
| `demand` | EV を使う人の量: `population`（建物にいる人数）、`period`（`morning`・`lunch`）、`peak_pct_5min`（混む 5 分の割合、12）。`rate: {type: lift_demand}` と `alight.count: {type: lift_demand}` が使う（Peters ら 2011） |
| `streams[]` | 人の流れ: `name`、`origin`（現れる場所。場所の名前か、座標の `{"xy": [x, y]}`・`{"line": [[x0, y0], [x1, y1]]}`。線なら線の上のどこか。`name` を足すと集計での呼び名になる）、`rate`（到着の率）、`group_size`、`types`、`destinations[]`、`start_s`。座標は歩ける所の中で、行き先まで歩いて行ける所に置く（外なら計算の前に誤り） |
| `elevator` | `cars`（扉の名前）、`capacity`、`schedule`、`alight`（降りる人: `count`・`types`・`destinations`）、`transfer_s`（1 人の乗り降り、1.0 秒）、`door_open_s`（着いてから最初の人が動くまで、1.0 秒、仮） |
| `gates` | ゲートごとの `service_s`（1 レーンで 1 人を通す間隔。秒か分布。既定 1.5 秒、`office_commute_jp` では対数正規 中央 2.0 秒） |
| `validity` | `{speed_density: judge}` で密度ごとの速さを Weidmann の式で判定する（一方向の廊下の確かめだけ） |
| `cameras[]` | `name`（空間の候補の名前。新しい名前でもよい）と、上書きする `eye`・`target`（どちらも `[x, y, z]`）・`focal_mm`（12）・`h_aperture_mm`（20.955）・`width`・`height`・`clock_offset_s`・`drop_rate`（後ろの 2 つは記録するだけ）。新しい名前なら `eye` と `target` が必須 |
| `render` | `width`・`height`（1280×720）、`tint`（`per_person` で人ごとに服の色を変える、`false` で変えない。`twinsim.render(tint=...)` の引数が優先）、`props`（置く物の場所の名前）、`gate_props`（ゲートの機械を置く、`true`） |
| `outputs` | 書き出すもの（`ground_truth`・`frames`・`tasks`・`graph`・`mot`・`aicity`・`preview`・`validity`） |
| `variants`・`variant` | A/B の比較: `variants: {A: {名前: 値}}` と、行き先の `variant_p: 名前` で `p` を差し替える |
| `graph` | `cell_m`（格子のグラフの大きさ、2 m） |
| `mot_stride` | MOT の枠を何コマごとに書くか（1） |
| `congestion_levels` | 混雑の段階の境い目（人/m²、`[0.10, 0.20]`） |
| `name`・`title`・`title_en`・`description` | 名前と説明 |
| `calibration` | `twinsim calibrate` が書く、合わせ方の記録 |

行き先（`destinations[]` の要素）:

| キー | 中身 |
|---|---|
| `to` | `elevator`（EV を待って乗る）、場所の名前（`exit`・`spawn` なら出ていく、`spot` なら止まる）、場所の名前の頭（`reception` → `reception_*` のどれか） |
| `p` | 選ばれる重み |
| `types` | この行き先を選ぶ人の種類（`[visitor]` など。なければ全員） |
| `via` | 途中で通るゲート（`[gate]`）。向き（入館・退館）は位置から決まる |
| `dwell` | 止まる時間（分布、秒） |
| `state` | 止まる間の状態（既定: 受付 `reception`、待ち合わせ `dwell`、案内板 `sign_check`） |
| `glance` | 止まっている間に見回す幅（度） |
| `variant_p` | A/B の比較で、`p` を差し替える名前（`variants`） |
| `meet` | 待ち合わせ: `p`、`delay`（同行者が遅れて来る時間）、`from`（同行者の現れる場所。`origin` と同じ形）、`via`。待つ間の状態は `companion_wait` |
| `then` | 止まったあとの行き先（同じ形） |

EV の運行（`elevator.schedule`）:
- `{type: interval, offset: 分布, interval: 分布}` 号機ごとに、間隔の分布で着く
- `{type: times, times: {EV1: [秒, ...]}}` 着く時刻を指定
- `{type: on_demand, travel_s: 分布, max_wait_s: 60}` 待つ人がいて、予定がなければ呼ぶ（簡単な例）
- API の `elevator_policy(sim, t)` で自分の運行を差し込める（UC2 の最適化）

## 3. 分布の書き方（twinsim/dists.py）

`1.34`（定数）、`{type: normal, mean, sd, min, max}`、`{type: uniform, min, max}`、`{type: lognormal, median, sigma, min, max}`、
`{type: poisson, lam}`、`{type: zero_truncated_poisson, lam}`（0 を除いたポアソン。まとまりの人数）、`{type: choice, values: {名前: 重み}}`。
到着の率（`per_min` はまとまりの数/分。`unit: persons` なら人/分で、まとまりの平均の人数で割って使う）: `{type: constant, per_min: 8}`、
`{type: piecewise, per_min: [[秒, 率], ...]}`（時間帯で変わるポアソン過程。間引き法で引く）、`{type: lift_demand, flow: incoming, share: 0.9}`（`demand` から人/分）、
`{type: times, times: [秒, ...]}`（決めた時刻。確かめ用）。どの分布にも `source: <文献の名前>` を書くと、妥当性の台帳で文献として数える。

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
| `ground_truth.json` | 追跡の評価などが読める正解（`tracks`・`moving`・`people`・`cameras`）に、状態の区間（`people[].states`）・グループ・EV とゲートの出来事・ゾーンを足したもの |
| `frames.csv.gz` | 1 コマ 1 人 1 行（frame, t, person, x, y, yaw, moving, state, zone, group, type） |
| `tasks.json` | 計画書 p7 の 6 タスクの正解の集計: 1 人数（秒ごと・ゾーンごと・状態ごと）、2 ゲートの通過（1 分ごと・向き）、3 滞留（3 秒以上止まった区間）、4 グループ、5 混み具合（ゾーンの密度と段階）、6 出発地 → 行き先（1 分ごと）、EV の待ち時間 |
| `graph/` | GNN 向け: `graph.json`（ゾーンのグラフ・2 m の格子のグラフ・カメラから見えるノード）、`zone_counts.csv`（秒ごとのゾーンの人数）、`zone_flows.csv`（1 分ごとのゾーン間の移動）、`grid_counts.npz`（counts[秒, 格子]）、`zone_graph.graphml` |
| `mot/<カメラ>.txt` | MOTChallenge の形式の枠（frame, id, x, y, w, h, 1, 1, 見えている割合）。見えている割合は近似（壁は床の上の線で、人は手前の枠との重なりで数える） |
| `preview.png` | 真上の図に、人の軌跡（流れごとの色）・ゾーン・カメラの向きを重ねた確認の図 |
| `summary.json` | 人数・状態ごとの時間・EV の待ち時間・ゲートの通過の向き・かかった時間・`inputs`（文献から決めた到着の率・EV の乗り降り・ゲートの時間） |
| `validity.json`・`validity.md`・`validity.png` | 文献の値との比べ（入力の再現・出てくる量）と、シナリオの値ごとの根拠の台帳（docs/validity.md） |
| `aicity/gt.txt` | 複数カメラの追跡の形（AI City Challenge の MTMC）。人の番号はカメラをまたいで同じ |
| `logs/` | 記録の形（export-logs） |
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

## 7. GUI と REST API

`python -m twinsim serve`（127.0.0.1:8770 だけで待ち受け。手元の PC で `ssh -N -L 8770:localhost:8770 ampb` を実行し、
`python -m twinsim serve --url` で表示される URL を開く）。他の利用者もいるマシンなので、トークン（~/.config/twinsim/token、本人だけ読める）を確かめる。

- 画面: 左に空間の真上の図（ゾーン・場所・ゲートの線・カメラの位置と見る点と映る範囲、人の流れの現れる所。カメラと現れる所はドラッグで動かせる）、右に設定
  （長さ・乱数の種・流れごとの到着の率とまとまりと行き先の重み・EV・ゲート・カメラ・置く物、シナリオの全部を書ける JSON の欄）と結果
  （要約・確認の図・試し撮りと描画（見積もりを見て確かめてから始める）・動画・ファイル）。
- API（プログラムからは `Authorization: Bearer <トークン>`）: `GET /api/spaces`・`/api/spaces/<名前>`・`/api/spaces/<名前>/top`、
  `GET /api/templates`・`/api/templates/<名前>`、`POST /api/runs {scenario, overrides, name}` → `{id}`、`GET /api/runs`・`/api/runs/<id>`・
  `/api/runs/<id>/file?path=...`、`POST /api/runs/<id>/render {frames | window: "busy", seconds, cameras, confirm}`、`GET /api/isaac`。
- 画面の確かめ: `tools/gui_shot.py`（Playwright の Firefox で設定・結果のタブを撮り、カメラのドラッグとブラウザのエラーを確かめる）。

## 8. 描画（Isaac Sim、GPU）

```bash
isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
```

（2026-10-22 時点、ホストのドライバーが 615.71.10 で `--vnc` の画面は作れない。上の WebRTC 方式で動く。）
`render` は、計算の結果の人を人物モデル（10 種類、服の色は人ごとに変える）で置き、カメラごとに描いて mp4 にする。
描画の速さ（2026-10-22 の試し撮り、1280×720、GPU 1 枚）: オフィス 30 人で 1 秒に約 5.7 コマ、倉庫 15 人で約 1.9 コマ、病院 24 人で約 1.1 コマ
（病院は照明が多く遅い）。5 分（9,000 コマ）× 2 台の目安は、オフィス約 1 時間、倉庫約 2.6 時間、病院約 4.5 時間。
置く物: ゲートの機械（レーンを仕切る箱、自動）、サイネージ（`render.props`）、照明（空間の `lights`、部屋の中に照明がない USD 用）。
長い描画は、始める前に所要時間と GPU を示して確認を取る（GPU は他の利用者と共有）。

## 9. 妥当性

人の分布は文献の値で作り、計算ごとに文献の値と比べる（`validity.*`）。値と出典の一覧・確かめの基準・エンジンの確かめの結果・
文献のない値（仮）と実データでの合わせ方は [validity.md](validity.md)。確かめ用のテンプレート: `verify_corridor_speed`（RiMEA の試験 1 に相当）、
`verify_fundamental_diagram`（速さと密度）、`verify_groups`（グループ）、`verify_gate_capacity`（混んだゲート）。

## 10. 既知の限界

- 歩き方は「経路から横へずれてよける」簡単なモデル（hospital-sim を広げたもの）に、前の人についていく速さ（Seyfried ら 2005）・
  速さと密度の関係（Weidmann 1993）・追い越し・グループのまとまりを足したもの。すれ違いで 0.25〜0.4 m まで近づく。
  0.25〜1 人/m² では文献より 0.1 m/s ほど遅い。RiMEA のテストケースは 1 番に当たるものだけ。双方向の流れ・階段・避難は確かめていない。
- 入口（現れる場所）がふさがっていると、空くまで外で待つ（`events.spawn_wait_s`）。列が建物の外まで伸びる場面は、外で待つ人として数える。
- 見えている割合（MOT の 9 列目）は近似。正確な値は描画の深度から取る（未実装）。
- 1 つの階だけ。EV は扉で人が消える・現れるだけで、かごや他の階はない。扉の開閉のアニメーションは使っていない（オフィスの EV 1 基には開閉のアニメーションがある）。
- 病院は部屋の扉を閉じたまま歩ける所を作ったので、部屋の中には入れない。小部屋は描画が真っ暗（原因未調査）。
- 人物モデルは 10 種類（服の色で人を区別できるようにしている）。荷物・車いす・子ども・ロボット・台車はない。
- カメラの時計のずれ・コマ落ち（`clock_offset_s`・`drop_rate`）は記録するだけで、まだ動画と正解に反映していない。
