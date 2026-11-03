"""Isaac Sim の中で、twinsim の計算の結果（ground_truth.json）を描画する。run_isaac.sh render が、ジョブのファイルを作ってから実行する。

ジョブ（JOB の場所の JSON）:
  run_dir   コンテナの中の結果の場所（/workspace/twinsim/runs/<名前>。ground_truth.json がある）
  usd       空間の USD の URL
  frames    [始まり, 終わり]（描くコマの範囲。試し撮りは短く）
  cameras   描くカメラの名前（空ならすべて）
  props     置く物 [{kind: signage, xy, face}]
  tint      true なら人ごとに服の色を変える（characters.tint と同じ式）
  preset    描画の方式（RAY_TRACE か PATH_TRACE）
  frames_dir  画像の置き場所（run_dir/frames/ の下。省くとカメラの名前）。1 本を分けて描くときに、分けた単位ごとに替える
  log_name    描画の記録の名前（省くと render_log.json）
出力: run_dir/frames/<frames_dir>/f.<コマ>.png と run_dir/<log_name>
"""

import colorsys
import json
import math
import os
import time
import types

import numpy as np
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

VENDOR = "/workspace/twinsim/isaac/vendor"
CLOTH = ("opaque__fabric", "opaque__leather", "retro__reflective", "opaque__plastic")
GOLDEN = 0.618033988749895


def _load(name):
    m = types.ModuleType(name)
    src = f"{VENDOR}/{name}.py"
    exec(compile(open(src, encoding="utf-8").read(), src, "exec"), m.__dict__)
    return m


def tint(k, part):  # twinsim/characters.py と同じ
    h = (k * GOLDEN + part * 0.37) % 1.0
    s = 0.45 + 0.4 * ((k * 7 + part * 3) % 5) / 4
    v = 0.6 + 0.4 * ((k * 3 + part) % 3) / 2
    return colorsys.hsv_to_rgb(h, s, v)


def look_at_camera(stage, path, c):
    cam = UsdGeom.Camera.Define(stage, path)
    cam.CreateFocalLengthAttr(float(c["focal_mm"]))
    cam.CreateHorizontalApertureAttr(float(c["h_aperture_mm"]))
    cam.CreateVerticalApertureAttr(float(c["h_aperture_mm"]) * c["height"] / c["width"])
    cam.CreateClippingRangeAttr(Gf.Vec2f(0.05, 300.0))
    xf = UsdGeom.Xformable(cam)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(Gf.Matrix4d(1.0).SetLookAt(Gf.Vec3d(*c["eye"]), Gf.Vec3d(*c["target"]), Gf.Vec3d(0, 0, 1)).GetInverse())
    return cam


def add_signage(stage, k, xy, face):
    """床置きのデジタルサイネージ（支柱と板。白い板に青い見出しの帯と文字の行）。板の正面を face の向きへ。"""
    def mat(path, color, emit=0.0):
        m = UsdShade.Material.Define(stage, path)
        sh = UsdShade.Shader.Define(stage, f"{path}/Shader")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        sh.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*(c * emit for c in color)))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        return m
    base = f"/Root/TS_Sign{k}"
    looks = {"post": mat(f"{base}_Looks/Post", (0.35, 0.35, 0.38)), "board": mat(f"{base}_Looks/Board", (0.95, 0.95, 0.95), 0.25),
             "head": mat(f"{base}_Looks/Head", (0.08, 0.25, 0.6), 0.2), "text": mat(f"{base}_Looks/Text", (0.15, 0.15, 0.18))}
    yaw = math.degrees(math.atan2(face[1] - xy[1], face[0] - xy[0]))
    root = UsdGeom.Xform.Define(stage, base)
    xf = UsdGeom.Xformable(root)
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(xy[0], xy[1], 0.0))
    xf.AddRotateZOp().Set(yaw - 90.0)

    def box(name, size, center, look):
        c = UsdGeom.Cube.Define(stage, f"{base}/{name}")
        c.CreateSizeAttr(1.0)
        x = UsdGeom.Xformable(c)
        x.AddTranslateOp().Set(Gf.Vec3d(*center))
        x.AddScaleOp().Set(Gf.Vec3f(*size))
        UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(looks[look])
    box("Base", (0.55, 0.4, 0.04), (0, 0, 0.02), "post")
    box("Post", (0.07, 0.07, 1.0), (0, 0, 0.5), "post")
    box("Frame", (0.92, 0.05, 1.02), (0, 0, 1.45), "post")
    box("Board", (0.84, 0.02, 0.94), (0, 0.03, 1.45), "board")
    box("Head", (0.84, 0.022, 0.16), (0, 0.035, 1.82), "head")
    for i in range(6):
        box(f"Line{i}", (0.6 - 0.08 * (i % 2), 0.022, 0.035), (-0.05 + 0.04 * (i % 2), 0.035, 1.64 - i * 0.1), "text")


def add_gate(stage, k, line, lanes, in_dir):
    """入館のゲートの機械（レーンを仕切る箱。高さ 1.0 m・通る向きに 1.4 m・幅 0.18 m、上面は黒いガラスの見立て）。"""
    (x0, y0), (x1, y1) = line
    d = np.array(in_dir, float)
    d /= np.linalg.norm(d)
    base = f"/Root/TS_Gate{k}"
    m = UsdShade.Material.Define(stage, f"{base}_Look")
    sh = UsdShade.Shader.Define(stage, f"{base}_Look/Shader")
    sh.CreateIdAttr("UsdPreviewSurface")
    sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.72, 0.73, 0.75))
    sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.6)
    sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.35)
    m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
    yaw = math.degrees(math.atan2(d[1], d[0]))
    for i in range(lanes + 1):  # レーンの境目ごとに 1 台
        f = i / lanes
        cx, cy = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        c = UsdGeom.Cube.Define(stage, f"{base}/Cab{i}")
        c.CreateSizeAttr(1.0)
        xf = UsdGeom.Xformable(c)
        xf.AddTranslateOp().Set(Gf.Vec3d(cx, cy, 0.5))
        xf.AddRotateZOp().Set(yaw)
        xf.AddScaleOp().Set(Gf.Vec3f(1.4, 0.18, 1.0))
        UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(m)



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

async def capture(app, cam, folder, start, end, fps, w, h, preset):
    from omni.kit.capture.viewport import CaptureExtension, CaptureOptions, CaptureRangeType, CaptureRenderPreset
    from omni.kit.viewport.utility import get_active_viewport
    get_active_viewport().camera_path = cam
    o = CaptureOptions()
    o.camera = cam
    o.range_type = CaptureRangeType.FRAMES
    o.capture_every_Nth_frames = 1
    o.start_frame, o.end_frame, o.fps = start, end, fps
    o.res_width, o.res_height = w, h
    o.render_preset = getattr(CaptureRenderPreset, preset)
    o.output_folder = folder
    o.file_name, o.file_type = "f", ".png"
    o.overwrite_existing_frames = True
    cap = CaptureExtension.get_instance()
    cap.options = o
    cap.show_default_progress_window = False
    t0 = time.monotonic()
    cap.start()
    for _ in range(600):
        await app.next_update_async()
        if not cap.done:
            break
    while not cap.done and time.monotonic() - t0 < 6 * 3600:
        await app.next_update_async()
    return time.monotonic() - t0


async def main():
    import omni.kit.app
    app = omni.kit.app.get_app()
    job = json.load(open(JOB))  # JOB は受け付け（agent_runner.py）が決める
    run = job["run_dir"]
    gt = json.load(open(f"{run}/ground_truth.json"))
    fps = gt["fps"]
    f0, f1 = job["frames"]
    t_start = time.monotonic()
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(job["usd"])
    while ctx.get_stage_loading_status()[2] > 0:
        await app.next_update_async()
    stage = ctx.get_stage()
    stage.SetTimeCodesPerSecond(fps)
    stage.SetFramesPerSecond(fps)
    log("stage loaded", round(time.monotonic() - t_start, 1), "s")
    dl, cl = _load("demo_lib"), _load("crowd_lib")
    walker = cl.Walker(stage, dl, fps)
    placed, tinted = 0, 0
    t0 = time.monotonic()
    for name, p in gt["people"].items():
        s0 = p["start_frame"]
        tr, mv = gt["tracks"][name], gt["moving"][name]
        a, b = max(f0 - 5, s0), min(f1 + 5, s0 + len(tr) - 1)  # 描く範囲にいる間だけ置く（速さのため）
        if a > b:
            continue
        # 歩く姿勢は、最後に止まった所（か現れた所）から進んだ距離で決まる（crowd_lib.add_track）。
        # 途中から描くときもそこから置き、分けて描いた区間の境目で姿勢が飛ばないようにする（全部を 1 本で描いたときと同じ姿勢）
        while a > s0 and mv[a - s0]:
            a -= 1
        frames = [(f, tr[f - s0][0], tr[f - s0][1], tr[f - s0][2], bool(mv[f - s0])) for f in range(a, b + 1)]
        cl.add_track(walker, name, p["model"], frames, z=float(job.get("z", 0.0)))
        placed += 1
        if job.get("tint", True):
            part = 0
            for prim in Usd.PrimRange(stage.GetPrimAtPath(f"/Root/{name}")):
                if prim.IsA(UsdShade.Shader) and prim.GetParent().GetName().startswith(CLOTH):
                    UsdShade.Shader(prim).CreateInput("diffuse_tint", Sdf.ValueTypeNames.Color3f).Set(
                        Gf.Vec3f(*tint(int(p.get("tint_index", placed)), part)))
                    part += 1
                    tinted += 1
    log("placed", placed, "people in", round(time.monotonic() - t0, 1), "s; tinted shaders", tinted)
    add_lights(stage, job.get("lights"))
    for k, pr in enumerate(job.get("props", [])):
        if pr.get("kind") == "signage":
            add_signage(stage, k, pr["xy"], pr["face"])
        elif pr.get("kind") == "gate":
            add_gate(stage, k, pr["line"], pr["lanes"], pr["in_dir"])
    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(max(f1, 1))
    cams = job.get("cameras") or list(gt["cameras"])
    times = {}
    for cname in cams:
        c = gt["cameras"][cname]
        look_at_camera(stage, f"/Root/TS_{cname}", c)
        for _ in range(30):
            await app.next_update_async()
        folder = f"{run}/frames/{job.get('frames_dir') or cname}"
        sec = await capture(app, f"/Root/TS_{cname}", folder, f0, f1, fps, c["width"], c["height"], job.get("preset", "RAY_TRACE"))
        times[cname] = round(sec, 1)
        log(cname, "rendered", f1 - f0 + 1, "frames in", round(sec, 1), "s")
    json.dump({"frames": [f0, f1], "cameras": times, "people_placed": placed, "total_s": round(time.monotonic() - t_start, 1),
               "worker": os.environ.get("TWINSIM_WORKER", "main")},
              open(f"{run}/{job.get('log_name') or 'render_log.json'}", "w"))
