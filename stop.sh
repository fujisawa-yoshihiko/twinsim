#!/usr/bin/env bash
# twinsim と、いっしょに使うアプリを止める。
#   ./stop.sh            GUI のサーバーと MOPF を止める（Isaac Sim は止めない）
#   ./stop.sh gui        GUI のサーバー（ポート 8770。TWINSIM_PORT で変える）
#   ./stop.sh mopf       MOPF（~/MOPF_ALL_video/stop_ampb.sh。GPU を空ける）
#   ./stop.sh isaac      Isaac Sim（isim down。GPU を空ける。描画の途中なら描画も止まる）
#   ./stop.sh all        上の 3 つ
# どれも、止める前に今の状態を表示する。止めたあと nvidia-smi で GPU の空きを表示する。
set -uo pipefail
PORT=${TWINSIM_PORT:-8770}
MOPF_HOME=${TWINSIM_MOPF_HOME:-$HOME/MOPF_ALL_video}
what=${1:-default}

stop_gui() {
  local pid
  pid=$(ss -ltnp 2>/dev/null | grep ":$PORT " | sed -E 's/.*pid=([0-9]+).*/\1/' | head -1)
  if [ -z "$pid" ]; then echo "GUI のサーバー: 動いていない（ポート $PORT）"; return; fi
  local parent
  parent=$(ps -o ppid= -p "$pid" | tr -d ' ')
  kill "$pid" && echo "GUI のサーバー: 止めた（PID $pid）"
  # ./run.sh（uv run）から起動したときは、親の uv も止める
  if [ -n "$parent" ] && ps -o cmd= -p "$parent" | grep -q "uv run"; then kill "$parent" 2>/dev/null; fi
}

stop_mopf() {
  if [ ! -x "$MOPF_HOME/stop_ampb.sh" ]; then echo "MOPF: $MOPF_HOME/stop_ampb.sh がない"; return; fi
  if ! docker ps --format '{{.Names}}' | grep -q "mopf"; then echo "MOPF: 動いていない"; return; fi
  (cd "$MOPF_HOME" && ./stop_ampb.sh | tail -2)
}

stop_isaac() {
  if ! command -v isim >/dev/null; then echo "Isaac Sim: isim がない"; return; fi
  if ! docker ps --format '{{.Names}}' | grep -q "isaac"; then echo "Isaac Sim: 動いていない"; return; fi
  isim down && echo "Isaac Sim: 止めた"
}

case "$what" in
  gui) stop_gui ;;
  mopf) stop_mopf ;;
  isaac) stop_isaac ;;
  all) stop_gui; stop_mopf; stop_isaac ;;
  default) stop_gui; stop_mopf ;;
  *) echo "使い方: ./stop.sh [gui|mopf|isaac|all]"; exit 2 ;;
esac
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null | sed 's/^/GPU /'
