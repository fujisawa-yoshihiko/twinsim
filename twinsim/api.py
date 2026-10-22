"""Python から使う入口。

    from twinsim import api
    summary = api.run("office_gate_ev", out_dir="~/dt-data/twinsim/runs/test", overrides={"duration_s": 60})

overrides はシナリオの一部を上書きする dict（GUI・ほかの道具から値を変えて回すとき）。
elevator_policy(sim, t) を渡すと、EV の運行を差し替えられる（毎秒呼ばれ、car.arrivals に着く時刻を足す。UC2 の最適化の差し込み口）。
"""

import time
from pathlib import Path

from .outputs import write_all
from .scenario import build, load_scenario


def run(scenario, out_dir, overrides=None, elevator_policy=None):
    t0 = time.monotonic()
    spec = load_scenario(scenario, overrides)
    sim, builder = build(spec)
    if elevator_policy is not None:
        sim.elevator_policy = elevator_policy
    sim.run()
    t1 = time.monotonic()
    summary = write_all(sim, builder, spec, Path(out_dir).expanduser())
    summary["timing_s"] = {"simulate": round(t1 - t0, 1), "write": round(time.monotonic() - t1, 1)}
    (Path(out_dir).expanduser() / "summary.json").write_text(__import__("json").dumps(summary, ensure_ascii=False, indent=1))
    return summary
