"""動画と正解ラベルから、物体検出の学習データ（YOLO の形）を作る（CPU だけ。先に 04）。

    uv run python examples/06_detection_dataset.py [--step 5]

runs/tutorial/dataset/ に images/*.jpg・labels/*.txt・dataset.yaml を書く。
ラベルの 1 行は「クラス 中心x 中心y 幅 高さ」で、画像の大きさを 1 にした値。クラスは person の 1 つだけ。
"""

import argparse

import numpy as np
from PIL import Image

import twinsim

MIN_VISIBLE = 0.4  # これより隠れている人は枠を付けない

parser = argparse.ArgumentParser()
parser.add_argument("--step", type=int, default=5, help="何コマごとに取り出すか")
args = parser.parse_args()

result = twinsim.open_result("runs/tutorial")
out = result.out_dir / "dataset"
(out / "images").mkdir(parents=True, exist_ok=True)
(out / "labels").mkdir(exist_ok=True)

n_images = n_boxes = 0
for camera in result.videos:
    labels = result.mot(camera)
    labels = labels[labels[:, 8] >= MIN_VISIBLE]
    for frame, image in result.video_frames(camera, step=args.step):
        height, width = image.shape[:2]
        rows = labels[labels[:, 0] == frame + 1]  # MOT の frame = シミュレータのコマ ＋ 1
        x0 = np.clip(rows[:, 2], 0, width)  # 画面からはみ出す枠は、画面の中だけにする
        y0 = np.clip(rows[:, 3], 0, height)
        x1 = np.clip(rows[:, 2] + rows[:, 4], 0, width)
        y1 = np.clip(rows[:, 3] + rows[:, 5], 0, height)
        keep = (x1 > x0) & (y1 > y0)
        lines = [f"0 {(a + c) / 2 / width:.6f} {(b + d) / 2 / height:.6f} {(c - a) / width:.6f} {(d - b) / height:.6f}"
                 for a, b, c, d in zip(x0[keep], y0[keep], x1[keep], y1[keep])]

        name = f"{camera}_{frame:06d}"
        Image.fromarray(image).save(out / "images" / f"{name}.jpg", quality=92)
        (out / "labels" / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        n_images += 1
        n_boxes += len(lines)

(out / "dataset.yaml").write_text(f"path: {out.resolve()}\ntrain: images\nval: images\nnames:\n  0: person\n")
print(f"画像 {n_images} 枚、枠 {n_boxes} 個 → {out}")
