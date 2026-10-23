#!/usr/bin/env bash
# 人物照合のモデルの重みを落とす（git の外の ${TWINSIM_DATA:-~/dt-data/twinsim}/models/reid/ に置く。どれも MIT の配布元の Google Drive）。
#   OSNet x0.25 は MOPF と同じもの（~/MOPF_ALL_video/MOPF_CV_Native/models/reid/）を使うので、ここでは落とさない。
#   落としたあと sha256 を確かめる（2026-10-23 に落としたものと同じか）。読み込みは torch.load(weights_only=True) だけ（twinsim/reid.py）。
set -euo pipefail
D=${TWINSIM_DATA:-$HOME/dt-data/twinsim}/models/reid
mkdir -p "$D"
get() {  # 名前 Google Drive の ID sha256
  if [ ! -f "$D/$1" ]; then uv run --no-project --with gdown gdown --quiet "$2" -O "$D/$1"; fi
  echo "$3  $D/$1" | sha256sum -c -
}
# OSNet x1.0、MSMT17（torchreid の配布。boxmot の一覧と同じ ID）
get osnet_x1_0_msmt17.pt 112EMUfBPYeYg70w-syK6V6Mx8-Qb9Q1M b7d73dc67c016fd044e4027ff856019496392a7aca8fa0ed56d862a1632c1cf2
# CLIP-ReID ViT-B/16、MSMT17（https://github.com/Syliz517/CLIP-ReID の README の ViT-CLIP-ReID・MSMT17 の model）
get clipreid_vitb16_msmt17.pth 1BVaZo93kOksYLjFNH3Gf7JxIbPlWSkcO 9974ef57c418e8c88e59581f66f3f53fbe02f879311f7438009f84fd150b1c63
