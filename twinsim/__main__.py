"""コマンド:
  python -m twinsim spaces                         空間の一覧
  python -m twinsim templates                      テンプレートの一覧
  python -m twinsim validate <シナリオ>             シナリオの確かめ（行き先・カメラの名前など）
  python -m twinsim run <シナリオ> [--out 場所] [--set key=value ...]   人の動きを計算して書き出す（描画はしない）
  python -m twinsim check <結果の場所>               結果の確かめ（壁の中・人の近さ・歩く速さ・止まる時間）
  python -m twinsim render <結果の場所> [--frames 始まり 終わり] [--cameras A,B]   Isaac Sim で描画して video/<カメラ>.mp4 を作る（GPU）
  python -m twinsim export-space <名前> --usd URL --region x0 x1 y0 y1 z0 z1 [--res 0.25]   USD から空間の材料を作る（GPU）
--set の例: --set duration_s=60 --set seed=3 --set streams.0.rate.per_min=20
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import api
from .scenario import TEMPLATES, load_scenario
from .space import list_spaces


def parse_set(items):
    over = {}
    for it in items or []:
        k, v = it.split("=", 1)
        v = yaml.safe_load(v)
        cur = over
        keys = k.split(".")
        for key in keys[:-1]:
            cur = cur.setdefault(key, {})
        cur[keys[-1]] = v
    return over


def main(argv=None):
    ap = argparse.ArgumentParser(prog="twinsim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spaces")
    sub.add_parser("templates")
    v = sub.add_parser("validate")
    v.add_argument("scenario")
    r = sub.add_parser("run")
    r.add_argument("scenario")
    r.add_argument("--out", default=None)
    r.add_argument("--set", action="append")
    c = sub.add_parser("check")
    c.add_argument("run_dir")
    rd = sub.add_parser("render")
    rd.add_argument("run_dir")
    rd.add_argument("--frames", nargs=2, type=int)
    rd.add_argument("--cameras")
    rd.add_argument("--preset", default="RAY_TRACE")
    ex = sub.add_parser("export-space")
    ex.add_argument("name")
    ex.add_argument("--usd", required=True)
    ex.add_argument("--region", nargs=6, type=float, required=True)
    ex.add_argument("--res", type=float, default=0.25)
    a = ap.parse_args(argv)
    if a.cmd == "spaces":
        print("\n".join(list_spaces()))
    elif a.cmd == "templates":
        for p in sorted(TEMPLATES.glob("*.yaml")):
            s = yaml.safe_load(p.read_text(encoding="utf-8"))
            print(f"{p.stem:24s} {s.get('space', ''):10s} {s.get('title', '')}")
    elif a.cmd == "validate":
        spec = load_scenario(a.scenario)
        print("ok:", spec.get("name"), "space", spec["space"], "streams", len(spec["streams"]), "cameras", [c["name"] for c in spec["cameras"]])
    elif a.cmd in ("render", "export-space"):
        from . import isaac_bridge as ib
        ib.sync()
        if not ib.ready():
            print("Isaac Sim が twinsim の受け付けで起動していない（README の「描画」の isim up を先に）")
            return 1
        if a.cmd == "render":
            r = ib.render(a.run_dir, a.frames, a.cameras.split(",") if a.cameras else None, a.preset)
        else:
            r = ib.export_space(a.name, a.usd, a.region, a.res)
        print(r["log"])
        print(json.dumps({k: v for k, v in r.items() if k != "log"}, ensure_ascii=False))
    elif a.cmd == "check":
        from .quality import check
        print(json.dumps(check(a.run_dir), ensure_ascii=False, indent=1))
    elif a.cmd == "run":
        over = parse_set(a.set)
        # streams.0.x のような番号つきの指定は、読んだシナリオに直接当てる
        spec = load_scenario(a.scenario)
        for key in [k for k in over if k == "streams"]:
            for idx, sub_over in over.pop(key).items():
                from .scenario import deep_merge
                spec["streams"][int(idx)] = deep_merge(spec["streams"][int(idx)], sub_over)
        out = a.out or str(Path.home() / "dt-data/twinsim/runs" / (spec.get("name") or Path(a.scenario).stem))
        summary = api.run(spec, out, overrides=over)
        print(json.dumps({k: summary[k] for k in ("people", "groups", "max_present", "elevator", "gate_passes", "timing_s")},
                         ensure_ascii=False, default=str))
        print("out:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
