# ほかのアプリとの連携（MOPF・中間層のグラフ・研究のコード・実データ）

2026-10-22。twinsim の結果を、MOPF（`~/MOPF_ALL_video`）・GNN などのグラフのタスク・研究のコード・実データとつなぐ方法。

## 1. 全体の流れ

```
シナリオ（人の分布は文献・実データ） ─→ twinsim（CPU）─→ 正解（ground_truth・mot・aicity）・中間層のグラフ（graph/）・記録の形（logs/）
                                              │
                                              └→ Isaac Sim（GPU）で描画 ─→ video/<カメラ>.mp4
                                                                           │
                       MOPF（GPU）: 検出・追跡 ←───────────────────────────┘（mopf-process、またはライブに流す）
                           │
                           ├→ twinsim mopf-eval: 正解と比べる（MOTA・IDF1・人数・足元のずれ）
                           └→ 中間層のグラフ（mopf_graph/、graph/ と同じ形）─→ GNN・最適化（MOPF_OPT）─→ EV の運行など（elevator_policy）─→ twinsim
実データ（ゲートの通過記録・EV の運行記録）─→ twinsim calibrate ─→ 出典つきのシナリオ
```

Notion の要件の「API による連携（MOPF・GNN）」「シミュレータの映像を MOPF に流す（本番のリハーサル）」「グラフベースの中間層」に当たる。

## 2. MOPF で動画を処理して比べる（オフライン）

```bash
cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --no-llm --no-vc3     # MOPF を起動（GPU。確認を取ってから。カメラの入力なしで）
cd ~/twinsim
./run.sh mopf-process ~/dt-data/twinsim/runs/office_gate_ev        # video/*.mp4 を MOPF に送り、追跡を mopf_tracks/ に受け取る
./run.sh mopf-eval ~/dt-data/twinsim/runs/office_gate_ev           # 正解と比べる（mopf_eval/）・中間層のグラフ（mopf_graph/）
```

- 動画は MOPF の `uploads/twinsim-<結果の名前>-<カメラ>.mp4` に写し、`POST /api/video/process/<名前>?model_name=yolo11m` で処理する。
  結果は `outputs/uploads/<名前>/tracking.jsonl`（MOPF の形）。
- 比べ方: 正解の枠は `mot/<カメラ>.txt`（人を囲む箱を映した近似の枠と、見えている割合）。IoU 0.3 以上で対応づけ、
  見えている割合 0.4 未満の正解は見逃しにも誤検出にも数えない。動画の 0 コマ目は `render_log.json` の `frames[0]`。
- 出すもの: MOTA・IDF1・ID の切り替わり・再現率・適合率、画面の人数の誤差、足元（枠の下の真ん中）を床に移した位置と正解のずれ。
  足元は体の手前の端に当たるので、追跡が完全でも 0.3 m ほどずれる。
- 確かめ: 正解から作った MOPF の形の追跡（`mopf_link.synthetic_tracks`）で、誤りなしなら MOTA・IDF1 が 1、見逃し 20% なら再現率 0.8（`tests/test_validity.py`）。
- GUI の結果のタブにも「動画を MOPF で検出・追跡（GPU）」「MOPF の追跡を正解と比べる」がある（GPU を使う前に確認の画面が出る）。

### 実際に MOPF で処理した結果（2026-10-22、A: 試し撮り 5 秒 × 2 台、yolo11m・BoostTrack、GPU 3）

結果: `~/dt-data/twinsim/runs/office_gate_ev-20261022-172550/`（mopf_tracks・mopf_eval・mopf_graph）。処理は 2 本で 18 秒。

| カメラ | MOTA | IDF1 | ID の切り替わり | 再現率 | 適合率 | 画面の人数の誤差 | 足元のずれ（中央） |
|---|---|---|---|---|---|---|---|
| CamGate（ゲート） | 0.950 | 0.975 | 0 | 0.952 | 0.998 | 0.17 人 | 0.19 m |
| CamEV（EV 前） | 0.906 | 0.922 | 5 | 0.976 | 0.936 | 0.54 人 | 0.18 m |

- 中間層のグラフ（ゾーンの人数の平均）: EV 前 MOPF 10.3 人 / 正解 14.2 人、ゲート前 1.3 人 / 2.7 人。混んだ所・遠い所で少なく出る。
- この試し撮りは前の版の計算で、`mot/ids.json` がなかったので、枠の位置から作り直した（`ensure_ids`）。
### 5 分 × 2 台（2026-10-23、B: office_gate_ev、94 人・在館 600 人の朝の山、描画 89 分・MOPF の処理 1 本 約 3 分）

結果: `~/dt-data/twinsim/runs/office_gate_ev/`（video・mopf_tracks・mopf_eval・mopf_graph、記録は night_b.log）。

| カメラ | MOTA | IDF1 | ID の切り替わり | 再現率 | 適合率 | 人の数（正解 / MOPF の ID） | 画面の人数の誤差 | 足元のずれ（中央・90%） |
|---|---|---|---|---|---|---|---|---|
| CamGate（ゲート） | 0.868 | 0.859 | 29 | 0.893 | 0.975 | 87 / 114 | 0.23 人 | 0.22・0.40 m |
| CamEV（EV 前） | 0.898 | 0.878 | 29 | 0.964 | 0.936 | 83 / 112 | 0.16 人 | 0.16・0.38 m |

- 5 秒の試し撮り（A）より ID の切り替わりが多い（5 分で各 29 回。ID の数が正解の人数の約 1.3 倍）。長い動画では人が重なる場面が増える。
- ゲートの線を MOPF の追跡で（人流モニターと同じ決まりで）数えると、入館 48・退館 3。正解なら（見えている人の足元で）入館 67・退館 3、
  ゲートの通過の記録は入館 73・退館 7。入館を 3 割ほど数えもらした。
  原因は追跡ではなく線の場所: 入館の人は奥の扉の陰から現れてカメラのほうへ歩くが、線が扉のすぐ手前にあり、現れた時点で足元が線の上か
  線を越えている（線の手前にいた記録ができない）。線を入館の向きへずらすと（`mopf.LINE_OFFSET_M`、既定を 1 m にした）:

  | ずらす距離 | 正解なら（入館・退館） | MOPF（入館・退館） |
  |---|---|---|
  | 0 m | 67・3 | 48・3 |
  | 0.5 m | 71・3 | 61・8 |
  | 1.0 m | 70・4 | 65・10 |
  | 1.5 m | 70・4 | 66・8 |
  | 3.0 m | 68・13 | 67・12（ロビーのほかの流れも横切る） |

  1 m では、正解の 74 回のうち 67 回を MOPF が数え（91%）、数えもらし 7・余分 8（退館の向きに多い。ID の切り替わりで行き来に見える）。
- 見て確かめるもの: `mopf_eval/<カメラ>_overlay.mp4`（正解と MOPF の枠を重ね、数えもらし・ID の切り替わりの時刻に印）、
  `mopf_eval/CamGate_missed.png`（数えもらした場面の一覧）、`mopf_eval/CamGate_crossings.json`（時刻と人）。`./run.sh mopf-overlay <結果>` で作る。
- 中間層のグラフ（ゾーンの人数の平均）: EV 前 MOPF 3.5 人 / 正解 4.0 人（誤差 0.61）、ゲート前 1.1 人 / 1.7 人（誤差 0.69）。
- 途中で止まったとき（描画のあと）は `tools/night_b.sh --resume` で mp4 にするところから続けられる（`isaac_bridge.finish_render`）。

## 3. MOPF の人流モニター（ライブ）

```bash
./run.sh mopf ~/dt-data/twinsim/runs/office_gate_ev --camera CamGate            # 設定（床の図・位置合わせ・線・エリア）と、正解なら数えるはずの値
cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --live-demo ~/dt-data/twinsim/runs/office_gate_ev/video/CamGate.mp4   # 動画を RTSP でライブに流す
cd ~/twinsim && ./run.sh mopf ~/dt-data/twinsim/runs/office_gate_ev --camera CamGate --apply   # 設定を MOPF に送る
```

- 設定は、シミュレータがカメラの行列と床の座標を知っているので、手で 4 点を合わせる代わりに床の格子点から作る（`mopf.py`）。
- 正解なら数えるはずの値（`mopf/<カメラ>/expected.json`）は、MOPF の人流モニターと同じ決まり（足元・線から 8 画素・線分の交差）で、
  見えている割合 0.4 以上の人の足元から数える。ライブは動画を繰り返すので、1 周あたりで比べる。
  例（office_gate_ev・CamGate・5 分）: ゲートの線を入館 67・退館 3、ゲートの前のエリアに入った人 87。
- 確かめ（2026-10-22、A の試し撮りの CamGate 5 秒を繰り返し、60 秒）: 設定は `--apply` で MOPF に届いた。ゲートの線は入館 0・退館 0 で、
  正解（1 周あたり 0・0）と一致。ゲート前のエリアに入った回数は 1 周あたり約 3（正解は 5 人）。ライブでは映像が 640×360 に縮まり、
  遠い人の検出が落ちる（動画の処理は 1280×720 で再現率 0.95）。

## 4. 中間層のグラフ（シミュレータからでも MOPF からでも同じ形）

| ファイル | 中身 |
|---|---|
| `graph/graph.json` | ゾーンのグラフ（ノード: ゾーン、辺: 隣り合うゾーン）・2 m の格子のグラフ・カメラから見えるノード（`observed`） |
| `graph/zone_counts.csv`・`mopf_graph/<カメラ>/zone_counts.csv` | 秒ごとのゾーンの人数（列: t, ゾーン…） |
| `graph/zone_flows.csv`・`mopf_graph/<カメラ>/zone_flows.csv` | 1 分ごとのゾーン間の移動（minute, source, target, count） |
| `graph/grid_counts.npz` | 格子のノードの人数（counts[秒, 格子]） |

- `graph/` はシミュレータの正解（全員）、`mopf_graph/` は MOPF の追跡（足元を床に移した位置）から作る。同じ形なので、GNN や最適化は
  どちらからでも同じように読める（映像 → グラフ → 学習・最適化、の 2 層の分け方）。
- 比べると、追跡が完全でも、ほとんど隠れた人と足元のずれのため、EV 前の人数は平均 1 人少なく出る（正解 4.0 人に対し 3.0 人）。
  実カメラからグラフを作るときは、見えない分の補正（重なりの補正 QAQS・人数の推定）が要る。

## 5. 研究のコード（~/MOPF_ALL_video/research）

`research/sim-cctv/cctv_eval_lib.py` は `SIM_DATASET=twinsim TWINSIM_RUN=<結果の場所>` で twinsim の結果を読む（正解の形が同じ）。
MOPF の結果は `TRACKS_DIR` の下の `twinsim-<結果の名前>-<カメラ>/tracking.jsonl`。ただし研究の評価は隠れているかを知らない
（画面に入っていれば映っているはずと数える）ので、同じ追跡でも再現率が低く出る。twinsim の結果には `mopf-eval` を使う。

## 6. 正解の形（ほかの道具向け）

- `mot/<カメラ>.txt`: MOTChallenge（frame, id, x, y, w, h, 1, 1, 見えている割合）
- `aicity/gt.txt`: 複数カメラの追跡（AI City Challenge の MTMC: camera_id obj_id frame_id xmin ymin width height xworld yworld）。人の番号はカメラをまたいで同じ
- `tasks.json`: 計画書 p7 の 6 タスクの正解の集計、`frames.csv.gz`: 1 コマ 1 人 1 行

## 7. 実データで合わせる（記録の形と、お願いするデータ）

```bash
./run.sh export-logs ~/dt-data/twinsim/runs/office_gate_ev     # シミュレータの結果を記録の形に（形の見本）
./run.sh calibrate office_gate_ev --gate-log gate_log.csv --ev-log ev_log.csv   # 記録で合わせたシナリオ（~/dt-data/twinsim/calibration/<id>/）
```

| 記録 | 列 | 1 行 | 合わせるもの |
|---|---|---|---|
| ゲートの通過記録 `gate_log.csv` | time_s, gate, lane, direction（in/out）, person（なくてよい） | 1 人が通るごと | 入る流れの 1 分ごとの人数、ゲートの 1 人あたりの時間（間隔 4 秒以下に対数正規） |
| EV の運行記録 `ev_log.csv` | time_s, car, boarded, alighted（分かれば） | EV がロビーの階に着くごと | 号機ごとの着く間隔（対数正規、または時刻をそのまま `--ev-mode replay`）、降りる人の平均 |

- 合わせた値には `source: data:<id>` が付き、シナリオの `calibration` の欄に記録のファイル・ハッシュ・日時が残る。妥当性の台帳では「実データ」と数える。
- 往復の確かめ（シミュレータの記録で合わせる）: 到着 10.9 人/分（元 11.0）、ゲートの時間 中央 2.03 秒（元 2.0）、EV の間隔 中央 44 秒（元 35〜60 秒）。
- 竹芝の記録（NDA の対象になりうる）から作ったものは、git にも共有の場所にも置かない（既定の置き場所は `~/dt-data` の下）。
- 東急不動産にお願いするときの形の案: 上の 2 つ（時刻は秒かミリ秒、日付と時刻でもよい）。EV が行き先階の予約の方式かどうかも確かめる。

## 8. REST API（GUI のサーバー、`Authorization: Bearer <トークン>`）

`POST /api/runs {scenario, overrides}` で計算、`GET /api/runs/<id>/file?path=...` でファイル、
`POST /api/runs/<id>/mopf {camera, apply}`（人流モニターの設定と、数えるはずの値）、
`POST /api/runs/<id>/mopf/process {cameras, model, confirm}`（MOPF で処理。confirm なしは見積もり）、`POST /api/runs/<id>/mopf/eval`（比べる・グラフ）。
Python からは `twinsim.api.run(..., elevator_policy=f)` で EV の運行を差し替えられる（最適化の差し込み口）。

## 9. まだのこと

- 一周のつなぎ（MOPF の出力 → 最適化（MOPF_OPT の Gurobi）→ EV の運行 → シミュレータ → 結果）。差し込み口（`elevator_policy`）はあるが、MOPF_OPT とはつないでいない
- 外から API でイベント（サイネージの切り替え・混んだら案内）を指示する口
- ライブに流す動画の切り替えの自動化（今は `start_ampb.sh --live-demo` を手で実行。cv-app を作り直す）
