# Python のライブラリとして使う

[English](library.en.md)

`twinsim` は `import` して呼べる。設定は JSON で渡す。GPU は要らない（描画を除く）。入れ方は [README](../README.md)。

## 最短の例

```python
import twinsim

result = twinsim.simulate("config.json", out_dir="runs/test")
print(result.summary["people"], "人")
labels = result.mot("CamGate")   # 物体検知の正解ラベル
```

ひな形はテンプレートから作れる。

```bash
twinsim template office_gate_ev --out config.json
```

```python
config = twinsim.template("office_gate_ev")   # dict で返る
config["duration_s"] = 120
result = twinsim.simulate(config, out_dir="runs/short")
```

## 関数

| 関数 | 中身 |
|---|---|
| `twinsim.simulate(config, out_dir=None, overrides=None, elevator_policy=None)` | 人の動きを計算し、正解ラベルなどを書き出して `Result` を返す。描画はしない |
| `twinsim.validate(config, overrides=None)` | 設定を確かめ、既定の値を足した dict を返す。誤りがあれば `ValueError`。計算はしない |
| `twinsim.load_config(config, overrides=None)` | `validate` と同じ（読むための名前） |
| `twinsim.template(name)` | テンプレートを dict で返す（既定の値は足さない） |
| `twinsim.list_templates()`・`twinsim.list_spaces()` | テンプレート・空間の名前の一覧 |
| `twinsim.open_result(out_dir)` | 計算済みの結果のフォルダを開いて `Result` を返す。計算し直さない |
| `twinsim.render(out_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=None)` | 計算の結果を Isaac Sim で描画して `video/<カメラ>.mp4` を作る。GPU を使う。Isaac Sim が動いていなければ `RuntimeError`。`frames` はシミュレータのコマの範囲（端を含む）、`tint=False` で服の色を変えない（`None` なら設定の `render.tint` に従う） |

`config` に渡せるもの:

| 形 | 例 |
|---|---|
| dict | `{"space": "office", "duration_s": 60, ...}` |
| JSON の文字列 | `'{"space": "office", ...}'` |
| ファイルの場所（`.json`、`.yaml`） | `"config.json"`、`pathlib.Path` |
| テンプレートの名前 | `"office_gate_ev"` |

`overrides` は設定の一部を上書きする dict。値を変えて何度も回すときに使う。

```python
for seed in range(5):
    r = twinsim.simulate("config.json", out_dir=f"runs/s{seed}", overrides={"seed": seed})
```

`out_dir` を省くと `<TWINSIM_DATA>/runs/<設定の name>` に書く（`TWINSIM_DATA` の既定は `~/.twinsim`）。同じ場所に計算し直すと、前の結果を置き換える（動画と描画の記録は `before_<日時>/` に移す）。

## Result

| 名前 | 中身 |
|---|---|
| `result.out_dir` | 結果のフォルダ |
| `result.summary` | 要約の dict（人数・EV・ゲート・状態ごとの時間・`files` など）。`summary.json` と同じ |
| `result.config` | 既定の値を足した設定の dict。`scenario_resolved.json` と同じ |
| `result.files` | 書き出したファイルの一覧 |
| `result.cameras` | 枠があるカメラの名前 |
| `result.mot(camera)` | 物体検知・追跡の正解ラベルの配列。列は `frame, id, x, y, w, h, conf, class, visibility`（frame は 1 始まり） |
| `result.frames()` | 1 コマ 1 人の行を dict で順に返す（`frame, t, person, x, y, yaw, moving, state, zone, group, type`） |
| `result.videos` | 描画した動画の dict（カメラ → mp4 の場所） |
| `result.video_first_frame` | 動画の 0 コマ目のシミュレータのコマ。一部だけ描いたときは途中から始まる |
| `result.video_frames(camera, frames=None, step=1)` | 動画のコマを順に返す: `(シミュレータのコマ, 高さ×幅×3 の RGB の配列)`。ffmpeg を使う。`frames` はシミュレータのコマの範囲（端を含む） |
| `result.ground_truth()` | `ground_truth.json`（人ごとの軌跡・状態・出来事、カメラ、EV・ゲートの出来事） |
| `result.tasks()` | `tasks.json`（場所ごとの人数・通過・滞留などの集計） |
| `result.validity()` | `validity.json`（文献との比べ）。`outputs` に `validity` があるとき |

ファイルの形は [formats.md](formats.md)。計算から動画の取得までの通しの例は [examples/](../examples/README.md)。ラベルの見えている割合が 0.4 未満の枠は、学習・評価から外すのが目安。

## 設定（JSON）

いちばん小さい例（[examples/minimal.json](../examples/minimal.json)）:

```json
{
  "name": "minimal",
  "space": "office",
  "duration_s": 60,
  "seed": 1,
  "people": {"profile": "office_commute_jp"},
  "streams": [
    {
      "name": "commuters",
      "origin": "entrance",
      "rate": {"type": "constant", "per_min": 20, "unit": "persons"},
      "destinations": [{"to": "south_exit", "via": ["gate"]}]
    }
  ],
  "cameras": [{"name": "CamGate"}, {"name": "CamEV"}],
  "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"]
}
```

| キー | 中身 |
|---|---|
| `space` | 空間の名前（`twinsim.list_spaces()`）か、自分の空間のフォルダの場所。必須 |
| `name`・`title` | 名前 |
| `seed` | 乱数の種 |
| `duration_s`・`fps` | 長さ（秒、既定 120）・1 秒のコマ数（既定 30） |
| `people` | 人の分布。`profile`（文献の値の組: `office_commute_jp`・`leisure_low_density`）、`speed` など |
| `demand` | EV を使う人の量（`population`・`period`・`peak_pct_5min`） |
| `streams` | 人の流れ（現れる場所・到着の率・行き先）。現れる場所は場所の名前か座標 |
| `elevator`・`gates` | EV の運行、ゲートの処理時間 |
| `cameras` | カメラ。空間の候補の名前か、`eye`・`target`・`focal_mm` などで自分で置く |
| `render` | 描画の大きさ（`width`・`height`）、服の色（`tint`）、置く物（`props`） |
| `outputs` | 書き出すもの（`ground_truth`・`frames`・`tasks`・`graph`・`mot`・`aicity`・`preview`・`validity`） |

書き方を順に学ぶには[チュートリアル](config-tutorial.md)、全部のキーと分布の書き方は[リファレンス](config-reference.md)。文献の値の組は [validity.md](validity.md)。

物体検知の正解ラベルを出すには、`cameras` にカメラを書き、`outputs` に `mot` を入れる。

### 人の現れる場所とカメラの位置を変える

人の現れる場所（`streams[].origin`）は、場所の名前のほかに座標で書ける。座標は世界の座標（m）。

```json
"streams": [
  {"name": "a", "origin": "entrance", "rate": 5, "destinations": ["south_exit"]},
  {"name": "b", "origin": {"xy": [-3.0, 20.0]}, "rate": 5, "destinations": ["south_exit"]},
  {"name": "c", "origin": {"line": [[-4.0, 20.0], [-2.0, 20.0]], "name": "north_door"}, "rate": 5, "destinations": ["south_exit"]}
]
```

| 書き方 | 人の現れる所 |
|---|---|
| `"entrance"` | 空間の場所（`twinsim show-space <空間>` の図や、GUI の図で確かめる。真上の図のない `corridor` 系では使えない） |
| `{"xy": [x, y]}` | その点 |
| `{"line": [[x0, y0], [x1, y1]]}` | 線の上のどこか（幅のある入口） |

`name` を足すと、集計（`flow`・`od_per_min`）での呼び名になる。書かなければ流れの名前を使う。歩ける所の外の座標や、行き先まで歩いて行けない座標は、計算の前に `ValueError` になる（近くの歩ける所も表示する）。待ち合わせの `meet.from` も同じ形で書ける。行き先は場所の名前だけで、座標では書けない。

カメラ（`cameras[]`）は、候補の名前に値を足すと、その値だけを上書きする。新しい名前なら `eye` と `target` が必須。

```json
"cameras": [
  {"name": "CamGate", "eye": [-1.0, 8.0, 3.0]},
  {"name": "MyCam", "eye": [-6.0, 6.0, 2.7], "target": [-3.0, 14.5, 0.8], "focal_mm": 10.0}
]
```

通しの例は [examples/07_move_origin_and_camera.py](../examples/07_move_origin_and_camera.py)。

### GUI との対応

GUI の設定は、この JSON を編集している。「詳しい設定」の欄に同じ JSON が出て、「設定を書き出す」でファイルにできる。GUI で変えられるものは、全部 JSON で書ける。

| GUI の欄 | JSON のキー |
|---|---|
| 長さ・乱数の種 | `duration_s`・`seed` |
| 文献の値の組 | `people.profile` |
| 建物にいる人数・時間帯・混む 5 分の割合 | `demand.population`・`period`・`peak_pct_5min` |
| 人の流れ: 現れる所 | `streams[].origin` |
| 人の流れ: 到着・まとまりの λ | `streams[].rate`・`group_size` |
| 人の流れ: 行き先の重み | `streams[].destinations[].p` |
| エレベーター: 着く間隔・定員・降りる人 | `elevator.schedule.interval`・`capacity`・`alight.count` |
| ゲート | `gates.<名前>.service_s` |
| カメラ: 使う・位置・見る点・焦点距離 | `cameras[]` の `name`・`eye`・`target`・`focal_mm` |
| 置く物 | `render.props` |

設定ではない操作は、コードの関数に当たる。

| GUI の操作 | コード |
|---|---|
| テンプレートを選ぶ | `twinsim.template(name)` |
| 計算する | `twinsim.simulate(config)` |
| 全部を描画 | `twinsim.render(out_dir)` |
| いちばん混む 5 秒を試し撮り | `twinsim.render(out_dir, frames=(a, b))`。区間の探し方は [examples/04_get_video.py](../examples/04_get_video.py) |

JSON だけで書けるもの（GUI では「詳しい設定」の欄で書く）: 空間（`space`）、`fps`、歩く速さなどの分布（`people`）、流れと行き先の追加・削除、経由するゲート（`via`）、止まる時間（`dwell`）、次の行き先（`then`）、待ち合わせ（`meet`）、EV の運行の方式（`schedule`）と乗り降りの時間、出力（`outputs`）、A/B の比較（`variants`）、描画の大きさと服の色（`render`）、カメラの画面の大きさ（`width`・`height`）、グラフ（`graph`）など。

### 誤りの知らせ方

綴りの誤りを既定の値のまま黙って動かさないように、知らないキーは誤りにする。

```python
>>> twinsim.validate({"space": "office", "duraton_s": 60})
ValueError: シナリオの誤り:
  知らないキー duraton_s（使えるのは ...）
```

行き先・ゲート・カメラの名前が空間にないとき、`duration_s` が正の数でないとき、`outputs` に知らない名前があるときも `ValueError`。JSON の書き方の誤りは行と文字の位置を出す。

## 同じ結果になること

同じ設定・同じ `seed` なら、実行のたびに同じ結果になる。`result.config` か `scenario_resolved.json` を残せば、あとから同じ計算ができる。

```python
again = twinsim.simulate(result.out_dir / "scenario_resolved.json", out_dir="runs/again")
```

## 自分の空間

`space` にフォルダの場所を書くか、環境変数 `TWINSIM_SPACES` の場所に置いて名前で呼ぶ。フォルダには `space.yaml` か `space.json` と、歩ける所の地図を置く。形は [spec.md](spec.md) の 1 節、USD から作る手順は `twinsim export-space`。

## EV の運行を差し替える

`elevator_policy(sim, t)` は毎秒呼ばれる。`car.arrivals` に着く時刻を足すと、EV がその時刻に着く。配車の最適化を試すときに使う。

```python
def policy(sim, t):
    if sim.queue and not any(x >= t for c in sim.cars for x in c.arrivals):   # 待つ人がいて、着く予定がなければ呼ぶ
        sim.cars[0].arrivals.append(round(t + 10.0, 2))

result = twinsim.simulate("config.json", out_dir="runs/ev", elevator_policy=policy)
```

## 環境変数

| 名前 | 中身 |
|---|---|
| `TWINSIM_DATA` | 結果の既定の置き場所（既定 `~/.twinsim`） |
| `TWINSIM_SPACES` | 自分の空間の置き場所（付属の空間より先に探す） |
| `TWINSIM_ISAAC_WORK` | Isaac Sim との受け渡しの場所（既定 `~/isaac-sim-work/twinsim`） |
| `TWINSIM_TOKEN_FILE` | GUI のトークンのファイル（既定 `~/.config/twinsim/token`） |
