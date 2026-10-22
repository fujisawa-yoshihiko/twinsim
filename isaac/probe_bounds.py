"""Isaac Sim の中で、USD のシーンの大きさを調べる（export-space の範囲を決めるため）。
ジョブ: usd、out（JSON の場所）。出力: 単位・上の軸・全体の範囲・大きすぎる物（200 m 超、外の建物など）を除いた範囲・床らしい物の高さ。
"""

import json
import re

import omni.usd
from pxr import Usd, UsdGeom


async def main():
    import omni.kit.app
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # noqa: F821
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(job["usd"])
    while ctx.get_stage_loading_status()[2] > 0:
        await app.next_update_async()
    stage = ctx.get_stage()
    root = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    lo, hi = [1e9] * 3, [-1e9] * 3
    floors, n, skipped = [], 0, []
    for p in root.GetChildren():
        r = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if r.IsEmpty():
            continue
        a, b = r.GetMin(), r.GetMax()
        if b[0] - a[0] > 200 or b[1] - a[1] > 200:
            skipped.append(p.GetName())
            continue
        n += 1
        lo = [min(lo[i], a[i]) for i in range(3)]
        hi = [max(hi[i], b[i]) for i in range(3)]
        if re.search(r"floor|ground", p.GetName(), re.I):
            floors.append(round(b[2], 2))
    whole = cache.ComputeWorldBound(stage.GetPseudoRoot()).ComputeAlignedRange()
    res = {"usd": job["usd"], "metersPerUnit": UsdGeom.GetStageMetersPerUnit(stage), "upAxis": UsdGeom.GetStageUpAxis(stage),
           "whole_min": list(whole.GetMin()), "whole_max": list(whole.GetMax()), "inner_min": lo, "inner_max": hi, "children": n,
           "skipped_large": skipped[:20], "floor_tops": sorted(set(floors))[:20]}
    json.dump(res, open(job["out"], "w"), indent=1)
    log(json.dumps(res))
