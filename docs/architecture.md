# 構成（開発する人向け）

[English](architecture.en.md)

## データの流れ

```
templates/*.yaml ──→ scenario.load_scenario（既定 → 文献の組 literature.PROFILES → シナリオ → overrides）
spaces/<名前>/   ──→ space.load_space（歩ける所の格子・意味の地図・経路 A*）
                         │
                         ▼
                 scenario.Builder ──→ engine.Sim（1 コマずつ: 歩く・よける・列・EV・グループ）  ← CPU
                         │
                         ▼
                 outputs.write_all（正解・集計・グラフ・枠・AI City・確認の図）→ validity.evaluate（文献との比べ）
                         │                                                   ~/dt-data/twinsim/runs/<名前>/
                         ├─→ isaac_bridge.render（Isaac Sim に頼む → mp4）                          ← GPU
                         ├─→ mopf.process（MOPF で検出・追跡）→ mopf.evaluate・graph・floormap・crossings・overlay  ← GPU（MOPF）/ CPU
                         └─→ calibrate（ゲート・EV の記録 → 出典つきのシナリオ）
```

## モジュール

| 場所 | 役割 | 主な入口 |
|---|---|---|
| `twinsim/config.py` | 置き場所と接続先（環境変数で変える） | `RUNS`・`MOPF_URL`・`ISAAC_WORK` |
| `twinsim/space.py` | 空間（格子・ゾーン・場所・経路） | `load_space`・`Space.route` |
| `twinsim/dists.py` | 分布の書き方と、引く・平均・到着の時刻 | `sample`・`mean`・`arrival_times` |
| `twinsim/literature.py` | 文献の値・出典・文献の組 | `REFS`・`PROFILES`・`weidmann_speed` |
| `twinsim/scenario.py` | シナリオを読み、人の発生・行き先・EV・ゲートを組み立てる | `load_scenario`・`build`・`resolve_rate` |
| `twinsim/engine.py` | 人の動き（段取り・速さと密度・ついていく・追い越し・グループ・列・EV） | `Sim.run` |
| `twinsim/outputs.py` | 正解・集計・グラフ・MOT・AI City・確認の図 | `write_all` |
| `twinsim/validity.py`・`quality.py` | 文献との比べ・台帳／壁・近さの確かめ | `evaluate`・`check` |
| `twinsim/calibrate.py` | 実データで合わせる・記録の形に書き出す | `calibrate`・`export_logs` |
| `twinsim/camera.py` | カメラ（USD の行列）・枠・見えている割合・床への写し | `Camera` |
| `twinsim/isaac_bridge.py`・`isaac/` | Isaac Sim での描画・空間の材料（Isaac Sim の中で動くのは `isaac/`） | `render`・`finish_render`・`export_space` |
| `twinsim/mopf/` | MOPF との連携（`__init__.py` に一覧） | `process`・`evaluate`・`graph`・`floormap`・`overlay`・`identities`・`link`・`control` |
| `twinsim/api.py`・`__main__.py` | Python の入口・コマンド（`twinsim <サブコマンド>`） | `api.run` |
| `twinsim/server.py`・`static/` | GUI と REST API（`app.js`: 設定・結果、`mopf.js`: MOPF のタブ、`i18n.js`: 日本語・English の切り替え。画面の文字は `tr("日本語", "English")` と、HTML の `data-en`。テンプレート・空間・文献の組の英語は `title_en`・`license_en`・`note_en`・`notes_en`） | `serve` |

## 開発の手順

```bash
cd ~/twinsim
uv run --group dev ruff check          # 書き方（設定は pyproject.toml）
uv run --group dev pytest -q           # 動作確認（CPU、十数秒）。分割・名前の変更の取りこぼしは tests/test_imports.py が見つける
uv run --group gui-test python tools/gui_shot.py [出力] [ポート]   # 画面の確かめ（サーバーを起動してから）
```

- 依存は `pyproject.toml`（`uv.lock` で固定）。`./run.sh` は `uv run twinsim`。
- GitHub（非公開 `fujisawa-yoshihiko/twinsim`）に送ると、`.github/workflows/ci.yml` が ruff と pytest を回す（GPU は使わない）。
- 決まり（GPU の使い方・データを git に入れない・NDA）は `CLAUDE.md`。
