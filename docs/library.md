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
| `twinsim.render(out_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=True)` | 計算の結果を Isaac Sim で描画する。GPU を使う。Isaac Sim の受け付けが動いているとき。`tint=False` で服の色を変えない |

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

`out_dir` を省くと `<TWINSIM_DATA>/runs/<設定の name>` に書く（`TWINSIM_DATA` の既定は `~/.twinsim`）。同じ場所に書き直すと上書きする。

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
| `result.ground_truth()` | `ground_truth.json`（人ごとの軌跡・状態・出来事、カメラ、EV・ゲートの出来事） |
| `result.tasks()` | `tasks.json`（場所ごとの人数・通過・滞留などの集計） |
| `result.validity()` | `validity.json`（文献との比べ）。`outputs` に `validity` があるとき |

ファイルの形は [formats.md](formats.md)。ラベルの見えている割合が 0.4 未満の枠は、学習・評価から外すのが目安。

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
| `streams` | 人の流れ（現れる場所・到着の率・行き先） |
| `elevator`・`gates` | EV の運行、ゲートの処理時間 |
| `cameras` | カメラ。空間の候補の名前か、`eye`・`target`・`focal_mm` などで自分で置く |
| `outputs` | 書き出すもの（`ground_truth`・`frames`・`tasks`・`graph`・`mot`・`aicity`・`preview`・`validity`） |

全部の項目と分布の書き方は [spec.md](spec.md) の 2〜3 節。文献の値の組は [validity.md](validity.md)。

物体検知の正解ラベルを出すには、`cameras` にカメラを書き、`outputs` に `mot` を入れる。

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
