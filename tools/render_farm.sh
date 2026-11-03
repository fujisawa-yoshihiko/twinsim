#!/usr/bin/env bash
# 描画専用の Isaac Sim（画面なし・ポートなし）を GPU ごとにいくつか起動し、twinsim の受け付けを共通の待ち行列で動かす。
#   tools/render_farm.sh up --gpu N [--workers K] [--wait]   起動（--wait で受け付けが動き出すまで待つ）
#   tools/render_farm.sh down [--gpu N]                      停止（描きかけのジョブは、同じ名前で起動し直すと inbox に戻る）
#   tools/render_farm.sh status                              様子（受け付け・待ち行列・GPU）
# 投入は twinsim render <結果> --chunk-s 60 か、Python の twinsim.render(..., chunk_s=60)。
#
# 決まり（CLAUDE.md）: 他の人のジョブがある GPU には載せない（one-gpu check）。自分の GPU は全部で 2 枚まで。
# isim up（対話用、1 人 1 つ）とは別に数える。コンテナには isim.user・isim.gpu のラベルを付けるので、one-gpu と isim の空きの判定はこの GPU を使用中として扱う。
# 1 本あたり GPU のメモリ約 3〜7 GiB・CPU 16 スレッドまで（SIM_CPUS）。シェーダーなどのキャッシュは isim と共用し、ログと設定は 1 本ずつ分ける。
set -euo pipefail

ISIM_HOME=/opt/isaac-sim
[ -f "$ISIM_HOME/isim.conf" ] && source "$ISIM_HOME/isim.conf"
IMAGE=${ISAAC_SIM_IMAGE:-nvcr.io/nvidia/isaac-sim:6.1.0}
CPUS=${SIM_CPUS:-16}
DATA=$HOME/docker/isaac-sim
WORK=$HOME/isaac-sim-work
ME=$(id -un)
MAX_GPUS=2
LABEL=twinsim.render
ROOT=$(cd "$(dirname "$0")/.." && pwd)

die() { echo "render_farm: $*" >&2; exit 1; }

mine() {  # 自分の描画専用のコンテナ（名前 GPU 状態）
  docker ps -a --filter "label=$LABEL" --filter "label=isim.user=$ME" --format '{{.Names}}	{{.Label "isim.gpu"}}	{{.State}}'
}

own_gpus() {  # 自分が使っている GPU（描画専用・isim・MOPF など、one-gpu の判定と同じ）
  { mine | awk -F'\t' '$3 == "running" { print $2 }'
    one-gpu status 2>/dev/null | sed -n 's/^GPU \([0-9]*\): .*（自分 \([0-9]*\) MiB）.*/\1 \2/p' | awk '$2 > 0 { print $1 }'
  } | sort -un
}

cmd_up() {
  local gpu="" n=1 wait=0 k name
  while [ $# -gt 0 ]; do
    case $1 in
      -g|--gpu) gpu=${2:?GPU の番号}; shift 2 ;;
      -w|--workers) n=${2:?本数}; shift 2 ;;
      --wait) wait=1; shift ;;
      *) die "知らないオプション: $1" ;;
    esac
  done
  [[ $gpu =~ ^[0-9]+$ ]] || die "--gpu N で GPU を選ぶ（one-gpu pick が既定の GPU を示す）"
  [[ $n =~ ^[0-9]+$ ]] && (( n >= 1 && n <= 16 )) || die "--workers は 1〜16"
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu,temperature.gpu --format=csv,noheader
  one-gpu check "$gpu" || die "GPU $gpu に他の人のジョブがある（one-gpu status）"
  local gpus
  gpus=$( { own_gpus; echo "$gpu"; } | sort -un | wc -l)
  (( gpus <= MAX_GPUS )) || die "自分の GPU が $MAX_GPUS 枚を超える（今 $(own_gpus | tr '\n' ' ')、足すのは $gpu）"

  (cd "$ROOT" && uv run --no-project --with numpy --with scipy --with pyyaml --with pillow python -c "from twinsim import isaac_bridge as b; b.sync()")
  for k in $(seq 1 "$n"); do
    name=twinsim-render-g$gpu-$k
    if docker ps --format '{{.Names}}' | grep -qx "$name"; then echo "$name は動いている"; continue; fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    rm -f "$WORK/twinsim/outbox/_alive.g$gpu-$k.txt"   # 前に動いていた同じ名前の印で、起動したと見誤らないように
    mkdir -p "$DATA/farm/$name"/{logs,config,data,pkg} "$DATA"/cache/{main,computecache,kit} "$DATA/hub"
    docker run -d --name "$name" --runtime nvidia --restart no -u 1234:1234 --cpus "$CPUS" --network bridge \
      -e NVIDIA_VISIBLE_DEVICES="$gpu" -e ACCEPT_EULA=Y -e TWINSIM_WORKER="g$gpu-$k" \
      -e OMP_NUM_THREADS="$CPUS" -e OPENBLAS_NUM_THREADS="$CPUS" -e MKL_NUM_THREADS="$CPUS" \
      -l "$LABEL=1" -l "isim.user=$ME" -l "isim.gpu=$gpu" \
      -v "$DATA/cache/main:/isaac-sim/.cache:rw" -v "$DATA/cache/computecache:/isaac-sim/.nv/ComputeCache:rw" \
      -v "$DATA/cache/kit:/isaac-sim/kit/cache:rw" -v "$DATA/hub:/var/cache/hub:rw" \
      -v "$DATA/farm/$name/logs:/isaac-sim/.nvidia-omniverse/logs:rw" -v "$DATA/farm/$name/config:/isaac-sim/.nvidia-omniverse/config:rw" \
      -v "$DATA/farm/$name/data:/isaac-sim/.local/share/ov/data:rw" -v "$DATA/farm/$name/pkg:/isaac-sim/.local/share/ov/pkg:rw" \
      -v "$WORK:/workspace:rw" \
      --entrypoint /bin/sh "$IMAGE" -c "umask 0002 && /isaac-sim/license.sh >/dev/null && exec /isaac-sim/isaac-sim.sh --no-window \
        --/plugins/carb.tasking.plugin/threadCount=$CPUS --/plugins/omni.tbb.globalcontrol/maxThreadCount=$CPUS --/persistent/physics/numThreads=$CPUS \
        --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --exec /workspace/twinsim/isaac/agent_runner.py" >/dev/null
    echo "起動した: $name（GPU $gpu、受け付け g$gpu-$k）"
  done
  if (( wait )); then
    local t0=$SECONDS alive
    while (( SECONDS - t0 < 1500 )); do
      alive=0
      for k in $(seq 1 "$n"); do
        f=$WORK/twinsim/outbox/_alive.g$gpu-$k.txt
        [ -f "$f" ] && (( $(date +%s) - $(stat -c %Y "$f") < 30 )) && alive=$((alive + 1))
      done
      (( alive == n )) && { echo "受け付け $n 本が動いている（$((SECONDS - t0)) 秒）"; return 0; }
      for k in $(seq 1 "$n"); do
        [ "$(docker inspect -f '{{.State.Running}}' "twinsim-render-g$gpu-$k" 2>/dev/null)" = true ] ||
          die "twinsim-render-g$gpu-$k が止まった（docker logs twinsim-render-g$gpu-$k、$DATA/farm/twinsim-render-g$gpu-$k/logs）"
      done
      sleep 5
    done
    die "25 分待っても受け付けが動き出さない"
  fi
}

cmd_down() {
  local gpu="" names
  while [ $# -gt 0 ]; do
    case $1 in
      -g|--gpu) gpu=${2:?GPU の番号}; shift 2 ;;
      *) die "知らないオプション: $1" ;;
    esac
  done
  names=$(mine | awk -F'\t' -v g="$gpu" 'g == "" || $2 == g { print $1 }')
  [ -n "$names" ] || { echo "止める描画専用の Isaac Sim はない"; return 0; }
  # shellcheck disable=SC2086
  docker stop -t 20 $names >/dev/null && docker rm $names >/dev/null
  isim fix-perms >/dev/null 2>&1 || true
  echo "止めた: $(echo $names)"
  local left
  left=$(ls "$WORK/twinsim/running" 2>/dev/null | wc -l)
  (( left == 0 )) || echo "描きかけのジョブ $left 件は running/ にある（同じ GPU と本数で up し直すと inbox に戻る）"
}

cmd_status() {
  echo "描画専用の Isaac Sim:"
  mine | awk -F'\t' '{ printf "  %-22s GPU %s  %s\n", $1, $2, $3 }'
  echo "受け付け（最後の印からの秒）:"
  for f in "$WORK"/twinsim/outbox/_alive.*.txt; do
    [ -f "$f" ] || continue
    printf '  %-10s %s 秒\n' "$(basename "$f" .txt | cut -d. -f2-)" $(( $(date +%s) - $(stat -c %Y "$f") ))
  done
  echo "待ち行列: inbox $(ls "$WORK"/twinsim/inbox/*.py 2>/dev/null | wc -l)・描いている $(ls "$WORK"/twinsim/running/*.py 2>/dev/null | wc -l)"
  ls "$WORK"/twinsim/running/*.py 2>/dev/null | sed 's#.*/#  #' | head -20
  nvidia-smi --query-gpu=index,memory.used,utilization.gpu,power.draw,temperature.gpu --format=csv,noheader
}

case ${1:-} in
  up) shift; cmd_up "$@" ;;
  down) shift; cmd_down "$@" ;;
  status) shift; cmd_status "$@" ;;
  *) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
