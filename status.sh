#!/usr/bin/env bash
# twinsim と、いっしょに使うアプリの起動状況を見る（GUI のサーバー・MOPF・Isaac Sim・GPU）。止めるのは ./stop.sh
PORT=${TWINSIM_PORT:-8770}
echo "GUI のサーバー（ポート $PORT）:"
if curl -sf -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null; then
  pid=$(ss -ltnp 2>/dev/null | grep ":$PORT " | sed -E 's/.*pid=([0-9]+).*/\1/' | head -1)
  echo "  動いている（PID $pid、起動 $(ps -o lstart= -p "$pid" 2>/dev/null)）。開く URL: ./run.sh serve --url"
else
  echo "  止まっている（起動: ./run.sh serve）"
fi
echo "MOPF:"
if docker ps --format '{{.Names}}' | grep -q "mopf_video-cv-app"; then
  live=$(curl -sf -m 3 http://127.0.0.1:8010/api/live/summary | python3 -c "import json,sys; s=json.load(sys.stdin); print(s.get('status'))" 2>/dev/null)
  gpu=$(docker inspect mopf_video-cv-app-1 --format '{{range .HostConfig.DeviceRequests}}{{join .DeviceIDs ","}}{{end}}' 2>/dev/null)
  [ -z "$gpu" ] && gpu=$(docker inspect mopf_video-cv-app-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^NVIDIA_VISIBLE_DEVICES=//p' | cut -d, -f1)   # 2 番目は VLM の逃がし先
  started=$(date -d "$(docker inspect mopf_video-cv-app-1 --format '{{.State.StartedAt}}')" '+%m/%d %H:%M')
  echo "  動いている（GPU ${gpu:-不明}、ライブ: ${live:-不明}、起動 $started）。画面: http://localhost:5174"
else
  echo "  止まっている（GUI の「MOPF」のタブから起動できる）"
fi
echo "Isaac Sim:"
if docker ps --format '{{.Names}}' | grep -q "isaac-sim"; then
  isim status 2>/dev/null | grep -E "枠" | sed 's/^/  /'
else
  echo "  止まっている（描画するときだけ ./isaac_up.sh）"
fi
echo "GPU:"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null | sed 's/^/  /'
