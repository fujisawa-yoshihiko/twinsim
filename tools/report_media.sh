#!/usr/bin/env bash
# 報告のページ（docs/report/<日付>/）に載せる小さな動画・GIF・画像を、結果（~/dt-data/twinsim/runs/<結果>/）から作る。CPU だけ、1 分ほど。
#   tools/report_media.sh <出力の場所> [<結果の場所>]   既定の結果: ~/dt-data/twinsim/runs/office_gate_ev
# 区間は office_gate_ev で選んだもの（2 台の対応: 正しくつないだ移動がいちばん多い 20 秒、ゲート: 入館がいちばん多い 12 秒、EV 前: EV が着く前後の 15 秒）。
# 画面のキャプチャは tools/capture_gui.py（GUI のサーバーが動いているとき）。
set -euo pipefail
OUT=$1
R=${2:-$HOME/dt-data/twinsim/runs/office_gate_ev}
mkdir -p "$OUT"

clip() {  # 入力 始まり 長さ 幅 fps 名前: 共有用の mp4（H.264）と、ページに埋め込む GIF
  local in=$1 ss=$2 t=$3 w=$4 fps=$5 name=$6
  ffmpeg -loglevel error -y -ss "$ss" -t "$t" -i "$in" -vf "scale=$((w * 3 / 2)):-2" -c:v libx264 -crf 28 -preset slow -pix_fmt yuv420p -an "$OUT/$name.mp4"
  ffmpeg -loglevel error -y -ss "$ss" -t "$t" -i "$in" \
    -vf "fps=$fps,scale=$w:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    "$OUT/$name.gif"
}

clip "$R/video/CamEV.mp4" 195 15 640 8 scene_ev
clip "$R/mopf_eval/CamGate_overlay.mp4" 250 12 640 8 overlay_gate
clip "$R/mopf_eval/sync_pred.mp4" 174 20 960 6 sync_pred

img() {  # 入力 幅 名前（JPEG、品質 85）。追加の切り出しは 4 つ目に ffmpeg の crop
  local vf="scale=$2:-2"
  [ -n "${4:-}" ] && vf="$4,$vf"
  ffmpeg -loglevel error -y -i "$1" -vf "$vf" -q:v 4 "$OUT/$3.jpg"
}
img "$R/preview.png" 1280 preview
img "$R/validity.png" 1200 validity
img "$R/mopf_eval/CamEV_floor.png" 1200 floor_ev
img "$R/mopf_eval/CamGate_floor.png" 900 floor_gate
img "$R/mopf_eval/CamGate_missed.png" 1400 missed_gate
img "$R/mopf_eval/links.png" 720 links_good "crop=720:520:0:0"
img "$R/mopf_eval/links.png" 720 links_bad "crop=720:660:0:1694"
ls -la "$OUT"
