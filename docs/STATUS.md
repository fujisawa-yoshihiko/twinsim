# 作業の状態（再開用）

## 2026-10-22 10:40 一時停止（他の利用者の計算が始まったため）

動いているもの: なし（Isaac Sim・MOPF のコンテナなし、裏で動くスクリプトなし）。

### できていること（commit 済み、v0.1）
- 人の動きの計算（CPU）・空間 office・テンプレート 4 つ・正解／集計／グラフ／MOT／確認の図・`check`・試験（`pytest -q tests`、3 件）
- Isaac Sim の部品（`isaac/render.py`・`isaac/export_space.py`・`isaac/agent_runner.py`）と `twinsim/isaac_bridge.py`。**まだ一度も Isaac Sim で動かしていない**

### 途中（この commit で入れたもの）
- `twinsim/mopf.py`: MOPF の人流モニターの設定を自動で作る（office_gate_ev の CamEV・CamGate で作れた。MOPF に送る `--apply` は未確認）
- `twinsim/server.py`: GUI と REST API のサーバー（未試験）。**画面（`static/index.html`・`app.js`・`style.css`）はまだない**

### 再開の手順
1. GPU の空きを確かめる: `nvidia-smi`（他の利用者の計算がないこと）
2. Isaac Sim を twinsim の受け付けで起動（VNC は今のドライバーで作れないので WebRTC 方式）:
   `isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"`
   （その前に `cd ~/twinsim && uv run --no-project --with numpy --with scipy --with pyyaml --with pillow python -c "from twinsim import isaac_bridge as b; b.sync()"` で部品を作業場所に写す）
3. 試し撮り（5 秒・2 台、数分）: `python -m twinsim render ~/dt-data/twinsim/runs/office_gate_ev --frames 3000 3149`
   → `~/dt-data/twinsim/runs/office_gate_ev/video/*.mp4` を見て、人物・服の色・カメラの向きを確かめる
4. 空間を増やす: `export-space` で Hospital・Simple_Room・倉庫（Isaac Sim 付属）の材料を作り、意味の地図を描く
5. GUI の画面を書いて、`python -m twinsim serve` で確かめる
6. 本番の描画（5 分・2 台で 1.5〜2 時間）は、所要時間と GPU を示して確認を取ってから
