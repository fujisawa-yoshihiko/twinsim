"""空間の USD で、ガラス・透ける材質の付いた prim の一覧を出す（描画の正解で、すりガラスの向こうの人を「見えている」と数えた件の調べ、2026-11-04）。

ジョブ（JOB の場所の JSON）: {"usd": 空間の USD, "out": 結果の JSON の場所, "region": [x0, x1, y0, y1]（任意。この範囲にかかる prim だけ）}
出力: {"materials": {材質の path: {"mdl": MDL の名前, "prims": 数, "examples": [prim の path], "bbox": [x0, y0, z0, x1, y1, z1]}},
       "prims": [{"path", "material", "mdl", "corners": 向きのある箱の 8 つの角（世界の座標）}], "meters_per_unit", "up_axis"}
ガラスの奥の人の隠れを計算機で数えるのに使う（twinsim/glass.py）。
"""

import json

import omni.usd
from pxr import Gf, Usd, UsdGeom, UsdShade

KEYS = ("glass", "frost", "transl", "transp", "window", "mirror", "acryl", "clear")


async def main():
    import omni.kit.app
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # noqa: F821（受け付けが決める）
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(job["usd"])
    while ctx.get_stage_loading_status()[2] > 0:
        await app.next_update_async()
    stage = ctx.get_stage()
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    reg = job.get("region")
    mats, prims = {}, []
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Gprim):
            continue
        mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if not mat:
            continue
        mp = mat.GetPath().pathString
        mdl = ""
        for sh in Usd.PrimRange(mat.GetPrim()):
            if sh.IsA(UsdShade.Shader):
                a = sh.GetAttribute("info:mdl:sourceAsset")
                if a and a.Get():
                    mdl = str(a.Get().path) + ":" + str(sh.GetAttribute("info:mdl:sourceAsset:subIdentifier").Get() or "")
                    break
        text = (mp + " " + mdl).lower()
        if not any(k in text for k in KEYS):
            continue
        bb = cache.ComputeWorldBound(prim)
        r = bb.ComputeAlignedRange()
        lo, hi = r.GetMin(), r.GetMax()
        if reg and (hi[0] < reg[0] or lo[0] > reg[1] or hi[1] < reg[2] or lo[1] > reg[3]):
            continue
        lr, mx = bb.GetRange(), bb.GetMatrix()
        corners = [list(mx.Transform(Gf.Vec3d(*[(lr.GetMin(), lr.GetMax())[(k >> i) & 1][i] for i in range(3)]))) for k in range(8)]
        prims.append({"path": prim.GetPath().pathString, "material": mp, "mdl": mdl, "corners": [[round(v, 4) for v in c] for c in corners]})
        m = mats.setdefault(mp, {"mdl": mdl, "prims": 0, "examples": [], "bbox": [1e9, 1e9, 1e9, -1e9, -1e9, -1e9]})
        m["prims"] += 1
        if len(m["examples"]) < 5:
            m["examples"].append(prim.GetPath().pathString)
        m["bbox"] = [min(m["bbox"][0], lo[0]), min(m["bbox"][1], lo[1]), min(m["bbox"][2], lo[2]),
                     max(m["bbox"][3], hi[0]), max(m["bbox"][4], hi[1]), max(m["bbox"][5], hi[2])]
    json.dump({"usd": job["usd"], "materials": mats, "prims": prims, "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
               "up_axis": str(UsdGeom.GetStageUpAxis(stage))}, open(job["out"], "w"), indent=1)
    log("materials", len(mats))  # noqa: F821
    await ctx.new_stage_async()
