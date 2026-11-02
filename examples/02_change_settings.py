"""設定の作り方と変え方: テンプレート・dict・overrides・誤りの確かめ方（CPU だけ、10 秒ほど）。

    uv run python examples/02_change_settings.py
"""

import json
from pathlib import Path

import twinsim

print("テンプレート:", ", ".join(twinsim.list_templates()))
print("空間:", ", ".join(twinsim.list_spaces()))

# テンプレートを dict で受け取り、値を変えて渡す
config = twinsim.template("office_gate_ev")
config["duration_s"] = 60

# overrides は設定の一部だけを変える。乱数を変えて何度も回すときに使う
for seed in (1, 2, 3):
    r = twinsim.simulate(config, out_dir=f"runs/tutorial_seed{seed}", overrides={"seed": seed})
    print(f"seed {seed}: {r.summary['people']} 人、同時に最大 {r.summary['max_present']} 人")

# 値を足した設定は JSON に書き出せる。そのファイルを渡すと同じ計算をやり直せる
Path("runs/tutorial_config.json").write_text(json.dumps(r.config, ensure_ascii=False, indent=1))
print("使った設定:", "runs/tutorial_config.json")

# 設定の誤りは計算の前に分かる
try:
    twinsim.validate({**config, "duration_s": -1})
except ValueError as e:
    print("誤りの例:", e)
