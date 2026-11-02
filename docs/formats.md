# 出力の形（学習データ・正解ラベル）

[English](formats.en.md)

twinsim の計算・描画が書き出すファイルの形。検出・追跡・複数カメラの追跡・人物照合・人流の予測・グラフの学習・状態の判別（VLM）など、
ほかの目的で使う人向け。

## 0. 共通の約束

| 項目 | 約束 |
|---|---|
| 置き場所 | `<TWINSIM_DATA>/runs/<結果の名前>/` か、`out_dir` で決めた場所（`TWINSIM_DATA` の既定は `~/.twinsim`）。git には入れない |
| 座標 | 世界の座標（m）。Z が上。床の高さは空間の `levels[0].z`（office は 0）。x・y は `twinsim/spaces/<空間>/space.yaml` と同じ |
| 向き（yaw） | 度。+X から反時計回り（`atan2(dy, dx)`）。−180〜180。歩いている間は進む向き、止まっている間は向いている向き |
| 時刻 | シミュレータのコマは 0 始まり、秒 = コマ ÷ fps（既定 30）。`events` などの時刻は秒 |
| コマの番号のずれ | MOT・AI City の形は 1 始まり（= シミュレータのコマ ＋ 1）。動画の k コマ目 = シミュレータのコマ `render_log.json` の `frames[0]` ＋ k（全部を描いたときは同じ） |
| 人の名前 | `P0001`…（計算ごとに付け直す）。MOT・AI City の数の ID は `mot/ids.json` で名前と対応（カメラをまたいで同じ） |
| グループ | 正解のグループは `G001`…（一緒に歩く人のまとまり） |
| 人の枠 | 足元を中心に、半径 0.25 m・背の高さ（`height_m`）の箱を映した枠。描かれた人の輪郭にぴったりではなく少し大きい（対応づけは IoU 0.3 が目安） |
| 見えている割合 | 近似。壁: カメラの真下から足元・頭への床の上の線が歩けない所を 1 m 以上通れば 0。人: 手前の人の枠と重なる割合（枠の中の 8×16 点）。描画の深度は使っていない |

カメラ（`ground_truth.json` の `cameras[名前]`）は USD のカメラと同じ表し方: 行ベクトル `p_cam = [x, y, z, 1] · M`（`M` = `world_to_camera_rowmajor`、4×4）、
カメラは −Z を見て +Y が上。画素への写し方:

```python
import numpy as np
def project(cam, pts):                       # pts: (N, 3) 世界の座標 → (N, 2) 画素、奥行き
    ph = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ np.asarray(cam["world_to_camera_rowmajor"])
    depth = -ph[:, 2]
    u = cam["cx_px"] + cam["fx_px"] * ph[:, 0] / depth
    v = cam["cy_px"] - cam["fy_px"] * ph[:, 1] / depth
    return np.c_[u, v], depth
```

レンズのゆがみはない（ピンホール）。ほかの値: `eye`・`target`（世界の座標）、`focal_mm`・`h_aperture_mm`、`width`・`height`（既定 1280×720）、
`h_fov_deg`、`tilt_down_deg`、`fps`。`twinsim/camera.py` の `Camera` がそのまま読める。

## 1. ファイルの一覧

| ファイル | 中身 | 主な使い道 |
|---|---|---|
| `ground_truth.json` | 人ごとの軌跡・状態・出来事・属性、カメラ、EV・ゲートの出来事、ゾーン | すべての正解の元 |
| `frames.csv.gz` | 1 コマ 1 人 1 行の表 | 軌跡の予測・集計・表計算 |
| `mot/<カメラ>.txt`・`mot/ids.json` | カメラごとの人の枠（MOTChallenge の形） | 検出・1 台の追跡の学習と評価 |
| `aicity/gt.txt`・`aicity/cameras.json` | 複数カメラの枠と世界の位置（AI City Challenge の MTMC の形） | 複数カメラの追跡・人物照合 |
| `video/<カメラ>.mp4`・`render_log.json` | 描いた動画（H.264、fps は正解と同じ）と描いた範囲 | 上の枠と合わせて画像の学習 |
| `tasks.json` | 計画書 p7 の 6 タスクの正解の集計 | 人数・流れ・滞留・混雑の評価 |
| `graph/` | ゾーンのグラフ・格子のグラフと、人数・流れの時系列 | GNN・時系列の予測 |
| `logs/` | ゲートの通過記録・EV の運行記録（実データと同じ形）。`twinsim export-logs <結果>` で作る | 実データで合わせる（`calibrate`）の見本 |
| `summary.json`・`scenario_resolved.json`・`.yaml` | 要約と、既定を足したシナリオ（乱数の種を含む） | 作り直し・記録 |
| `validity.*`・`preview.png` | 文献との比べ・確認の図 | 人の分布の妥当性 |

## 2. `ground_truth.json`

| キー | 中身 |
|---|---|
| `fps`・`total_frames`・`seed`・`space`・`scenario` | コマ数（1 秒）・全体のコマ数・乱数の種・空間の名前・シナリオの名前 |
| `people[名前]` | 人の属性と段取り（下の表） |
| `tracks[名前]` | `[[x, y, yaw], …]`。k 番目は `people[名前].start_frame + k` のコマ（現れてから消えるまで） |
| `moving[名前]` | `[0/1, …]`。そのコマに歩いているか（`tracks` と同じ長さ） |
| `cameras[名前]` | カメラ（0 の表し方） |
| `gate_events` | `[{t, gate, lane, person, dir: in/out}]`。ゲートを通った時刻 |
| `elevator_events` | `[{t, car, boarded: [名前], alighted: [名前]}]`。EV が着いた時刻と、乗った人・降りた人 |
| `elevator_times`・`cars`・`spots`・`door` | EV の着く時刻、号機の扉の位置・定員、EV 待ちの立つ場所 |
| `gates[名前]` | レーンの中心 `lanes`・入館の向き `in_dir`・1 人あたりの時間 `service_s` |
| `zones[名前]` | ゾーンの多角形 `[[x, y], …]` |

`people[名前]` の中身:

| キー | 中身 |
|---|---|
| `model`・`kind`・`height_m`・`tint_index` | 人物モデル（Isaac Sim の人物、10 種類）・性別 F/M・背の高さ（m）・服の色の番号（描画で人ごとに色を変える） |
| `type`・`stream`・`origin`・`destination`・`flow` | 種類（staff・visitor など）・流れの名前・現れた場所・行き先・「現れた場所->行き先」 |
| `group`・`role` | グループの名前（`G001`、1 人なら null）・同行者なら `companion` |
| `start_frame`・`arrive_frame`・`speed_m_s` | 現れた・消えたコマ、思う歩く速さ |
| `states` | `[[始まりのコマ, 終わりのコマ, 状態], …]`（状態は下の表） |
| `events` | 秒。`start`・`end`、`gate_join`・`gate`（列に並んだ・通った）、`hall`・`wait_start`・`car`・`board_start`・`board`（EV）、`stops`（止まった区間）、`meet_start`・`meet_end`、`spawn_wait_s`（入口がふさがって外で待った秒） |

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
| `work`・`wait` | 倉庫の作業・待ち（倉庫のテンプレート） |

## 3. `frames.csv.gz`

1 行目が列の名前: `frame, t, person, x, y, yaw, moving, state, zone, group, type`。
`t` は秒、`moving` は 0/1、`zone` は足元のゾーン（なければ空）、`group` は空か `G…`。

## 4. カメラの枠

`mot/<カメラ>.txt`（MOTChallenge の gt.txt と同じ、カンマ区切り）: `frame, id, x, y, w, h, conf, class, visibility`。
`frame` は 1 始まり、`id` は `mot/ids.json` の番号、`x, y, w, h` は画素（左上と幅・高さ）、`conf` と `class` は 1、`visibility` は見えている割合（0〜1、近似）。
枠の 2 割以上が画面に入っている人を、隠れていても書く（見えている割合 0.4 未満は学習・評価から外すのが目安）。シナリオの `mot_stride` で間引ける。

`mot/ids.json`: `{"P0001": 1, …}`。番号はカメラをまたいで同じ人に同じ。

`aicity/gt.txt`（AI City Challenge の MTMC と同じ、空白区切り）: `camera_id obj_id frame_id xmin ymin width height xworld yworld`。
`camera_id` は `aicity/cameras.json`（`{"CamEV": 1, …}`）、`obj_id` は `mot/ids.json` と同じ、`frame_id` は 1 始まり、`xworld yworld` は足元の世界の座標（m）。

## 5. `tasks.json`（計画書 p7 の 6 タスク）

| キー | 中身 |
|---|---|
| `seconds`・`zones`・`zone_area_m2` | 秒の数、ゾーンの名前、ゾーンの面積 |
| `1_count` | `present`（秒ごとの全体の人数）、`by_zone[ゾーン]`・`by_state[状態]`（秒ごとの人数）。各秒の最初のコマで数える |
| `2_direction` | `gate_per_min["ゲート:in/out"]`（1 分ごとの通過人数）、`gate_events` |
| `3_dwell` | 3 秒以上止まった区間 `[{person, state, start_s, end_s, zone}]` |
| `4_group` | `{G001: [名前, …]}` |
| `5_congestion` | `levels_per_m2`（段階の境い、既定 [0.1, 0.2] 人/m²）、`density[ゾーン]`・`level[ゾーン]`（秒ごと） |
| `6_trend` | `od_per_min`: `[{minute, origin, destination, count}]` |
| `elevator` | `waits`: `[{person, car, wait_s}]`、`events` |

## 6. `graph/`

| ファイル | 中身 |
|---|---|
| `graph.json` | `zone_graph`（`nodes`: `{id, kind: zone, x, y, area_m2}`、`edges`: 隣り合うゾーン `{source, target}`）、`grid_graph`（`cell_m` 既定 2 m の格子、`nodes`: `{id: c<番号>, kind: cell, x, y}`、`edges`）、`observed[カメラ]`（`zones`: ゾーンの床のうちカメラに映る割合、`cells`: 映る格子） |
| `zone_counts.csv` | `t, <ゾーン>…`。秒ごとのゾーンの人数 |
| `zone_flows.csv` | `minute, source, target, count`。1 分ごとのゾーン間の移動 |
| `grid_counts.npz` | `counts[秒, 格子]`（格子の順は `grid_graph.nodes`）、`t` |
| `zone_graph.graphml` | ゾーンのグラフ（networkx などで読める） |


## 7. 動画

`video/<カメラ>.mp4`: H.264、`width`×`height`、fps は正解と同じ。`render_log.json`: `{"frames": [始まり, 終わり], "cameras": {名前: 描画の秒}, "people_placed", "total_s"}`。
人ごとに服の色を変えて描く（`people.tint_index`）。描画の方式は RAY_TRACE。

## 8. 学習に使うときの例

**検出・1 台の追跡**（MOTChallenge の形を読む道具がそのまま使える）

```python
import cv2, numpy as np
gt = np.loadtxt(f"{run}/mot/CamGate.txt", delimiter=",")       # frame, id, x, y, w, h, conf, class, vis
cap = cv2.VideoCapture(f"{run}/video/CamGate.mp4")
k = 0
while (ok := cap.read())[0]:
    img = ok[1]
    rows = gt[(gt[:, 0] == k + 1) & (gt[:, 8] >= 0.4)]           # 全部を描いたとき: 動画の k コマ目 = MOT の k+1
    k += 1
```

**人物照合（ReID）の学習用の切り出し**: `mot/<カメラ>.txt` の枠を動画から切り出し、`id` を人の番号、`aicity/cameras.json` の番号をカメラの番号にする
（Market-1501 の名前の付け方なら `{id:04d}_c{camera}s1_{frame:06d}_00.jpg`）。見えている割合の低い枠は外す。

**複数カメラの追跡**: `aicity/gt.txt` を正解にする（同じ人は全カメラで同じ `obj_id`、足元の世界の座標つき）。

**軌跡の予測・グラフの学習**: `frames.csv.gz`（全員の正確な位置）か `graph/`（ゾーン・格子の人数と流れ）。カメラから見える分だけにするなら `graph.json` の `observed`。

**状態の判別（VLM など）**: `people[名前].states` を、動画の同じコマの枠（`mot`）と合わせる。

## 9. 学習に使うときの注意（今の版の限界）

- 枠は人を囲む箱を映した近似で、描かれた輪郭にぴったりではない。見えている割合も近似（深度・マスクは出していない）。検出器の学習には、描画のときに Isaac Sim の Replicator でぴったりの枠・マスク・深度を出すのが要る（未実装）。
- 人物モデルは 10 種類で、服の色を人ごとに変えて区別している。人物照合をこのデータだけで学習すると「服の色」だけで見分ける近道を覚えるおそれがある。
- ゆがみ・ノイズ・圧縮・照明の変化・カメラの時計のずれとコマ落ちは入れていない（`clock_offset_s`・`drop_rate` は記録だけ）。
- 3D の枠・姿勢（キーポイント）・顔などはない。1 つの階だけ。
- 素材の利用条件: 空間（オフィス・病院・倉庫）は CC BY 4.0（NVIDIA Isaac Sim の素材、クレジットを書く）。人物モデルの条件は未確認なので、作ったデータを外に出す前に確かめる。
  竹芝の実際の映像・図面から作ったものは、このデータの置き場所とは分ける（NDA）。

## 10. 病棟の配置と道のり（`ward_layout.json`）

`twinsim ward-layout [--space hospital]` → `<TWINSIM_DATA>/ward/hospital_ward_layout.json`。空間の `ward.yaml`（ベッドとナースステーションの置き方）から、
歩ける所の上の最短の道のりを出す。`~/digitaltwin` のワークベンチの「病棟の実施の遅れ」（`workbench/bridge/ward.py`）が看護師の歩く時間に使う。

| キー | 中身 |
|---|---|
| `space`・`source`・`note` | 空間の名前、配置の出典、説明 |
| `beds` | `[{name, ward, xy}]`。ベッドに最も近い歩ける点（病室の前の廊下） |
| `layouts` | `{置き方: {ステーション: [x, y]}}`（例 `reception`・`best1`・`best2`） |
| `points`・`names` | `{名前: [x, y]}`（ベッドの名前と `置き方:ステーション`）と、その並び |
| `dist_m` | `dist_m[i][j]` = `names[i]` から `names[j]` までの道のり（m、0.25 m の格子のダイクストラ法） |
| `paths` | `{"置き方:ステーション|ベッド": [[x, y], ...]}`。ステーションからベッドまでの最短の道の点の列（格子の道を 0.2 m の幅で間引いたもの。戻りは逆順）。ワークベンチが看護師の動きを描くのに使う |

## 11. 実データの記録の形（`twinsim calibrate` の入力）

`twinsim calibrate <元のシナリオ> --gate-log a.csv --ev-log b.csv [--ev-mode fit|replay] [--id 名前] [--out 場所]`。結果は `<TWINSIM_DATA>/calibration/<id>/scenario.yaml`・`report.json`。

| ファイル | 列 |
|---|---|
| `gate_log.csv` | `time_s, gate, lane, direction`（`in`・`out`）、任意で `person` |
| `ev_log.csv` | `time_s, car, boarded, alighted` |

時刻は 2 つの記録の早い方を 0 にそろえる。形の見本は `twinsim export-logs <結果>` で作れる。
