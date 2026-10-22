"""Python から使う入口。

    from twinsim import api
    summary = api.run("office_gate_ev", out_dir="~/dt-data/twinsim/runs/test", overrides={"duration_s": 60})

overrides はシナリオの一部を上書きする dict（GUI・ほかの道具から値を変えて回すとき）。
elevator_policy(sim, t) を渡すと、EV の運行を差し替えられる（毎秒呼ばれ、car.arrivals に着く時刻を足す。UC2 の最適化の差し込み口）。
"""

import json
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
    out0 = Path(out_dir).expanduser()
    stale = [p for p in (out0 / "video", out0 / "render_log.json", out0 / "render_stdout.txt", out0 / "mopf_tracks", out0 / "mopf_eval", out0 / "mopf_graph") if p.exists()]
    if stale:  # 前の計算の動画・描画の記録・MOPF の結果は新しい正解と合わないので、まとめて名前を変えて残す（消さない）
        moved = out0 / f"before_{time.strftime('%Y%m%d-%H%M%S')}"
        moved.mkdir()
        for p in stale:
            p.rename(moved / p.name)
        print(f"前の動画・描画の記録を {moved} に移した（新しい計算と合わないため）")
    summary = write_all(sim, builder, spec, Path(out_dir).expanduser())
    summary["timing_s"] = {"simulate": round(t1 - t0, 1), "write": round(time.monotonic() - t1, 1)}
    out = Path(out_dir).expanduser()
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if "validity" in spec["outputs"]:
        try:  # 文献との比べ（validity.json・md・png）。失敗しても計算の結果は残す
            from .validity import evaluate
            evaluate(out)
            summary["files"] += ["validity.json", "validity.md", "validity.png"]
            (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        except Exception as e:
            print("validity failed:", e)
    return summary
