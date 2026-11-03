# JSON の設定のリファレンス

[English](config-reference.en.md) ｜ [チュートリアル](config-tutorial.md) ｜ **リファレンス** ｜ [Python の使い方](library.md) ｜ [出力の形](formats.md)

設定に書ける全部のキーです。初めて書くときは[チュートリアル](config-tutorial.md)から読むと分かりやすいです。
YAML でも同じ形で書けます。座標は世界の座標（m、Z が上）、時間は秒です。

## 目次

| 分類 | 項目 |
|---|---|
| 全体 | [キーの一覧](#top-level)・[値の重なり方](#merge) |
| 人 | [`space`](#space)・[`people`](#people)・[`demand`](#demand) |
| 流れ | [`streams[]`](#streams)・[`origin`](#origin)・[`rate`](#rate)・[`destinations[]`](#destinations)・[`meet`](#meet) |
| 設備 | [`elevator`](#elevator)・[`schedule`](#schedule)・[`alight`](#alight)・[`gates`](#gates) |
| カメラと出力 | [`cameras[]`](#cameras)・[`render`](#render)・[`outputs`](#outputs) |
| 比較と確かめ | [`variants`](#variants)・[`validity`](#validity) |
| そのほか | [`graph` など](#others) |
| 共通 | [分布の書き方](#distributions)・[場所の名前](#places)・[計算の前の検査](#checks) |

<a id="top-level"></a>

## キーの一覧

`space` だけが必須です。ここにないキーはエラーになります。

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| [`space`](#space) | 文字列 | 必須 | 空間の名前か、空間のフォルダの場所 |
| `seed` | 整数 | `0` | 乱数の種 |
| `fps` | 正の整数 | `30` | 1 秒のコマ数 |
| `duration_s` | 数 | `120` | 計算する長さ（秒） |
| [`people`](#people) | オブジェクト | 下を参照 | 人の分布 |
| [`demand`](#demand) | オブジェクト | なし | EV を使う人の量 |
| [`streams`](#streams) | 配列 | `[]` | 人の流れ |
| [`elevator`](#elevator) | オブジェクト | なし | エレベーター |
| [`gates`](#gates) | オブジェクト | `{}` | ゲートごとの処理時間 |
| [`cameras`](#cameras) | 配列 | `[]` | カメラ |
| [`render`](#render) | オブジェクト | 下を参照 | 描画 |
| [`outputs`](#outputs) | 配列 | 全部 | 書き出すもの |
| [`variants`・`variant`](#variants) | オブジェクト・文字列 | なし | 条件の比較 |
| [`validity`](#validity) | オブジェクト | なし | 確かめの追加の判定 |
| [`graph`・`mot_stride`・`congestion_levels`](#others) | | | 出力の細かい設定 |
| [`name`・`title`・`title_en`・`description`・`calibration`](#others) | | | 名前と記録 |

<a id="merge"></a>

## 値の重なり方

値は次の順に重なり、あとのものが優先します。

1. 既定の値
2. `people.profile` の値の組
3. 設定ファイル
4. `overrides`（Python）・`--set`（コマンド）

オブジェクトはキーごとに重なります。配列と分布（`type` を持つオブジェクト）は全部置き換わります。計算に使った値の全部は `scenario_resolved.json` に書かれます。

<a id="space"></a>

## `space`

`twinsim spaces`（Python では `twinsim.list_spaces()`）で一覧が出ます。自分の空間はフォルダの場所を書きます（[自分の空間](library.md)）。付属の空間の場所の名前は[場所の名前](#places)にあります。

<a id="people"></a>

## `people`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `profile` | 文字列 | なし | 文献の値の組（下の表） |
| `speed` | [分布](#distributions) | 正規分布 1.34 ± 0.26 m/s（0.8〜1.9） | 自由に歩く速さ |
| `group_size` | [分布](#distributions) | なし（1 人） | 流れに書かないときのグループの人数 |
| `group_speed` | オブジェクト | `{"model": "moussaid2010", "slope_m_s": 0.04}` | グループの速さ。平均から 1 人増えるごとに遅くする。`{"model": "min"}` はいちばん遅い人に合わせる |
| `group_lateral_m` | 数 | `0.66` | 2 人連れの横の間隔（m） |
| `lateral_max_m` | 数 | `1.0` | 経路から横へよけられる幅（m） |
| `speed_density` | オブジェクトか `null` | `{"v0": 1.34, "gamma": 1.913, "rho_max": 5.4}` | 密度で遅くなる式（Weidmann 1993）。`null` で切る |
| `models` | `"all"` か配列 | `"all"` | 使う人物モデルの名前（`twinsim/characters.py` の 10 種類） |

`profile` の値の組:

| 名前 | 中身 |
|---|---|
| `office_commute_jp` | 日本のオフィスの朝の出勤。1 人で歩く人 82%、横の間隔 0.72 m、ゲート 中央 2.0 秒 |
| `leisure_low_density` | 余暇の人出。1 人で歩く人 46%、横の間隔 0.66 m |

書いた値は組の値より優先します。値の根拠は [validity.md](validity.md) にあります。

<a id="demand"></a>

## `demand`

`rate` と `alight.count` の `lift_demand` が使います。EV を使う人の量は、在館人数 × 割合 ÷ 5 分です（Peters ら 2011）。

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `population` | 数 | 必須 | 建物にいる人数 |
| `period` | 文字列 | `"morning"` | `morning`（入る 85%・出る 10%）か `lunch`（45%・45%） |
| `peak_pct_5min` | 数 | `12` | いちばん混む 5 分の割合（%） |
| `level` | 数 | `1.0` | 全体に掛ける倍率 |

<a id="streams"></a>

## `streams[]`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `name` | 文字列 | `origin` | 流れの名前。集計に使う。`origin` が座標なら `origin.name`、なければ `stream1` のように付く |
| [`origin`](#origin) | 文字列かオブジェクト | 必須 | 人の現れる場所 |
| [`rate`](#rate) | 数かオブジェクト | 必須 | 到着の率 |
| `group_size` | [分布](#distributions) | `people.group_size` | 一緒に現れる人数 |
| `types` | 文字列か `choice` の分布 | `"person"` | 人の種類。行き先の `types` で使う |
| [`destinations`](#destinations) | 配列 | 必須 | 行き先 |
| `start_s` | 数 | `0` | 現れ始める時刻（秒） |

<a id="origin"></a>

### `origin`

| 形 | 人の現れる所 |
|---|---|
| `"entrance"` | [場所の名前](#places) |
| `{"xy": [x, y]}` | その点 |
| `{"line": [[x0, y0], [x1, y1]]}` | 線の上のどこか（幅のある入口） |

座標の形には `name` を足せます。集計での呼び名になります。

```json
"streams": [
  {"name": "a", "origin": "entrance", "rate": 5, "destinations": ["south_exit"]},
  {"name": "b", "origin": {"xy": [-3.0, 20.0]}, "rate": 5, "destinations": ["south_exit"]},
  {"origin": {"line": [[-4.0, 20.0], [-2.0, 20.0]], "name": "north_door"}, "rate": 5, "destinations": ["south_exit"]}
]
```

座標は歩ける所の中に置きます。線は両端と途中の点を確かめます。場所の名前の種類は問いません。

<a id="rate"></a>

### `rate`

`per_min` はグループの数/分です。`unit: "persons"` を足すと人/分で数え、グループの平均の人数で割って使います（`constant`・`piecewise`）。

| 形 | 中身 |
|---|---|
| `20` | 一定の率（グループ/分） |
| `{"type": "constant", "per_min": 20}` | 同じ |
| `{"type": "piecewise", "per_min": [[0, 5], [30, 30], [60, 5]]}` | `[秒, 率]` を線でつなぐ |
| `{"type": "lift_demand", "flow": "incoming", "share": 0.9}` | [`demand`](#demand) から計算する。`flow` は `incoming`・`outgoing`・`interfloor`、`share` は既定 `1.0` |
| `{"type": "times", "times": [3, 10, 25]}` | 決めた時刻に 1 組ずつ（確かめ用） |

`times` 以外は、この率のポアソン過程で到着の時刻を引きます。`lift_demand` には `demand` のキーを足して、この流れだけ値を変えられます。

<a id="destinations"></a>

## `destinations[]`

`streams[].destinations` と `elevator.alight.destinations` の要素です。`"south_exit"` のように名前だけでも書けます。

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `to` | 文字列 | 必須 | 行き先（下の表） |
| `p` | 数 | `1.0` | 選ばれる重み |
| `types` | 配列 | なし | この行き先を選ぶ人の種類。合う行き先がなければ全部から選ぶ |
| `via` | 配列 | `[]` | 途中で通るゲートの名前。向きは位置から決まる |
| `dwell` | [分布](#distributions) | `10.0` | 止まる時間（秒） |
| `state` | 文字列 | 場所で決まる | 止まる間の状態。受付 `reception`、案内板 `sign_check`、ほかは `dwell` |
| `glance` | 数 | 止まる場所 `0`・EV `20`・待ち合わせ `45` | 止まっている間に見回す幅（度） |
| [`meet`](#meet) | オブジェクト | なし | 待ち合わせ |
| `then` | 文字列かオブジェクト | なし | 止まったあとの行き先（同じ形。`meet` は書けない） |
| `variant_p` | 文字列 | なし | [`variants`](#variants) で `p` を差し替える名前 |

`to` に書けるもの:

| 値 | 動き |
|---|---|
| `"elevator"` | EV を待って乗る。[`elevator`](#elevator) の設定が要る |
| `exit`・`spawn` の場所 | そこまで歩いて出ていく |
| `spot`・`prop` の場所 | そこまで歩いて止まる |
| 場所の名前の頭（`"reception"`） | `reception_*` のどれか |

行き先は場所の名前だけで、座標では書けません。

<a id="meet"></a>

### `meet`

先に着いた人が待ち、同行者が遅れて来ます。待つ間の状態は `companion_wait` です。

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `p` | 数 | `1.0` | 待ち合わせをする確率 |
| `delay` | [分布](#distributions) | 一様分布 8〜25 秒 | 同行者が遅れて来る時間 |
| `from` | [`origin`](#origin) と同じ形 | 流れの `origin` | 同行者の現れる場所 |
| `via` | 配列 | `[]` | 同行者が通るゲート |

<a id="elevator"></a>

## `elevator`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `cars` | 配列 | 必須 | 扉の場所の名前 |
| `capacity` | 整数 | `8` | 定員 |
| [`schedule`](#schedule) | オブジェクト | 号機ごとに 35〜60 秒の間隔 | EV の着き方 |
| [`alight`](#alight) | オブジェクト | なし | 降りる人 |
| `transfer_s` | 数 | `1.0` | 1 人の乗り降りの時間（秒） |
| `door_open_s` | 数 | `1.0` | 着いてから最初の人が動くまで（秒） |

<a id="schedule"></a>

### `schedule`

| `type` | キー | 中身 |
|---|---|---|
| `interval`（既定） | `offset`（[分布](#distributions)、既定は一様分布 3〜30 秒）、`interval`（分布、必須） | 号機ごとに、間隔の分布で着く |
| `times` | `times`（`{"EV1": [秒, ...]}`） | 決めた時刻に着く |
| `on_demand` | `travel_s`（分布、既定は一様分布 10〜40 秒）、`max_wait_s`（既定 `60`）、`dwell_s`（既定 `8`） | 待つ人がいて、`max_wait_s` 以内に着く予定がなければ呼ぶ |

コードで運行を差し替えるには `twinsim.simulate(elevator_policy=...)` を使います（[EV の運行を差し替える](library.md)）。

<a id="alight"></a>

### `alight`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `count` | [分布](#distributions) | ポアソン分布 λ = 1 | 着くたびに降りる人数。`{"type": "lift_demand", "flow": "outgoing"}` なら [`demand`](#demand) から計算する（`schedule` が `interval` か `times` のとき） |
| `types` | 文字列か `choice` の分布 | `"person"` | 人の種類 |
| [`destinations`](#destinations) | 配列 | 必須 | 行き先 |

```json
"elevator": {
  "cars": ["EV1"],
  "schedule": {"type": "times", "times": {"EV1": [10, 40]}},
  "alight": {"count": 2, "destinations": ["south_exit"]}
}
```

<a id="gates"></a>

## `gates`

キーはゲートの場所の名前です。

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `service_s` | [分布](#distributions) | `1.5`（`office_commute_jp` は対数正規 中央 2.0 秒） | 1 レーンで 1 人を通す間隔（秒） |

```json
"gates": {"gate": {"service_s": 2.5}}
```

<a id="cameras"></a>

## `cameras[]`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `name` | 文字列 | 必須 | 空間の候補の名前か、新しい名前 |
| `eye` | `[x, y, z]` | 候補の値 | カメラの位置。新しい名前なら必須。高さ `z` は空間の天井（`space.yaml` の `ceiling_m`。office 3.0 m・hospital 2.97 m・simple_room 3.99 m・warehouse 5.8 m）より低く |
| `target` | `[x, y, z]` | 候補の値 | 見る点。新しい名前なら必須 |
| `focal_mm` | 数 | 候補の値、なければ `12.0` | 焦点距離（mm） |
| `h_aperture_mm` | 数 | `20.955` | センサーの横幅（mm） |
| `width`・`height` | 整数 | `render` の値 | 画面の大きさ（画素） |
| `clock_offset_s`・`drop_rate` | 数 | なし | 時計のずれとコマ落ち。記録するだけで、動画と正解には反映しない |
| `note` | 文字列 | なし | メモ |

候補の名前に値を足すと、その値だけを上書きします。

```json
"cameras": [
  {"name": "CamGate"},
  {"name": "CamEV", "eye": [-8.0, 3.0, 2.8]},
  {"name": "MyCam", "eye": [-6.0, 6.0, 2.7], "target": [-3.0, 14.5, 0.8], "focal_mm": 10.0}
]
```

<a id="render"></a>

## `render`

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `width`・`height` | 整数 | `1280`・`720` | 画面の大きさ（画素） |
| `tint` | `"per_person"` か `false` | `"per_person"` | 人ごとに服の色を変えるか。`twinsim.render(tint=...)` の引数が優先する |
| `props` | 配列 | `[]` | 置く物（`prop` の場所の名前） |
| `gate_props` | 真偽 | `true` | ゲートの機械を置くか |

<a id="outputs"></a>

## `outputs`

| 値 | 書き出すファイル |
|---|---|
| `graph` | `graph/`（GNN 向けのグラフ） |
| `mot` | `mot/<カメラ>.txt`・`mot/ids.json`（検出と追跡の正解ラベル）。`cameras` が要る |
| `aicity` | `aicity/`（複数カメラの追跡の正解）。`mot` も要る |
| `preview` | `preview.png`（軌跡の図） |
| `validity` | `validity.json`・`validity.md`・`validity.png`（文献との比べ） |
| `ground_truth`・`frames`・`tasks` | 指定に関係なく、いつも書き出す |

`summary.json`・`ground_truth.json`・`frames.csv.gz`・`tasks.json`・`scenario_resolved.*` は常に書かれます。ファイルの形は[出力の形](formats.md)にあります。

<a id="variants"></a>

## `variants`・`variant`

`variants` は条件の名前ごとの `{名前: p}` です。`variant` で選んだ条件の値が、同じ `variant_p` を持つ行き先の `p` になります。

```json
"variant": "B",
"variants": {"A": {"sign": 0.05}, "B": {"sign": 0.30}},
"streams": [
  {
    "name": "visitors",
    "origin": "entrance",
    "rate": 10,
    "destinations": [
      {"to": "sign", "p": 0.05, "variant_p": "sign", "dwell": 5, "then": "south_exit"},
      {"to": "south_exit", "p": 0.95}
    ]
  }
]
```

<a id="validity"></a>

## `validity`

確かめのテンプレートが使う、追加の判定です。

| キー | 中身 |
|---|---|
| `speed_density` | `"judge"` で、密度ごとの速さを Weidmann の式で判定する（一方向の廊下だけ） |
| `bottleneck` | `{"x": 30.0, "y": [-0.5, 0.5], "width_m": 1.0}` の出入口を通る流れを測る |

<a id="others"></a>

## そのほか

| キー | 型 | 既定 | 中身 |
|---|---|---|---|
| `name`・`title`・`title_en`・`description` | 文字列 | なし | 名前と説明。`name` は `out_dir` を省いたときのフォルダの名前になる |
| `graph` | オブジェクト | `{"cell_m": 2.0}` | 格子のグラフの 1 辺（m） |
| `mot_stride` | 整数 | `1` | MOT の枠を何コマごとに書くか |
| `congestion_levels` | 配列 | `[0.10, 0.20]` | 混雑の段階の境い目（人/m²） |
| `calibration` | オブジェクト | なし | `twinsim calibrate` が書く、合わせ方の記録 |

<a id="distributions"></a>

## 分布の書き方

時間や人数を書く所では、数の代わりに分布を書けます。

| 形 | 中身 |
|---|---|
| `2.0` | 定数 |
| `{"type": "constant", "value": 2.0}` | 定数 |
| `{"type": "uniform", "min": 30, "max": 50}` | 一様分布 |
| `{"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9}` | 正規分布 |
| `{"type": "lognormal", "median": 20, "sigma": 0.5, "min": 3, "max": 120}` | 対数正規分布 |
| `{"type": "poisson", "lam": 1.5}` | ポアソン分布 |
| `{"type": "zero_truncated_poisson", "lam": 0.6}` | 0 を除いたポアソン分布（グループの人数） |
| `{"type": "choice", "values": {"staff": 0.7, "visitor": 0.3}}` | 重みつきの選択。`["a", "b"]` なら同じ重み |

`uniform` 以外の `min`・`max` は値を切ります。`source` に文献の名前を書くと、値の根拠の表で文献として数えます。

<a id="places"></a>

## 場所の名前

`origin`・`to`・`via`・`cars`・`props` に書く名前です。図で確かめるには `twinsim show-space <空間>` を実行します（空間のフォルダの `annotate.png`。書けないときは今のフォルダ）。真上の図のない `corridor` 系では使えません。

| 空間 | 現れる・出る | ゲート | EV | 止まる | カメラの候補 |
|---|---|---|---|---|---|
| `office` | `entrance`・`south_exit`・`west_corridor`・`east_room` | `gate` | `EV1`・`EV2` | `reception_w1`・`reception_w2`・`reception_e1`・`lounge_1`〜`3`・`sign_view`・`sign` | `CamGate`・`CamEV`・`CamLobby` |
| `hospital` | `lobby_entrance`・`west`・`hall_side`・`west_room` | | `EV` | `reception_1`・`reception_2` | `CamGate`・`CamHall` |
| `warehouse` | `dock` | | | `pick_1`〜`12`・`pack_1`〜`4`・`staging_1`・`staging_2`・`break_1` | `CamAisles`・`CamPack` |
| `simple_room` | `door_w`・`door_e` | | | `table_1`・`table_2` | `CamRoom` |
| `corridor` | `west`・`start`・`east`・`finish`・`east_narrow` | | | | |
| `corridor_door` | `west`・`east` | | | | |

オフィスの図は[チュートリアル](config-tutorial.md#origin)にあります。

<a id="checks"></a>

## 計算の前の検査

`twinsim.validate`・`twinsim validate`・`twinsim.simulate` は、計算の前に次を確かめます。誤りは全部まとめて `ValueError` で知らせます（知らない空間とテンプレートは `FileNotFoundError`）。

| 検査 | 例 |
|---|---|
| 知らないキー | 一番上のキーと、`cameras[]` のキー |
| 値の範囲 | `duration_s` が正の数、`fps` が正の整数、`seed` が整数、`mot_stride`、`graph.cell_m` が空間の格子の倍数、`outputs`・`render.tint` の値 |
| 名前 | `name` とカメラの名前は文字・数字・`_`・`-` だけ（ファイルの名前になるため） |
| 場所の名前 | `origin`・`to`・`via`・`meet.via`・`cars`・`gates` のキー・`render.props` が空間にあるか。`via` はゲートか、`cars` は EV か |
| 必須のもの | `rate`・`destinations`、`to: "elevator"` のときの `elevator` と `cars` |
| 種類の綴り | `rate` と `schedule` の `type`、`variant` が `variants` にあるか |
| 座標 | `origin`・`meet.from` の形、歩ける所の中か、線の両端も含めて行き先まで歩いて行けるか |
| カメラ | `name`、`eye`・`target` の形、同じ名前がないか、`eye` と `target` が同じ点でないか、天井より低いか（天井より上だと、映っていない人に正解の枠が付く） |
| 組み合わせ | `aicity` には `mot` が要る、`meet` は流れの一番上の行き先にだけ書ける |

次は検査しません。

- 分布の中身の誤り。計算の途中でエラーになります。
- `people`・`elevator` などの中の知らないキー。書いても無視されます。

グループの人数に 0 が出たときは 1 人にします。

---

[English](config-reference.en.md) ｜ [チュートリアル](config-tutorial.md) ｜ **リファレンス**
