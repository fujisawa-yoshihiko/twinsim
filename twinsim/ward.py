"""病棟の配置（spaces/<空間>/ward.yaml のベッドとナースステーションの置き方）と、歩ける所の上の最短の道のり（m）を書き出す。
~/digitaltwin のワークベンチの「病棟の実施の遅れ」（workbench/bridge/ward.py）が、看護師の歩く時間に使う。形は docs/formats.md の 10。"""

import json
from pathlib import Path

import yaml

from . import config
from .space import Geodesic, load_space


def ward_layout(space="hospital"):
    sp = load_space(space)
    spec = yaml.safe_load((sp.folder / "ward.yaml").read_text(encoding="utf-8"))
    points = {b["name"]: [float(v) for v in b["xy"]] for b in spec["beds"]}
    for lay, stations in spec["layouts"].items():
        for st, xy in stations.items():
            points[f"{lay}:{st}"] = [float(v) for v in xy]
    names = list(points)
    geo = Geodesic(sp)  # 歩ける所の格子の上のダイクストラ法（歩けない点は近くの歩ける点に寄せる）
    dist = [[round(geo.dist(points[a], points[b]), 2) for b in names] for a in names]
    # ステーションからベッドまでの道の点の列（看護師の動きを画面に描くため。戻りは逆順）
    paths = {f"{lay}:{st}|{b['name']}": [[round(x, 2), round(y, 2)] for x, y in geo.path(points[f"{lay}:{st}"], points[b["name"]])]
             for lay, stations in spec["layouts"].items() for st in stations for b in spec["beds"]}
    return {"space": sp.name, "beds": spec["beds"], "layouts": spec["layouts"], "points": points, "names": names, "dist_m": dist,
            "paths": paths, "source": spec.get("source"),
            "note": "dist_m[i][j] = names[i] から names[j] までの歩ける所の上の最短の道のり（m、0.25 m の格子）。"
                    "paths[\"置き方:ステーション|ベッド\"] = その間の道の点の列（0.2 m の幅で間引いたもの）"}


def write(space="hospital", out=None):
    out = Path(out) if out else config.DATA / "ward" / f"{space}_ward_layout.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ward_layout(space), ensure_ascii=False, indent=1), encoding="utf-8")
    return out
