"""Isaac Sim の中で、指定の視点から 1 枚ずつ撮る（カメラの置き場所の確かめ・GUI のカメラの見え方）。人は置かない。
ジョブ: usd、views [{name, eye, target, focal_mm?, width?, height?}]、out（出力の場所）。出力: out/<name>.png
"""

import json

import omni.usd
from pxr import Gf, UsdGeom



def add_lights(stage, lights):
    """空間の space.yaml の lights（部屋の中に照明がない USD のため）: [{xy, z, radius, intensity}] の球の照明を置く。"""
    from pxr import UsdLux
    for k, L in enumerate(lights or []):
        sl = UsdLux.SphereLight.Define(stage, f"/Root/TS_Light{k}")
        sl.CreateRadiusAttr(float(L.get("radius", 0.3)))
        sl.CreateIntensityAttr(float(L.get("intensity", 30000.0)))
        xf = UsdGeom.Xformable(sl)
        xf.ClearXformOpOrder()
        xf.AddTranslateOp().Set(Gf.Vec3d(float(L["xy"][0]), float(L["xy"][1]), float(L.get("z", 2.5))))

async def main():
    import omni.kit.app
    from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # noqa: F821
    ctx = omni.usd.get_context()
    if ctx.get_stage_url() != job["usd"]:
        await ctx.open_stage_async(job["usd"])
        while ctx.get_stage_loading_status()[2] > 0:
            await app.next_update_async()
    stage = ctx.get_stage()
    add_lights(stage, job.get("lights"))
    vp = get_active_viewport()
    for v in job["views"]:
        cam = UsdGeom.Camera.Define(stage, f"/Root/TS_View_{v['name']}")
        cam.CreateFocalLengthAttr(float(v.get("focal_mm", 12.0)))
        cam.CreateHorizontalApertureAttr(20.955)
        cam.CreateVerticalApertureAttr(20.955 * 9 / 16)
        cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 300.0))
        xf = UsdGeom.Xformable(cam)
        xf.ClearXformOpOrder()
        xf.AddTransformOp().Set(Gf.Matrix4d(1.0).SetLookAt(Gf.Vec3d(*v["eye"]), Gf.Vec3d(*v["target"]), Gf.Vec3d(0, 0, 1)).GetInverse())
        vp.camera_path = str(cam.GetPath())
        for _ in range(40):
            await app.next_update_async()
        capture_viewport_to_file(vp, f"{job['out']}/{v['name']}.png")
        for _ in range(10):
            await app.next_update_async()
    log("views", len(job["views"]))
