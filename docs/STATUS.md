# 作業の状態（再開用）

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
