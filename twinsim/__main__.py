"""コマンド:
  python -m twinsim spaces                         空間の一覧
  python -m twinsim templates                      テンプレートの一覧
  python -m twinsim validate <シナリオ>             シナリオの確かめ（行き先・カメラの名前など）
  python -m twinsim run <シナリオ> [--out 場所] [--set key=value ...]   人の動きを計算して書き出す（描画はしない）
  python -m twinsim check <結果の場所>               結果の確かめ（壁の中・人の近さ・歩く速さ・止まる時間）と文献との比べ（validity.*）
  python -m twinsim mopf-process <結果の場所> [--cameras ..] [--model yolo11m]   描いた動画を MOPF で検出・追跡（MOPF が動いているとき。GPU）
  python -m twinsim mopf-eval <結果の場所> [--tracks 場所]   MOPF の追跡を正解と比べる（mopf_eval/）、MOPF の追跡から中間層のグラフ（mopf_graph/）
  python -m twinsim mopf-overlay <結果の場所> [--cameras ..]   正解と MOPF の枠を重ねた動画・数えもらしの場面の画像（mopf_eval/）
  python -m twinsim mopf-sync <結果の場所> [--table-only]   カメラを時刻でそろえ、同じ人の各カメラの MOPF の ID（対応表・並べた動画）
  python -m twinsim mopf-link <結果の場所> [--no-video]   正解を使わずに 2 台の間の対応を推論し、採点する（links.json・links.png・sync_pred.mp4）
  python -m twinsim export-logs <結果の場所>         ゲートの通過記録・EV の運行記録の形で書き出す（実データの形の見本・往復の確かめ）
  python -m twinsim ward-layout [--space hospital] [--out 場所]   病棟のベッド・ナースステーションの置き方と、その間の道のり
  python -m twinsim calibrate <元のシナリオ> --gate-log a.csv --ev-log b.csv [--ev-mode replay]   記録で値を合わせたシナリオを作る
  python -m twinsim render <結果の場所> [--frames 始まり 終わり] [--cameras A,B]   Isaac Sim で描画して video/<カメラ>.mp4 を作る（GPU）
  python -m twinsim export-space <名前> --usd URL --region x0 x1 y0 y1 z0 z1 [--res 0.25]   USD から空間の材料を作る（GPU）
  python -m twinsim mopf <結果の場所> --camera <名前> [--apply]   MOPF の人流モニターの設定（床の図・位置合わせ・線・エリア）を作る
  python -m twinsim serve [--port 8770] [--url]       GUI と REST API（127.0.0.1 だけ、トークンつき）
  python -m twinsim show-space <名前>                 真上の図に歩ける所・目盛り・候補・場所・ゾーンを重ねた図（spaces/<名前>/annotate.png）
--set の例: --set duration_s=60 --set seed=3 --set streams.0.rate.per_min=20
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import api, config
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
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["serve"]:
        from .server import main as serve
        return serve(argv[1:])
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
    ss = sub.add_parser("show-space")
    ss.add_argument("name")
    mo = sub.add_parser("mopf")
    mo.add_argument("run_dir")
    mo.add_argument("--camera", required=True)
    mo.add_argument("--apply", action="store_true")
    mp = sub.add_parser("mopf-process")
    mp.add_argument("run_dir")
    mp.add_argument("--cameras", nargs="*")
    mp.add_argument("--model", default="yolo11m")
    mov = sub.add_parser("mopf-overlay")
    mov.add_argument("run_dir")
    mov.add_argument("--cameras", nargs="*")
    msy = sub.add_parser("mopf-sync")
    msy.add_argument("run_dir")
    msy.add_argument("--cameras", nargs="*")
    msy.add_argument("--table-only", action="store_true", help="対応表だけ（動画を作らない）")
    mli = sub.add_parser("mopf-link")
    mli.add_argument("run_dir")
    mli.add_argument("--cameras", nargs="*")
    mli.add_argument("--no-video", action="store_true", help="予測の番号で並べた動画を作らない")
    mli.add_argument("--apps", nargs="*", help="見た目の種類（color、osnet_x0_25_msmt17 など。既定は使えるものすべて）")
    mli.add_argument("--method", help="動画・links.json に使う方式（既定は time*+<最後の見た目>）")
    me = sub.add_parser("mopf-eval")
    me.add_argument("run_dir")
    me.add_argument("--tracks", help="tracking.jsonl の置き場所（既定 <結果>/mopf_tracks）")
    el = sub.add_parser("export-logs")
    el.add_argument("run_dir")
    el.add_argument("--out")
    wl = sub.add_parser("ward-layout")
    wl.add_argument("--space", default="hospital")
    wl.add_argument("--out")
    ca = sub.add_parser("calibrate")
    ca.add_argument("base", help="元のシナリオ（テンプレートの名前かファイル）")
    ca.add_argument("--gate-log")
    ca.add_argument("--ev-log")
    ca.add_argument("--ev-mode", choices=["fit", "replay"], default="fit")
    ca.add_argument("--out", help="書く場所（既定 ~/dt-data/twinsim/calibration/<id>/）")
    ca.add_argument("--id")
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
            print("Isaac Sim が動いていない。先に ./isaac_up.sh を実行する（終わったら isim down）")
            return 1
        if a.cmd == "render":
            r = ib.render(a.run_dir, a.frames, a.cameras.split(",") if a.cameras else None, a.preset)
        else:
            r = ib.export_space(a.name, a.usd, a.region, a.res)
        print(r["log"])
        print(json.dumps({k: v for k, v in r.items() if k != "log"}, ensure_ascii=False))
    elif a.cmd == "show-space":
        from .spaceview import draw
        print(draw(a.name))
    elif a.cmd == "mopf":
        from . import mopf
        out, cfg, info = mopf.write(a.run_dir, a.camera)
        print("out:", out, "lines", len(cfg["lines"]), "zones", [z["name"] for z in cfg["zones"]], json.dumps(info, ensure_ascii=False))
        from .mopf import expect
        e = expect(a.run_dir, a.camera)
        print("正解なら数えるはず:", json.dumps({"lines": e["lines"], "zones": e["zones"], "frames": e["frames"]}, ensure_ascii=False))
        if a.apply:
            print(mopf.apply(out))
    elif a.cmd == "mopf-process":
        from .mopf import process
        print(json.dumps(process(a.run_dir, a.cameras, a.model), ensure_ascii=False, indent=1))
    elif a.cmd == "mopf-overlay":
        from .mopf import overlay
        run = Path(a.run_dir).expanduser()
        for cam in a.cameras or sorted(p.stem for p in (run / "mopf_tracks").glob("*.jsonl")):
            print(cam, json.dumps(overlay(run, cam), ensure_ascii=False))
    elif a.cmd == "mopf-sync":
        from .mopf import identities, sync_video
        if a.table_only:
            res, _ = identities(a.run_dir, a.cameras)
            print(json.dumps({"persons": len(res["persons"]), "cameras": res["cameras"]}, ensure_ascii=False))
        else:
            print(json.dumps(sync_video(a.run_dir, a.cameras), ensure_ascii=False))
    elif a.cmd == "mopf-link":
        from .mopf import link, link_video
        out = link(a.run_dir, a.cameras, apps=a.apps, best=a.method)
        print("見た目の特徴を出す時間:", json.dumps(out["timing"], ensure_ascii=False), " 動画・links.json の方式:", out["method"])
        print(f"{'方式':28s} {'IDF1':>6s} {'組（正しい/予測）':>16s} {'見つけた/本当の組':>16s} {'全体の番号':>8s}")
        for m, r in out["metrics"].items():
            pairs = f"{r['cross_correct']:>8d}/{r['cross_links']:<7d} {r['handovers_found']:>8d}/{r['handovers']:<7d}"
            print(f"{m:28s} {r['idf1']:6.3f} {pairs} {r['global_ids']:>8d}")
        if not a.no_video:
            print(json.dumps(link_video(a.run_dir), ensure_ascii=False))
    elif a.cmd == "mopf-eval":
        from .mopf import evaluate, graph
        e = evaluate(a.run_dir, a.tracks)
        for c, r in e["cameras"].items():
            print(c, " ".join(f"{k}={r[k]}" for k in ("mota", "idf1", "num_switches", "recall", "precision", "count_mae", "foot_error_m_median")))
        g = graph(a.run_dir, a.tracks)
        for c, r in g.items():
            print(c, "中間層のグラフ（ゾーンの人数、MOPF / 正解）:", json.dumps(r["zones_compared"], ensure_ascii=False))
    elif a.cmd == "export-logs":
        from .calibrate import export_logs
        print("logs:", export_logs(a.run_dir, a.out))
    elif a.cmd == "ward-layout":
        from .ward import write
        print("ward layout:", write(a.space, a.out))
    elif a.cmd == "calibrate":
        from .calibrate import calibrate
        path, rep = calibrate(a.base, a.gate_log, a.ev_log, a.out, a.ev_mode, cid=a.id)
        for c in rep["changes"]:
            print("合わせた:", json.dumps(c, ensure_ascii=False)[:200])
        for c in rep["kept"]:
            print("元のまま:", json.dumps(c, ensure_ascii=False))
        print("scenario:", path)
    elif a.cmd == "check":
        from .quality import check
        from .validity import evaluate
        print(json.dumps(check(a.run_dir), ensure_ascii=False, indent=1))
        v = evaluate(a.run_dir)
        for part in ("input_reproduction", "emergent"):
            for k, x in v[part].items():
                items = x.items() if k == "arrivals" else [(k, x)]
                for name, y in items:
                    print(f"{part:18s} {name:28s} {y.get('verdict', '-'):4s} {y.get('note', '')}")
        print("validity:", Path(a.run_dir).expanduser() / "validity.md")
    elif a.cmd == "run":
        over = parse_set(a.set)
        # streams.0.x のような番号つきの指定は、読んだシナリオに直接当てる
        spec = load_scenario(a.scenario)
        for key in [k for k in over if k == "streams"]:
            for idx, sub_over in over.pop(key).items():
                from .scenario import deep_merge
                spec["streams"][int(idx)] = deep_merge(spec["streams"][int(idx)], sub_over)
        out = a.out or str(config.RUNS / (spec.get("name") or Path(a.scenario).stem))
        summary = api.run(spec, out, overrides=over)
        print(json.dumps({k: summary[k] for k in ("people", "groups", "max_present", "elevator", "gate_passes", "timing_s")},
                         ensure_ascii=False, default=str))
        print("out:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
