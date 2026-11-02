#!/usr/bin/env bash
# 描画のための Isaac Sim を、twinsim の受け付けで起動する（共用の GPU なので、空きを確かめてから）。
#   ./isaac_up.sh [GPU の番号]      止めるとき: isim down
#   番号を省くと、動いている MOPF と同じ GPU に載せる（one-gpu が選ぶ。既定は GPU 3）
set -e
if command -v one-gpu >/dev/null; then GPU=$(one-gpu isim "${1:-}"); else GPU=${1:+--gpu $1}; fi   # 他の人のジョブがある GPU なら、ここで止まる
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
cd "$(dirname "$0")"
uv run --no-project --with numpy --with scipy --with pyyaml --with pillow python -c "from twinsim import isaac_bridge as b; b.sync()"
isim up $GPU --enable omni.anim.navigation.core --enable omni.kit.capture.viewport \
  --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
echo "受け付けの確認: ./run.sh 以外から見るなら ~/isaac-sim-work/twinsim/outbox/_alive.txt が数秒ごとに更新される"
