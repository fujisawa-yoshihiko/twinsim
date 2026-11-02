"""動画のコマを取り出し、正解の枠を重ねて画像にする（CPU だけ。先に 04）。

    uv run python examples/05_frames_with_boxes.py

画像は runs/tutorial/boxes_<カメラ>.png に書く。枠は足元を中心に計算した箱なので、人の輪郭より少し大きい。
"""

from PIL import Image, ImageDraw

import twinsim

result = twinsim.open_result("runs/tutorial")
for camera in result.videos:
    labels = result.mot(camera)
    images = list(result.video_frames(camera, step=15))  # 0.5 秒ごと
    best = max(images, key=lambda item: (labels[:, 0] == item[0] + 1).sum())  # 枠がいちばん多いコマ
    frame, image = best

    canvas = Image.fromarray(image)
    draw = ImageDraw.Draw(canvas)
    rows = labels[(labels[:, 0] == frame + 1) & (labels[:, 8] >= 0.4)]  # MOT の frame = シミュレータのコマ ＋ 1
    for _, person, x, y, w, h, *_ in rows:
        draw.rectangle([x, y, x + w, y + h], outline=(255, 220, 0), width=2)
        draw.text((x + 3, y + 2), str(int(person)), fill=(255, 220, 0))

    path = result.out_dir / f"boxes_{camera}.png"
    canvas.save(path)
    print(f"{camera}: シミュレータの {frame} コマ目、枠 {len(rows)} 個 → {path}")
