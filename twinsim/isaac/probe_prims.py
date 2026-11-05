"""空間の USD で、名前に key を含む prim の一覧を出す（場所・大きさ・参照している部品のファイル）。
ほかの空間へ部品を置くとき（hospital の見立ての EV に office の EV の部品を置く、2026-11-05）に使う。

ジョブ（JOB の場所の JSON）: {"usd": 空間の USD, "out": 結果の JSON の場所, "keys": ["Elevator", ...], "max_depth": 6,
  "under": prim の path（任意。その下を key によらず全部、max_depth 段まで）}
出力: {"prims": [{"path", "type", "bbox": [x0, y0, z0, x1, y1, z1]（世界の座標）, "refs": [参照・ペイロードのファイル],
                  "translate", "rotate", "scale", "children"}], "meters_per_unit", "up_axis"}
"""

import json

import omni.usd
from pxr import Sdf, Usd, UsdGeom


def arcs(prim):
    out = []
    for spec in prim.GetPrimStack():
        for lst in (spec.referenceList, spec.payloadList):
            for it in list(lst.prependedItems) + list(lst.appendedItems) + list(lst.explicitItems):
                path = it.assetPath or ""
                layer = spec.layer.identifier
                if path:
                    out.append({"asset": Sdf.ComputeAssetPathRelativeToLayer(spec.layer, path) if layer else path,
                                "prim": str(it.primPath) if it.primPath else ""})
    return out


async def main():
    import omni.kit.app
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # noqa: F821  JOB は受け付けが決める
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(job["usd"])
    while ctx.get_stage_loading_status()[2] > 0:
        await app.next_update_async()
    stage = ctx.get_stage()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    keys = [k.lower() for k in job.get("keys", [])]
    depth = int(job.get("max_depth", 6))
    prims = []
    under = job.get("under")  # この prim の下を全部（key は見ない）
    it = Usd.PrimRange(stage.GetPrimAtPath(under)) if under else stage.Traverse()
    for prim in it:
        p = prim.GetPath()
        if under:
            if p.pathElementCount - Sdf.Path(under).pathElementCount > depth:
                continue
        elif p.pathElementCount > depth or not any(k in prim.GetName().lower() for k in keys):
            continue
        elif any(str(p).startswith(q["path"] + "/") for q in prims):  # 見つけた prim の子は書かない
            continue
        r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lo, hi = r.GetMin(), r.GetMax()
        x = UsdGeom.Xformable(prim) if prim.IsA(UsdGeom.Xformable) else None
        ops = {}
        if x:
            for op in x.GetOrderedXformOps():
                v = op.Get()
                ops[op.GetOpName()] = list(v) if hasattr(v, "__len__") else v
        prims.append({"path": str(p), "type": prim.GetTypeName(), "bbox": [round(float(v), 3) for v in (*lo, *hi)],
                      "refs": arcs(prim), "ops": {k: [round(float(c), 4) for c in v] if isinstance(v, list) else v for k, v in ops.items()},
                      "children": len(prim.GetChildren())})
    json.dump({"usd": job["usd"], "prims": prims, "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
               "up_axis": str(UsdGeom.GetStageUpAxis(stage))}, open(job["out"], "w"), indent=1, default=str)
    log("prims", len(prims))  # noqa: F821
    await ctx.new_stage_async()
