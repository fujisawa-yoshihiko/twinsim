#!/usr/bin/env bash
# twinsim と、いっしょに使うアプリの起動状況を見る（GUI のサーバー・Isaac Sim・GPU）。止めるのは ./stop.sh
PORT=${TWINSIM_PORT:-8770}
echo "GUI のサーバー（ポート $PORT）:"
if curl -sf -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null; then
  pid=$(ss -ltnp 2>/dev/null | grep ":$PORT " | sed -E 's/.*pid=([0-9]+).*/\1/' | head -1)
  echo "  動いている（PID $pid、起動 $(ps -o lstart= -p "$pid" 2>/dev/null)）。開く URL: ./run.sh serve --url"
else
  echo "  止まっている（起動: ./run.sh serve）"
fi
echo "Isaac Sim:"
if docker ps --format '{{.Names}}' | grep -q "isaac-sim"; then
  isim status 2>/dev/null | grep -E "枠" | sed 's/^/  /'
else
  echo "  止まっている（描画するときだけ ./isaac_up.sh <GPU>）"
fi
echo "GPU:"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null | sed 's/^/  /'
