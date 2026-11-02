"""動画を取得する: Isaac Sim で描画して mp4 を作る（GPU。先に 01）。

    ./isaac_up.sh                                         # Isaac Sim を起動する（GPU は one-gpu が選ぶ）
    uv run python examples/04_get_video.py                # 人がいちばん多い 2 秒を、全部のカメラで描く
    uv run python examples/04_get_video.py --seconds 5 --cameras CamGate
    uv run python examples/04_get_video.py --all          # 全部の長さを描く（1 台あたり映像の長さの約 8.5 倍かかる）
    isim down                                             # 終わったら GPU を返す

--plain を付けると、服の色を人ごとに変えない（評価に使う動画はこちら）。
"""

import argparse

import numpy as np

import twinsim


def busiest_frames(result, cameras, seconds):
    """正解ラベルで、見えている人がいちばん多い区間を探す。返すのはシミュレータのコマ（端を含む）。"""
    gt = result.ground_truth()
    n = int(seconds * gt["fps"])
    count = np.zeros(gt["total_frames"])
    for camera in cameras:
        labels = result.mot(camera)
        labels = labels[labels[:, 8] >= 0.4]
        np.add.at(count, labels[:, 0].astype(int) - 1, 1)  # MOT の frame は 1 始まり
    start = int(np.convolve(count, np.ones(n), "valid").argmax())
    return start, start + n - 1


parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=2)
parser.add_argument("--cameras", nargs="*", help="描くカメラ（既定は全部）")
parser.add_argument("--all", action="store_true", help="全部の長さを描く")
parser.add_argument("--plain", action="store_true", help="服の色を変えない")
args = parser.parse_args()

result = twinsim.open_result("runs/tutorial")
cameras = args.cameras or result.cameras
frames = None if args.all else busiest_frames(result, cameras, args.seconds)
print("描くコマ:", frames or "全部", "カメラ:", ", ".join(cameras))

done = twinsim.render(result.out_dir, frames=frames, cameras=cameras, tint=False if args.plain else None)  # Isaac Sim が動いていなければ RuntimeError
print(f"かかった時間: {done['seconds']} 秒")
for camera, path in result.videos.items():
    print(f"{camera}: {path}（{path.stat().st_size / 1e6:.1f} MB）")
print("動画の 0 コマ目はシミュレータの", result.video_first_frame, "コマ目")
