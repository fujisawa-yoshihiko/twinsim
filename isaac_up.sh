#!/usr/bin/env bash
# 描画のための Isaac Sim を、twinsim の受け付けで起動する（GPU を 1 枚使う。共用なので空きを確かめてから）。
#   ./isaac_up.sh <GPU の番号>      例: ./isaac_up.sh 2      止めるとき: isim down
set -e
GPU=${1:?GPU の番号（nvidia-smi で空いている番号）}
nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv,noheader
cd "$(dirname "$0")"
uv run --no-project --with numpy --with scipy --with pyyaml --with pillow python -c "from twinsim import isaac_bridge as b; b.sync()"
isim up --gpu "$GPU" --enable omni.anim.navigation.core --enable omni.kit.capture.viewport \
  --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
echo "受け付けの確認: ./run.sh 以外から見るなら ~/isaac-sim-work/twinsim/outbox/_alive.txt が数秒ごとに更新される"
