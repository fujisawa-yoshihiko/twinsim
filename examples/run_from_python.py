"""Python から呼ぶ例。設定は JSON のファイル（minimal.json）。

    python examples/run_from_python.py
"""

from pathlib import Path

import twinsim

config = Path(__file__).with_name("minimal.json")
twinsim.validate(config)  # 誤りがあれば、計算の前に ValueError

result = twinsim.simulate(config, out_dir="runs/minimal", overrides={"seed": 2})
print(result)
print("人数:", result.summary["people"], "同時に最大:", result.summary["max_present"])

labels = result.mot("CamGate")  # 物体検知の正解ラベル: frame, id, x, y, w, h, conf, class, visibility
print("CamGate の枠:", len(labels), "個")

people = {row["person"] for row in result.frames() if row["state"] == "gate_queue"}
print("ゲートに並んだ人:", len(people), "人")
