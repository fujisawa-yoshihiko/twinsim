# 構成（開発する人向け）

[English](architecture.en.md)

## データの流れ

```
JSON・dict・テンプレート ──→ scenario.load_scenario（既定 → 文献の組 literature.PROFILES → シナリオ → overrides）
twinsim/spaces/<名前>/ ──→ space.load_space（歩ける所の格子・意味の地図・経路 A*）
                         │
                         ▼
                 scenario.Builder ──→ engine.Sim（1 コマずつ: 歩く・よける・列・EV・グループ）  ← CPU
                         │
                         ▼
                 outputs.write_all（正解・集計・グラフ・枠・AI City・確認の図）→ validity.evaluate（文献との比べ）
                         │                                                   <TWINSIM_DATA>/runs/<名前>/
                         ├─→ isaac_bridge.render（Isaac Sim に頼む → mp4）                          ← GPU
                         └─→ calibrate（ゲート・EV の記録 → 出典つきのシナリオ）
```

## モジュール

| 場所 | 役割 | 主な入口 |
|---|---|---|
| `twinsim/config.py` | 置き場所と接続先（環境変数で変える） | `RUNS`・`USER_SPACES`・`ISAAC_WORK` |
| `twinsim/space.py` | 空間（格子・ゾーン・場所・経路） | `load_space`・`Space.route` |
| `twinsim/dists.py` | 分布の書き方と、引く・平均・到着の時刻 | `sample`・`mean`・`arrival_times` |
| `twinsim/literature.py` | 文献の値・出典・文献の組 | `REFS`・`PROFILES`・`weidmann_speed` |
| `twinsim/scenario.py` | シナリオを読み、人の発生・行き先・EV・ゲートを組み立てる | `load_scenario`・`build`・`resolve_rate` |
| `twinsim/engine.py` | 人の動き（段取り・速さと密度・ついていく・追い越し・グループ・列・EV） | `Sim.run` |
| `twinsim/outputs.py` | 正解・集計・グラフ・MOT・AI City・確認の図 | `write_all` |
| `twinsim/validity.py`・`quality.py` | 文献との比べ・台帳／壁・近さの確かめ | `evaluate`・`check` |
| `twinsim/calibrate.py` | 実データで合わせる・記録の形に書き出す | `calibrate`・`export_logs` |
| `twinsim/camera.py` | カメラ（USD の行列）・枠・見えている割合・床への写し | `Camera` |
| `twinsim/isaac_bridge.py`・`twinsim/isaac/` | Isaac Sim での描画・空間の材料（Isaac Sim の中で動くのは `twinsim/isaac/`） | `render`・`finish_render`・`export_space` |
| `twinsim/api.py`・`__init__.py`・`__main__.py` | Python の入口（[library.md](library.md)）・コマンド（`twinsim <サブコマンド>`） | `simulate`・`Result`・`run` |
| `twinsim/server.py`・`twinsim/static/` | GUI と REST API（`app.js`: 設定・結果、`i18n.js`: 日本語・English の切り替え。画面の文字は `tr("日本語", "English")` と、HTML の `data-en`。テンプレート・空間・文献の組の英語は `title_en`・`license_en`・`note_en`・`notes_en`） | `serve` |

## 開発の手順

```bash
cd ~/twinsim-lib
uv run --group dev ruff check          # 書き方（設定は pyproject.toml）
uv run --group dev pytest -q           # 動作確認（CPU、5 分ほど）。分割・名前の変更の取りこぼしは tests/test_imports.py が見つける
uv run --group gui-test python tools/gui_shot.py [出力] [ポート]   # 画面の確かめ（サーバーを起動してから）
```

- 依存は `pyproject.toml`（`uv.lock` で固定）。`./run.sh` は `uv run twinsim`。
- GitHub（非公開 `fujisawa-yoshihiko/twinsim`）に送ると、`.github/workflows/ci.yml` が ruff と pytest を回す（GPU は使わない）。
- 決まり（GPU の使い方・データを git に入れない）は `CLAUDE.md`。

## 版の出し方

- 版の番号は `pyproject.toml` と `twinsim/__init__.py` の `X.Y.Z`。人の動き・出力の形・既定の値が変わる版は Y を上げ、直しだけの版は Z を上げる。
- 版ごとにリリースノート `docs/release-X.Y.md` と英語版 `docs/release-X.Y.en.md` を書く（Z の版は同じファイルに節を足す）。書くこと:
  1. 入っているもの（実装・変更。docs/validity.md などの節へのリンク）
  2. 前の版との違い（同じ設定と種で結果が変わるか、前の版の設定が読めるか、出力の形）
  3. 確かめたこと（下の確かめの結果、前の版との比べ、描画した素材の確かめ）
  4. 既知の制限
- 確かめ:
  - `tools/release_check.sh`: ruff・pytest、wheel をきれいな環境（Python 3.10・3.13）に入れて動かし、同じ設定と種で正解が同じか、秘密の情報（detect-secrets）、依存パッケージの脆弱性（pip-audit）
  - 前の版との比べ: 前の版のコードを `git archive` で取り出し、テンプレート 9 種（`verify_*` は種 0〜8、EV の前の 3 つは種 1〜16）を両方で計算して、今の判定で比べる
    （揺れ・動けなくなった人・重なり・判定ごとの「合う」の回数）。結果はデータの置き場所（`~/dt-data/twinsim/crowd_check/release_X.Y/`）に置き、リリースノートに表を写す
  - 特定の企業・建物の名前が文書・コード・記録のメッセージにないこと
- 出す: GitHub の CI が通ったら `main` に入れ、タグ `vX.Y.Z` を付け、GitHub の Releases に載せる
  （`uv run python tools/release_notes.py X.Y.Z > 本文.md` で相対リンクをタグの URL に直してから、`gh release create vX.Y.Z --title "twinsim X.Y.Z" --notes-file 本文.md`。英語版は本文の最初のリンクから）。
  入れるときは `pip install "git+https://github.com/fujisawa-yoshihiko/twinsim.git@vX.Y.Z"` で版を選べる。
