# 作業の状態（再開用）

## 2026-11-12（1.1 の準備、ブランチ crowd-cfsm）

- 1.1 の中身は「素材 v6 と同じ人の動き」（0ecaa76 の動き。v6 の 2 件を計算し直して軌跡・`moving` が一致）に、人の動きを変えない直しを足したもの:
  CI の ruff が 5.3 から落ちていた（31ce45c）、判定の標本の少なさ（8405d76、docs/validity.md の 5.6）。リリースノートは docs/release-1.1.md
- 版の出し方を docs/architecture.md に書いた。確かめは `tools/release_check.sh`、GitHub の Releases の本文は `tools/release_notes.py`（相対リンクをタグの URL に）
- 1.0 と 1.1 の比べ: ~/dt-data/twinsim/crowd_check/release_1.1/（code_1.0 は b5c7af1 の git archive、scripts/ の sim_one.py・judge_all.py、summary.md）
- 11/12 に出した: main を 7dfe9a6 へ早送り（PR #2 も入った）、タグ v1.0.0（b5c7af1）・v1.1.0（7dfe9a6）、GitHub の Releases（1.1.0 が最新）。CI は Python 3.10・3.13 とも通った
- 次の版の目標の案は docs/roadmap.md（1.2: グループの機能・EV 以外の行動の目的になる部品・既知の制限の直し・空間を多角形から。1.3: 2 台以上のカメラ）。直しの残り: 2 人連れが横に 2〜4 m 離れる、
  混む EV の前で乗るまでの裾、混んだ待つ人の中の小さな揺れ、office ゲート前 peak の南の出口のつかえ、空間を多角形・dict から作る

## 2026-11-08（歩く人がその場で前後に揺れる、ブランチ crowd-cfsm）

- 素材 v5 の映像で、ほかの人の手前で止まった歩く人が歩く姿勢のままその場で揺れていた。決まりと結果は docs/validity.md の 5.5
  - わけ: 行き先へ引く向きと離れる向きが打ち消し合うと、和の向きが毎コマ逆になり、その向きの空きの速さ（最大 1.4 m/s）で前後に跳ねた
  - 直し: 行ったり来たりしている間は和の長さに比例して遅くする（`BALANCE_E`・`CHATTER_S`・`BACK_M_S`）、書き出す `moving` と向きは 0.3 秒でならした速さから（`OUT_TAU`。
    docs/formats.md）、扉の前で降りる人を待つ乗る人も頼まれたら横へよける
  - 揺れ（1,000 人・秒あたり）: EV の前の 3 つ 39〜46 → 3〜6、verify_bottleneck 159 → 6、素材の 6 件 2.5〜108 → 0〜11。動けなくなった人 0 のまま、ほかの判定はほぼ同じ
- テスト 175 件（足した 3 件はどれも前の版で落ちる）
- 比べの記録: ~/dt-data/twinsim/crowd_check/shake/（README.md・scripts/。前の版 v5base、記録した版は fixK7。試して使わなかった版 fixB〜fixK6）
- 残り: 混んだ待つ人の中の小さな揺れ、混んだ EV の前で乗るまで 10 秒より長い人（前の版から 8〜16%）、hospital_gate_ev の重なりと安全弁が少し増えた。
  素材の描き直し（v6）はこの版で
- 2026-11-11: 素材 v6 を描いた（~/dt-data/twinsim/corpus/2026-11-v6、6 件・失敗 0）。描いた 60 秒の揺れは 6 件の計で 761.6 → 94.9 人・秒、0.3 m 未満の組 × コマ 76 → 12。
  見比べの動画は ~/dt-data/twinsim/corpus_audit/2026-11-v6/shake_compare/、確かめの記録は ~/MOPF_ALL_video/research/video_corpus/audit/README.md の「v6」。
  GitHub に送った（11/11）

## 2026-11-07（EV を待つ人が隣と触れたまま立つ・ゲートの手前の行き先、ブランチ crowd-cfsm）

- 5.3 の版で描き直した素材（v4、~/dt-data/twinsim/corpus/2026-11-v4）を v3 と比べて見つけた 2 つ。決まりと結果は docs/validity.md の 5.4
  - EV を待つ人: よけた人は歩く人が 0.9 m より離れたら元の場所へ戻る（`HOME_CLEAR_M`）、隣の知らない立つ人と 0.45 m より近ければ空いていれば離れる。
    A_hospital_ev_mid の 0.45 m 未満 17% → 3.4%、EV の前の 3 つ（種 1〜16）で 0.5〜4.2% → 0.1〜0.4%。5.3 の確かめはこの量を比べていなかった
  - `validate`: `via` のゲートを通ったあと行き先へゲートの線をもう一度横切る設定を誤りに（素材の office のゲート前で、東の部屋へ行く 25% が
    ゲートを通ってから引き返していた。素材の設定は西の廊下へ回した。A_office_gate_peak の安全弁 55 → 16 / 3 回）
- 5.3 の「残り」の「出ていく人が列の横を抜けられない」は誤りだった（55 回のうち 25 回が上の引き返す人、28 回が南の出口のつかえ）
- テスト 172 件（足した 6 件のうち、戻る・離れるの 2 件は前の版で落ちる。ゲートの手前の行き先の 3 件は前の版にない確かめ）
- 比べの記録: ~/dt-data/twinsim/crowd_check/v4_check/README.md（見つけた経緯）、rem_seeds/wait1（種 0〜16）・home{0.9,1.5,2.5}（戻る前の距離）、
  door/{seta_v5base,seta_wait1}（A 組、直した素材の設定で）
- 残り: 混む EV の前で、EV へ向かう人が待つ人の中へ安全弁で入り中で止まる（A_hospital_ev_peak）、よける向きが歩く人の次の道になることがある、
  南の出口で現れる人と出ていく人がつかえる、到着の判定は 2σ、受付で離れて立った 2 人連れが別の廊下を通る。v5 の描き直しはこの版で

## 2026-11-06 夕方（残りを直す: 入口の順・2 本目の入る線・ゲートの列・EV の前の混雑・判定の測り方、ブランチ crowd-cfsm）

- 決まりと結果は docs/validity.md の 5.3
- 動き: 入口で待つ人を毎コマ着いた順に（グループはまとめて）、入る人の線がふさがれば出る人の線からも入る（そこを出ていく人がいないとき。`motion.entry_alt`）、
  グループの仲間は 0.4 m あけて現れ 2 人目は横の線から並んで入る、止まる所（受付など）で仲間を待つ、扉の線では横のずれなし、
  ゲートの手前で列の順が後ろの真横の人は前の人と見ない、横のずれはゆっくり戻す、合流で長く進めずにいる人に譲る、
  3 秒進めない人は前側の立つ人に道をあけてもらう（ゲートへ向かう人もゲートから遠ければ安全弁）、経路を引き直すとき歩ける所の外の部分（かごの中）を残す
- 判定: ゲートの間隔（前の人が通る前に列で止まっていた人）、到着（終わりまで外で待った人 `summary.json` の `outside_at_end` も、分散はグループの人数から）、
  自由に歩く速さ（前 2.5 m、与えた速さと比べる）、2 人連れ（列〜ゲートの後 5 秒を除く）、待つ人どうし（立つ人どうしだけ）、
  止まった人（列の人も。30 秒ずっと歩く途中だった人だけ）
- 結果: verify_gate_capacity は到着 0 → 8・2 人連れ 5 → 7・ゲートの間隔 8/8 が合う（種 1〜8）。EV の前の 3 つ（種 1〜16）で安全弁 2.8〜9.3 → 1.4〜3.2、
  重なり 0.13〜0.47 → 0.04〜0.07。A 組 27 回で止まった人 0、安全弁 105 → 95
- テスト 166 件（足した 11 件はどれも前の版で落ちることを確かめた。うち 2 件は前の版にない関数を呼ぶため）
- 比べの記録: ~/dt-data/twinsim/crowd_check/rem_seeds/（README.md・scripts/、記録した版は final2）、door/{seta_base,seta_final2}（A 組）
- 残り: 混む設定でゲートの列が廊下を埋め、出ていく人が抜けられず安全弁で通る（A_office_gate_peak 26 → 55 / 3 回。決めた量が入るようになって表に出た）、
  到着の判定は 2σ（正しい到着でも 20 に 1 つほど注意）、受付で離れて立った 2 人連れが別の廊下を通ることがある。
  v3 の映像はこの直しの前の動き（描き直すかは未定）

## 2026-11-06（扉・ゲート・EV の扉の前で止まる人をなくす、ブランチ crowd-cfsm）

- v3 の hospital EV 前 mid で、ロビーの入口から出る人が入口の角で止まった件から。決まりと結果は docs/validity.md の 5.2
  - 扉の向こう（hidden）との行き来を 2 本の線に（入る人は元の線、出る人は横 0.6 m。`Space.door_lanes`）
  - 扉の向こうへ歩く人の横の上限で一歩が消えていた（EV の扉 → かごの曲がり角の内側）のを直した。安全弁がテンプレートで 1 回あたり 21〜34 → 2〜5 回
  - 重なったら離れる（0.3 m/s）、立っている人は近すぎる人から離れる向きなら道をあけられる
  - ゲートの手前でふさぎ合ったら列の順・レーンを入れ替える（`motion.lane_swaps`）
  - 止まった人の判定: 30 秒の間に 2 m より遠くへ行って戻った人は除く
- 素材の A 組の設定 27 回で動けなくなった人 2 → 0。テスト 155 件（tests/test_crowd.py に 6 件足した。うち 3 件は前の版で落ちることを確かめた）
- 比べの記録: ~/dt-data/twinsim/crowd_check/door_final（9 テンプレート）、door_seeds/{base,new5}（種 1〜8）、door/{before,new5,...}（A 組）。前の版の基準は base_fe13077
- 残り: verify_gate_capacity の列の間隔の測り方（10 回に届かない）、混んだ入口でグループの 2 人目が外で待たされて分かれる、verify_bottleneck の重なり 0.41 → 0.44、
  自由に歩く速さの測り方。v3 の映像はこの直しの前の動き（描き直すかは未定）

## 2026-11-05（人どうしがぶつからない動き、ブランチ crowd-cfsm、ローカルだけ）

- `people.motion_model: cfsm`（既定）: Collision-Free Speed Model（Tordeux ら 2016）。前のモデルは `lane`。結果と決まりは docs/validity.md の 5.1
- 重なり（0.3 m 未満、人 × コマ 1,000 あたり）は 9 つのテンプレートすべてで減った（最大 7.47 → 0.47）。動けなくなった人 0
- 11/5 午後: 仲間の後ろはついていく間隔 0.5 秒（2 人連れ 0.84〜0.94 m で合う）、EV は 2 列で乗る（続けて乗る間隔 1.17〜1.48 秒で合う）、hospital の EV のかご（描画で置く、blocked）
- 11/5 夕: v1 の 6 件を描き直した（~/dt-data/twinsim/corpus/2026-11-v2、fc76d58、GPU 0・1 で 2.1 時間）。確かめは research/video_corpus/audit/README.md の「v2」
  そのあと列の後ろの間隔（0.65 m）と、扉の向こうから入る人が入口のふさがりで外で待つ決まりを足した（v2 の映像には入っていない）
- 11/6: 4a70311 で 6 件を描き直した（~/dt-data/twinsim/corpus/2026-11-v3、1.9 時間）。列の後ろの近さ 24% → 0.4%。確かめは research/video_corpus/audit/README.md の「v3」
- 残り: 自由に歩く速さの測り方、安全弁の重なり、hospital のロビーの入口で出る人と入る人がすれ違えない（v3 の hospital EV 前 mid で 1 人）、混んだ EV 前で 2 人連れの間隔と続けて乗る間隔が少し外れる
- 比べの道具: `tools/crowd_check.py <名前> --jobs 9`（結果は ~/dt-data/twinsim/crowd_check/）

## 2026-11-03〜04（描画を並べる・ベンチマークのための直し、ブランチ render-farm → benchmark-gt、どちらもローカルだけ）

- 描画を並べた: `tools/render_farm.sh`（画面なしの描画専用 Isaac Sim を GPU ごとに何本も）、`render(..., chunk_s=)`。同じ GPU に 8 本で撮影は 4.0 倍
- 描画から正解を出す: `render(..., labels=True)` → `labels/<カメラ>.csv`（見えている部分の枠・全身の枠・visibility・occlusion・truncation・portal。docs/formats.md の 4）
  - Replicator の bounding_box_2d_tight/loose と意味の単位の塗り分け。occlusionRatio は −1 なので、全身の画素は 30 コマごとに人だけを組ごとに描いて数える
  - 同じ Isaac Sim で 2 本目の注釈は空・誤りになる → 注釈のジョブのあとは os._exit、コンテナが起動し直す（post_quit では終わらず、受け付けが止まったまま GPU を 11 時間押さえた）
- 区間の前 3 コマを捨てる（`preroll`）、カメラの近くの人だけ置く（`cull`）
- 出入り口: spawn・exit の `hidden`、elevator の `cabin_m`、`Space.portals`。office の入口・南の出口・EV、hospital のロビーの入口に書いた（hospital の EV は USD にないので見立てのまま）
- 待つ場所が埋まったら、ほかの人から 0.6 m 離れた所まで歩いて待つ（前は着いた所に立ち、重なった）
- 作業場所とジョブの名前に結果の場所のハッシュ（同じ名前の別の版の「済み」を見誤った）
- 確かめ: ~/MOPF_ALL_video/research/video_corpus/audit/README.md（v0 の問題）と、v1 の確かめ（同じフォルダ）
- 11/4 夕の直し（aa0c866・9c43c29・1d27d21）:
  - すりガラスの奥の隠れは計算機で数える（`glass.py`、`spaces/*/glass.json`、`space.yaml` の `glass.occluding`、表の `glass` 列）。注釈の間ガラスを不透明にする方法は、Replicator が人を返さなくなって使えなかった
  - 注釈は描画と別のジョブで取る（`capture: false`）。描いたあとに同じ Isaac Sim で取ると、途中で現れた人が数百コマ抜けた
  - Replicator の名前の取り違えは、計算の枠と突き合わせて直す（`labels.fix_names`、`labels/identity.json`）
  - 空の区間があれば `finish_labels` が止まる（前の表を残す）。空の区間はたまたま出るので、取り直す側（research の relabel.py）が 3 回まで入れ直す
  - 固まった受け付けの見張り（`isaac_bridge.unstick`）。部品の写しは名前の付け替えで（書きかけの render.py を読ませた）

- 11/4 夜の直し（1d27d21・6316e02・2d16f28・bfe1f50）: 見張りの数え違い、かごのない EV の出入り口の範囲（扉の外 1 m）、
  Replicator が区間の途中で現れた人を拾わない行を `unlabeled` に（全体の 0.75%、office ゲート前 mid は 5.6%）。9c43c29 で落ちていたテスト 2 件。
  v1 の確かめの結果は ~/MOPF_ALL_video/research/video_corpus/audit/README.md の「v1」（正しく見つけた人の IoU の中央値 0.97）

### 残り（ベンチマーク）
1. Replicator の注釈が、時刻ごとの表示の切り替えに付いてこない（途中で現れた人を返さない・出番の終わった人の名前で 2 人分まとめて返す）。
   → 11/4 夜に直した: 注釈の間は表示を切り替えず、出番の外は床の 200 m 下に置く（render.py の park、既定）。2 区間で出番の外の名前の注釈 2,805・836 → 0、
   始めからいる人の枠・画素は同じ（research/video_corpus/audit/hold_test.py、~/dt-data/twinsim/corpus_qa/hold_test/）。注釈の前に全員を見せる案は悪くなった。
   11/5 に v1 の 108 区間を park で取り直した（GPU 0・1、約 75 分）。出番の外の名前の注釈 39,854 → 0、最後まで付かない人 99 → 0、始めからいる人の枠は 100 万行で変わらず（research/video_corpus/audit/park_check.py）。正解の表は 3f47572
2. 歩く人が待つ人をすり抜ける（中心 0.3 m 未満が人×コマの約 0.5%）。直すには人どうしのよけ方のモデルを入れ替える（文献との比べのやり直し）
   → 11/5 に人の動きを Collision-Free Speed Model にした（ブランチ crowd-cfsm、上の 2026-11-05、docs/validity.md の 5.1）
3. hospital の EV（USD にない。素材を足すか、場所を移す）。今は出入り口の範囲で外している
   → 11/5 に office の EV のかごと扉の枠を描画で置いた（prop: elevator、blocked、cabin_m 1.0）。見え方: ~/dt-data/twinsim/corpus_qa/hospital_ev_prop/
4. 人物モデルが 10 種類（同じ骨格で使えるのは Isaac Sim 6.1 では 10 だけ）。広角のゆがみは描画のカメラの側で
5. 注釈で 1 コマの描画が約 2〜3 倍。RGB も Replicator で同時に取れば 1 回の描画で済む（未確認）

## 2026-11-02（1.0 の最終監査）

- 動画に 1 コマ多く入る不具合を直した（`isaac_bridge.encode`）。0.x で描いた動画はそのままで、1 コマ遅れている。`office_gate_ev` の検出・追跡の値を補正して測ると IDF1 は 0.859 → 0.862、0.878 → 0.880 で、結論は変わらない。
- 計算・安全性・文書の監査で見つかった問題を直した。内容と既知の制限は [release-1.0.md](release-1.0.md)。
- 残り: Isaac Sim での通しの確認（座標の発生位置・足したカメラ・`tint: false`）、パッケージのライセンスを決める、タグ。

## 2026-11-02（JSON の設定の文書）

- `docs/config-tutorial.md`（順に学ぶ）と `docs/config-reference.md`（全部のキー）を日本語・英語で足した。
- `tests/test_docs.py` が、文書の JSON を全部計算に通し、日英の一致・リンク・キーの抜け・場所の名前を確かめる。キーを足したらリファレンスも直す。

## 2026-11-02（人の現れる場所とカメラ）

- `streams[].origin`・`meet.from` に座標（`{"xy": ..}`・`{"line": ..}`）を書けるようにした。歩ける所の外と、行き先まで歩いて行けない座標は計算の前に誤り。行き先は場所の名前のまま。
- GUI: 図の緑の四角をドラッグして現れる場所を動かす（壁の中なら近くの歩ける所へ寄せる）。現れる所の選択と座標の入力、カメラの追加と焦点距離の欄を足した。
- カメラの設定の誤り（知らないキー・eye や target の欠け・同じ名前）を計算の前に出す。
- `render.tint` は書いても効いていなかったので、効くようにした（`twinsim.render(tint=None)` で設定に従う）。
- 既存のテンプレートは、変更の前後で同じ結果（office_gate_ev ほか 4 つ、ハッシュが一致）。GUI は Playwright の Firefox で 18 項目を確かめた。座標の発生位置・足したカメラでの描画（GPU）は未確認。

## 2026-11-02（`main` をシミュレータだけにした）

- ユーザーの指示で、シミュレータだけの版を `main` にした。それまでの全部入りはブランチ `with-mopf` に残した。
- チュートリアルの例 `examples/`（01〜06）と、`twinsim.open_result`・`Result.videos`・`Result.video_frames` を足した。GPU の既定は `one-gpu` が選ぶ 1 枚。
- 全部入りから MOPF との連携（`twinsim/mopf/`）・人物照合（`reid.py`・`vendor/`）・検知の説明と報告のページを外した。人の動き・正解ラベル・描画・画面・実データでの合わせ込み・病棟の配置は残した。
- `spaces`・`templates`・`static`・`isaac` を `twinsim/` の中へ移した（pip で入れても動くように）。`Geodesic` は `space.py` へ。
- Python の入口: `twinsim.simulate` など（docs/library.md）。設定は dict・JSON の文字列・ファイル・テンプレートの名前。知らないキーは誤りにする。
- `engine.py` のよける向きが `hash()` で実行ごとに変わっていたのを `tie_side`（crc32）に直した（`with-mopf` には残っている）。`hash()` を固定すれば全部入りと全ファイル同じ結果だった（office_gate_ev、種 3 通り）。
- 下の記録は全部入りのころのもの。`twinsim/mopf/` や `docs/report/` の話は `main` にはなく、`with-mopf` にある。

## 2026-10-26（病棟の配置と道のり）

- `spaces/hospital/ward.yaml`（ベッド 8 台・ナースステーションの置き方 3 案。仮想病院の配置の比較から写した）と `twinsim ward-layout`（歩ける所の上の道のり → `~/dt-data/twinsim/ward/hospital_ward_layout.json`、形は docs/formats.md の 10）。
- 使うのは `~/digitaltwin/workbench/bridge/ward.py`（病棟の実施の遅れの試作。看護師の順番待ち × MedGym）。結果は `~/digitaltwin/workbench/README.md` の「病棟の実施の遅れ」。

## 2026-10-24（進捗の報告のページ）

- `docs/report/2026-10-24/`（日本語・英語）: 画面のキャプチャ（`tools/capture_gui.py`、playwright の Firefox）と、結果の切り出しの GIF・mp4・画像（`tools/report_media.sh`）つきの報告。
  検証の環境としての進捗の表（評価指標ごと）も載せた。
- 評価仕様の案と評価の道具は研究のフォルダ（`~/MOPF_ALL_video/research/spec/`、手元の git だけ）。twinsim の正解を状態ラベルの形に書き出す道具もそこ（`kit/from_twinsim.py`）。

## 2026-10-23 午後（2 台の間の対応の推論）

- 正解を使わずに 2 台の間をつなぐ推論（twinsim/mopf/linking.py、`./run.sh mopf-link`、画面の「2 台の間の対応の予測」）。時間・向き・服の色の LLR の和で 1 対 1 に。
  office_gate_ev: 78 組のうち 70 組、予測した組の 88% が正しい、2 台を合わせた IDF1 0.59 → 0.82。時間だけでは 5 組（人が多くて絞れない）
- 予測の番号で並べた動画（sync_pred.mp4）・予測した組の切り出し（links.png）。並べた動画の関数を、予測の番号でも描けるように広げた
- 1（速い版）: OSNet x0.25（MOPF と同じ重み、CPU 4 ms/枚）と、移動時間のずれの学習（time*）。2（精度の高い版）: CLIP-ReID ViT-B/16・OSNet x1.0、
  代表の切り出しの選び方、階層クラスタリング（hc:）。3: 見た目 4 種 × 方式の比べ（docs/integration.md の 9）。最良は 服の色＋学んだ時間＋階層クラスタリング（IDF1 0.845）、
  人物照合では OSNet x1.0 / x0.25 ＋学んだ時間＋階層クラスタリング（0.83）
- 次の候補（4）: 服の色を変えない場面を描いて確かめる（GPU 約 1.5 時間、確認を取ってから）


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
4. 実データ（ゲート・EV の記録）で合わせる（形は docs/formats.md の 11）


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
- GPU の空きを確かめる（`nvidia-smi`）→ `./isaac_up.sh`
- GUI: `python -m twinsim serve`（URL は `--url`）
