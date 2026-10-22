#!/usr/bin/env bash
# B（夜間）: 計算の結果を全部の長さで描き（Isaac Sim。./isaac_up.sh で起動した GPU）、MOPF（既定 GPU 3）で検出・追跡して正解と比べる。
#   tools/night_b.sh [結果の場所（既定 ~/dt-data/twinsim/runs/office_gate_ev）]
#   目安（office_gate_ev、5 分 × 2 台）: 描画 約 1 時間、MOPF 数分。終わったら MOPF を止める（Isaac Sim は止めない）。
#   記録: <結果の場所>/night_b.log。結果: video/・mopf_tracks/・mopf_eval/・mopf_graph/
set -uo pipefail
RUN=$(readlink -f "${1:-$HOME/dt-data/twinsim/runs/office_gate_ev}")
MOPF_GPU=${MOPF_GPU:-3}
TS=$HOME/twinsim
MOPF=$HOME/MOPF_ALL_video
LOG=$RUN/night_b.log
exec > >(tee -a "$LOG") 2>&1
echo "=== night_b $(date '+%F %T') $RUN"
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader

cd "$TS" || exit 1
if ! uv run --no-project --with numpy --with scipy --with pyyaml --with pillow python -c \
    "import sys; from twinsim import isaac_bridge as b; sys.exit(0 if b.ready() else 1)"; then
  echo "Isaac Sim が受け付けていない（./isaac_up.sh <GPU>）。止める"; exit 1
fi
echo "--- 描画 $(date '+%T')"
./run.sh render "$RUN" || { echo "描画に失敗"; exit 1; }

echo "--- MOPF をカメラなしで起動 $(date '+%T')（GPU $MOPF_GPU）"
cd "$MOPF" && ./stop_ampb.sh >/dev/null 2>&1
./start_ampb.sh --gpu "$MOPF_GPU" --no-llm --no-vc3 | tail -3 || { echo "MOPF の起動に失敗（GPU $MOPF_GPU が使用中の可能性）"; exit 1; }
for _ in $(seq 1 100); do curl -sf http://127.0.0.1:8010/api/video/list >/dev/null && break; sleep 3; done

cd "$TS"
echo "--- MOPF で検出・追跡 $(date '+%T')"
./run.sh mopf-process "$RUN"
echo "--- 正解と比べる $(date '+%T')"
./run.sh mopf-eval "$RUN"

echo "--- MOPF を止める $(date '+%T')"
cd "$MOPF" && ./stop_ampb.sh | tail -2
echo "=== 終わり $(date '+%F %T')"
