"""正解ラベルを読む: 検出と追跡の枠、人ごとの位置と状態、場所ごとの集計（CPU だけ。先に 01）。

    uv run python examples/03_read_labels.py
"""

from collections import Counter

import twinsim

result = twinsim.open_result("runs/tutorial")

# 検出と追跡の正解ラベル。列は frame, id, x, y, w, h, conf, class, visibility（frame は 1 始まり）
for camera in result.cameras:
    labels = result.mot(camera)
    visible = labels[labels[:, 8] >= 0.4]  # 見えている割合が 0.4 未満の枠は、学習・評価から外すのが目安
    print(f"{camera}: 枠 {len(labels)} 個（よく見えているもの {len(visible)} 個）、人 {len(set(visible[:, 1]))} 人")

# 1 コマ 1 人の位置と状態（世界の座標、m）
rows = list(result.frames())
print("最初の行:", rows[0])
print("状態ごとの行の数:", Counter(row["state"] for row in rows).most_common())

# 人ごとの出来事（正解）と、場所ごとの集計
gt = result.ground_truth()
print("ground_truth.json の項目:", ", ".join(gt))
print("tasks.json の項目:", ", ".join(result.tasks()))
