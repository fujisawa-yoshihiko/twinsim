# 開始・停止の手順書

[English](operations.en.md)

ampb（共用の GPU サーバー）で twinsim・Isaac Sim を動かし、手元の PC のブラウザで見るための手順。2026-10-23 の版。

## 0. 決まり

- GPU（RTX PRO 6000 ×4）は他の利用者と共有。使う前に空きを確かめる（`./status.sh` か `nvidia-smi`）。検出などと同じマシンで動かすときは同じ GPU 1 枚に載せるのが既定（`one-gpu` が選ぶ。既定は GPU 3）。分けるのは必要なときだけで、2 枚まで。
- 描画など長い計算は、所要時間と GPU を決めてから始める。使い終わったら止める。
- 結果・動画は git に入れない（`~/dt-data/twinsim/` に置く）。実在の建物の映像・図面から作ったものは別の場所に置く。

## 1. 手元の PC から見る

```bash
# 手元の PC で（つないだままにする。8770 = twinsim の画面）
ssh -N -L 8770:localhost:8770 ampb
```

```bash
# ampb で: 開く URL（鍵つき）を出す。人に送らない
cd ~/twinsim-lib && ./run.sh serve --url
```

出てきた `http://localhost:8770/?token=…` を開く（2 回目からは `http://localhost:8770` だけでよい）。右上で日本語・English を切り替えられる。

## 2. 起動状況を見る

```bash
cd ~/twinsim-lib && ./status.sh     # GUI のサーバー・Isaac Sim（GPU）・GPU の空き
```

## 3. 起動と停止

| もの | 起動 | 停止 | GPU |
|---|---|---|---|
| twinsim の GUI のサーバー | `./run.sh serve`（端末を閉じても動かすなら `setsid nohup ./run.sh serve > ~/dt-data/twinsim/serve.log 2>&1 &`） | 起動した端末で `Ctrl+C`、または `./stop.sh gui` | 使わない |
| Isaac Sim（描画） | `./isaac_up.sh`（別の GPU を選ぶときは `./isaac_up.sh 2`） | `./stop.sh isaac`（= `isim down`） | 1 枚（検出などと同じ GPU） |
| 描画専用の Isaac Sim（並べて描く） | `tools/render_farm.sh up --gpu N --workers K --wait` | `tools/render_farm.sh down` | GPU 1 枚に何本も。自分の GPU は全部で 2 枚まで（[README](../README.md#parallel)）。正解の注釈（`--labels`）を出したジョブのあとは Isaac Sim が終わり、コンテナが自動で起動し直す（約 1〜2 分。同じ Isaac Sim で 2 本目の注釈は空・誤りになるため） |
| まとめて | - | `./stop.sh`（GUI）、`./stop.sh all`（Isaac Sim も） | - |

コマンドはどれもリポジトリのフォルダで実行する。

## 4. よく使う流れ

| したいこと | 手順 | 時間の目安（5 分・2 台） |
|---|---|---|
| 結果を見る | 画面の「結果」のタブで結果を選ぶ | - |
| 人の動きを計算する | 画面の「設定」で値を変えて「計算する」、または `./run.sh run office_gate_ev` | 15 秒（CPU） |
| 描画する | Isaac Sim を起動 → 画面の「いちばん混む 5 秒を試し撮り」か「全部を描画」、または `./run.sh render <結果>` | 試し撮り 2〜3 分、全部 1 台 42 分（GPU） |

`<結果>` は `~/dt-data/twinsim/runs/<結果の名前>`（例 `~/dt-data/twinsim/runs/office_gate_ev`）。

## 5. 困ったとき

| 症状 | 対処 |
|---|---|
| 画面が開かない | 手元の PC の `ssh -N -L …` が切れていないか。`./status.sh` で GUI のサーバーが動いているか |
| 「トークンが要る」と出る | ampb で `./run.sh serve --url` の URL を開き直す |
| `./run.sh serve` で「Address already in use」 | もう動いている（`./status.sh`）。作り直すなら `./stop.sh gui` してから起動 |
| 「Isaac Sim が動いていない」 | `./isaac_up.sh` で起動し、1 分ほど待ってから `./status.sh` で確かめる |
| 画面の新しい欄が出ない | GUI のサーバーが古いコードのまま。`./stop.sh gui` → `./run.sh serve` → ブラウザを読み直す |
| サーバーの記録に BrokenPipeError | ブラウザが動画を途中で閉じただけ。問題ない |

くわしくは [README.md](../README.md)（構成・出力の形・映像を作るのにかかる時間）、[library.md](library.md)（Python から使う）。
