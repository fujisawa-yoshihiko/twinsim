"""Isaac Sim の中で、USD のシーンから twinsim の空間（space pack）の材料を作る。python -m twinsim export-space が実行する。

ジョブ（JOB の JSON）: usd、region [x0, x1, y0, y1, z0, z1]（ナビメッシュを焼く範囲。1 つの階）、res（格子の刻み m）、out（出力の場所）
出力（out）:
  walkable.npz      walkable [ny, nx]（行 0 = y0）、x0、y0、res、z
  top.png           天井などを隠し、高さ 80 m から見下ろした図（top_view.json の視点）
  top_view.json     真上の図の視点（space.yaml の top_view にそのまま書ける）
  candidates.json   エレベーター・扉・階段・ゲートらしい prim の名前と位置（意味の地図を描く手がかり）
  info.json         シーンの単位・上の軸・全体の範囲・かかった時間
"""

import json
import math
import re
import time

import numpy as np
import omni.kit.commands
import omni.usd
from pxr import Gf, Usd, UsdGeom

PAT = re.compile(r"elevator|lift|escalator|stair|door|gate|turnstile|entrance|reception|lobby|sofa|bench|sign", re.I)


async def main():
    import omni.anim.navigation.core as nav
    import omni.kit.app
    from omni.anim.navigation.core.scripts.command import CreateNavMeshVolumeCommand
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # noqa: F821
    out = job["out"]
    x0, x1, y0, y1, z0, z1 = job["region"]
    res = float(job.get("res", 0.25))
    t_start = time.monotonic()
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(job["usd"])
    while ctx.get_stage_loading_status()[2] > 0:
        await app.next_update_async()
    stage = ctx.get_stage()
    for _ in range(30):
        await app.next_update_async()
    root = stage.GetDefaultPrim() or stage.GetPrimAtPath("/Root")
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    whole = cache.ComputeWorldBound(stage.GetPseudoRoot()).ComputeAlignedRange()
    info = {"metersPerUnit": UsdGeom.GetStageMetersPerUnit(stage), "upAxis": UsdGeom.GetStageUpAxis(stage),
            "range_min": list(whole.GetMin()), "range_max": list(whole.GetMax()), "root": str(root.GetPath())}
    log("units", info["metersPerUnit"], "up", info["upAxis"])
    # 手がかり: 名前で拾える物
    cands = []
    for p in Usd.PrimRange(root):
        if p.GetPath().pathElementCount > 3 or not PAT.search(p.GetName()):
            continue
        r = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if r.IsEmpty():
            continue
        lo, hi = r.GetMin(), r.GetMax()
        c = (lo + hi) / 2
        if x0 <= c[0] <= x1 and y0 <= c[1] <= y1 and z0 - 1 <= c[2] <= z1 + 1:
            cands.append({"path": str(p.GetPath()), "name": p.GetName(), "min": [round(v, 2) for v in lo], "max": [round(v, 2) for v in hi]})
    json.dump(cands, open(f"{out}/candidates.json", "w"), ensure_ascii=False, indent=1)
    log("candidates", len(cands))
    # 真上の図（範囲より上の物と天井を隠す）
    vp = get_active_viewport()
    hidden = []
    for p in root.GetChildren():
        r = cache.ComputeWorldBound(p).ComputeAlignedRange()
        if not r.IsEmpty() and r.GetMin()[2] >= z1 - 0.3 and p.IsA(UsdGeom.Imageable):
            UsdGeom.Imageable(p).MakeInvisible()
            hidden.append(p)
    for p in stage.Traverse():
        if p.IsA(UsdGeom.Imageable) and re.search(r"ceiling|roof", p.GetName(), re.I):
            UsdGeom.Imageable(p).MakeInvisible()
            hidden.append(p)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    span = max(x1 - x0, (y1 - y0) * 16 / 9) * 1.05
    height = 80.0
    focal = 20.955 / 2 / (span / 2 / height)
    tv = {"eye": [cx, cy - 0.01, z0 + height], "target": [cx, cy, z0], "focal_mm": round(focal, 3), "h_aperture_mm": 20.955,
          "width": 1280, "height": 720}
    cam = UsdGeom.Camera.Define(stage, "/Root/TS_TopView")
    cam.CreateFocalLengthAttr(tv["focal_mm"])
    cam.CreateHorizontalApertureAttr(20.955)
    cam.CreateVerticalApertureAttr(20.955 * 9 / 16)
    cam.CreateClippingRangeAttr(Gf.Vec2f(1.0, 500.0))
    xf = UsdGeom.Xformable(cam)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(Gf.Matrix4d(1.0).SetLookAt(Gf.Vec3d(*tv["eye"]), Gf.Vec3d(*tv["target"]), Gf.Vec3d(0, 0, 1)).GetInverse())
    vp.camera_path = "/Root/TS_TopView"
    for _ in range(80):
        await app.next_update_async()
    capture_viewport_to_file(vp, f"{out}/top.png")
    for _ in range(15):
        await app.next_update_async()
    for p in hidden:
        UsdGeom.Imageable(p).MakeVisible()
    json.dump(tv, open(f"{out}/top_view.json", "w"))
    # ナビメッシュ（範囲を絞って焼く）
    CreateNavMeshVolumeCommand(parent_prim_path=str(root.GetPath()), volume_type=0).do()
    vol = [p for p in root.GetChildren() if p.GetName().startswith("NavMeshVolume")][-1]
    m = Gf.Matrix4d(1.0).SetScale(Gf.Vec3d(x1 - x0, y1 - y0, z1 - z0)) * Gf.Matrix4d(1.0).SetTranslate(Gf.Vec3d(cx, cy, (z0 + z1) / 2))
    omni.kit.commands.execute("TransformPrim", path=vol.GetPath(), new_transform_matrix=m)
    inav = nav.acquire_interface()
    for _ in range(2):  # 範囲を作った直後の 1 回目は壁を無視することがあったので、2 回焼く（hospital-sim の経験）
        t0 = time.monotonic()
        inav.start_navmesh_baking()
        for _ in range(20):
            await app.next_update_async()
        while inav.is_navmesh_baking() and time.monotonic() - t0 < 900:
            await app.next_update_async()
    navmesh = inav.get_navmesh()
    if navmesh is None:
        log("navmesh failed")
        return
    nx, ny = int(round((x1 - x0) / res)) + 1, int(round((y1 - y0) / res)) + 1
    grid = np.zeros((ny, nx), bool)
    for i in range(ny):
        y = y0 + i * res
        for j in range(nx):
            x = x0 + j * res
            q, _ = navmesh.query_closest_point(target=(x, y, z0))
            grid[i, j] = abs(q[0] - x) + abs(q[1] - y) < res * 0.1 and abs(q[2] - z0) < 0.3
    np.savez_compressed(f"{out}/walkable.npz", walkable=grid, x0=x0, y0=y0, res=res, z=z0)
    info["walkable_cells"] = int(grid.sum())
    info["seconds"] = round(time.monotonic() - t_start, 1)
    json.dump(info, open(f"{out}/info.json", "w"), indent=1)
    log("walkable", int(grid.sum()), "of", grid.size, "cells; total", info["seconds"], "s")
