# 作業の状態（再開用）

## 2026-10-23（画面からの操作・保守性・GitHub）

動いているもの: GUI のサーバー（ポート 8770、こちらで起動、setsid）。MOPF は止めた。GPU 2 の Isaac Sim は藤澤さんが起動したもの（描画は終わっている）。

- 画面: 結果のダウンロード（ファイル・zip）、MOPF のタブ（GPU を選んで起動・ライブ・停止、ライブの映像と集計を正解と並べる）、床に写した図、重ねた動画を作るボタン
- 保守性: pyproject（`./run.sh` は `uv run twinsim`）、config.py（置き場所・接続先）、MOPF 連携を twinsim/mopf/ に分割、ruff、読み込みのテスト、CI、docs/architecture.md
- GitHub: 非公開の fujisawa-yoshihiko/twinsim に送った
- 複数カメラをまたぐ追跡: MOPF にはない。2 台を時刻でそろえた動画と、同じ人の各カメラの ID の対応表を作った（mopf-sync、画面の「2 台を時刻で並べる」）。
  研究の試作（research/multicam）の自動のつなぎを twinsim の結果で評価するのが次の候補


## 2026-10-22 深夜（残りと、ほかのアプリとの連携）

動いているもの: なし（MOPF は B の最後に止めた）。ポート 8770 の GUI のサーバー（17:23 起動、古いコード）と GPU 2 の Isaac Sim（17:30 起動）は藤澤さんが起動したもの。

### できたこと
- エンジン: ゲートの列の間隔 0.65 m（混んだ列で 0.45 m 未満 8.5% → 2.6%）、同じ向きに追いついたときの体の重なりを防ぐ（MIN_SEP 0.35 m）
- 確かめ: すれ違い（verify_counterflow、動けなくなる人 0）、幅 1 m の出入口（verify_bottleneck、2.32 人/(m·s)、実験 1.90〜2.19）、
  「詰まって動けなくなった人」「出入口を通れる量」の判定
- 実データで合わせる: export-logs（ゲート・EV の記録の形）と calibrate（出典つきのシナリオ、台帳で「実データ」）。往復で元の値に戻ることを確かめた
- MOPF との連携（twinsim/mopf_link.py、docs/integration.md）: mopf-process（動画を MOPF で検出・追跡）、mopf-eval（MOTA・IDF1・人数・足元のずれ、
  中間層のグラフ mopf_graph/）、人流モニターで数えるはずの値（expected.json）。正解から作った追跡で確かめた。GUI と REST API にも
- 研究のコード: research/sim-cctv/cctv_eval_lib.py が SIM_DATASET=twinsim で読める（MOPF_ALL_video の手元の git に記録）
- AI City の形（aicity/gt.txt）
- 試したが入れなかったもの: 追い越しを強める・遅い人のときだけにする（廊下の速さは変わらず、ゲートの列の近くで詰まりを生んだ）

- A（藤澤さんの確認のうえ、GPU 3）: 試し撮り（5 秒 × 2 台）を MOPF で処理して比べた（CamGate MOTA 0.95・IDF1 0.97、CamEV 0.91・0.92）。
  人流モニターにゲートのカメラの動画を流し、設定を送って数えた（線は正解と一致、エリアは 6 割）。docs/integration.md の 2・3
- B（夜間）のスクリプト: tools/night_b.sh（描画 約 1 時間 → MOPF → 比べる → MOPF を止める）

- B（2026-10-22 夜〜23 朝）: office_gate_ev を 5 分 × 2 台で描き（Isaac Sim、GPU 2、89 分）、MOPF（GPU 3）で処理して比べた
  （CamGate MOTA 0.87・IDF1 0.86、CamEV 0.90・0.88、ID の切り替わり 各 29、ゲートの入館を 3 割数えもらす）。docs/integration.md の 2。
  描画のあと前のセッションの終わりでスクリプトが止まったので、--resume を足して続きから回した。MOPF は止めた（GPU 3 は空き）

- 見て確かめる: mopf-overlay（正解と MOPF の枠を重ねた動画・数えもらしの場面の画像）。入館の数えもらしの原因は線の場所（扉の陰から現れた時点で
  線を越えている）で、線を 1 m 内側にずらす既定にした（数えられる割合 72% → 91%）

### 残り
1. ID の切り替わり（5 分で各 29 回）の場面を見て、追跡の方式・人物照合のモデルを比べる
2. 一周のつなぎ（MOPF → 最適化（MOPF_OPT）→ EV の運行 → twinsim）、イベントを外から指示する API
3. 0.25〜1 人/m² で文献より 0.1 m/s 遅い、ボトルネックの手前の押し合い（体が重なる）、曲がり角・階段の確かめ
4. 実データ（ゲート・EV の記録）を東急不動産から（形は docs/integration.md の 7）


## 2026-10-22 夜（人の分布を文献から）

動いているもの: なし（こちらで起動したものは止めた）。ポート 8770 の GUI のサーバー（17:23 起動）と GPU 2 の Isaac Sim（17:30 起動）は藤澤さんが起動したもの。

### できたこと
- 文献に基づく人の分布（`twinsim/literature.py`）: 出典つきの値と、組（`people.profile`: `office_commute_jp`・`leisure_low_density`）、
  建物の人数からの EV の利用者（`demand` と `rate: {type: lift_demand}`、Peters ら 2011）。到着の率の単位（`unit: persons`）
- エンジン: 速さと密度（Weidmann 1993）、前の人についていく（Seyfried ら 2005）、追い越し、グループの速さ（Moussaïd ら 2010）とまとまり、
  2 人連れの間隔（Zanlungo ら 2017）、EV に 1 人ずつ乗り降り（1.0 秒）、ゲートの時間の分布、列を来た道に沿って並べる、入口がふさがっていたら外で待つ
- 確かめ（`twinsim/validity.py`）: 計算ごとに validity.json・md・png（入力の再現・出てくる量・根拠の台帳）。確かめ用の廊下（`spaces/corridor`）と `verify_*` の 4 つ
- GUI: 「人の分布（文献）」の欄（組・建物の人数・時間帯・混む 5 分の割合）、結果に validity.png。`/api/profiles`
- 全テンプレートを計算し直した（前の試し撮りの動画は合わなくなったので video_before_* に移した）。テスト 9 件が通る
- 文書: docs/validity.md（文献の値の一覧・使い方・確かめの基準と結果・仮の値と合わせ方・限界）、spec.md の 2・3・5・9・10

### 残り（人の分布）
1. 実データで合わせる: 在館人数・ゲートの通過記録（到着の時間帯の形・ゲートの時間）・EV の運行記録（間隔）
2. 0.25〜1 人/m² で文献より 0.1 m/s 遅い（追い越しが簡単）。長い列で待つ人どうしが近づきすぎる
3. 双方向の流れ・曲がり角などの RiMEA の他のテストケース、背の高さの分布


## 2026-10-22 夕（v0.2）

動いているもの: なし（Isaac Sim は止めた。GUI のサーバーも止めた）。

### できたこと
- Isaac Sim での描画を確かめた（オフィス・病院・倉庫の 5 秒の試し撮り。動画は ~/dt-data/twinsim/runs/<名前>/video/）。ゲートの機械を置く・前回の画像が混ざらない・床の高さと照明を空間ごとに
- 空間を 5 つに（office・hospital・warehouse は使える、simple_room は計算だけ、warehouse_small は材料だけ）。`export-space`・`show-space`・`probe_bounds`・`probe_view`
- テンプレート 7 つ（hospital_gate_ev・warehouse_picking・simple_room_smoke を足した）
- GUI と REST API（`python -m twinsim serve`）。Playwright で画面を確かめた（`tools/gui_shot.py`）

### 残り
1. 本番の描画（5 分・2 台。オフィス約 1 時間、倉庫約 2.6 時間、病院約 4.5 時間の目安）は、所要時間と GPU を示して確認を取ってから
2. 小部屋の描画が真っ暗な原因（部屋の中のカメラ）
3. 小さい倉庫の意味の地図、病院の部屋の扉を開けた歩ける所（export のときに扉を隠す）
4. EV の扉の開閉、カメラの時計のずれ・コマ落ちを動画と正解に反映、見えている割合を描画の深度から
5. 歩き方のモデルの改善（速さと密度の関係・RiMEA のテストケース）、MOPF への設定の送信（--apply）の確認、画面からの USD のアップロード

### 再開の手順
- GPU の空きを確かめる（`nvidia-smi`）→ `isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"`
- GUI: `python -m twinsim serve`（URL は `--url`）
