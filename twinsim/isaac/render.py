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
  preroll     描く前に余分に描いて捨てるコマの数（区間の最初の 1〜2 コマだけ見え方が違うのを避ける。省くと 0）
  people      置く人の名前（省くと全員）。カメラごとの区間では、そのカメラの近くの人だけを置いて速くする
  labels      true なら、描いたあと同じコマを流して、人ごとの枠（見えている部分・全身）と隠れの割合を Replicator で出す
出力: run_dir/frames/<frames_dir>/f.<コマ>.png と run_dir/<log_name>。labels のときは run_dir/labels_raw/<frames_dir>.json
"""

import colorsys
import glob
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


def label_person(prim):
    """人の一番上の prim に「class: person」の印を付ける（Replicator の枠は、この印の付いた prim ごとに 1 つ）。"""
    from pxr import UsdSemantics
    UsdSemantics.LabelsAPI.Apply(prim, "class").CreateLabelsAttr().Set(["person"])


# 全身の画素を測るコマの間隔。間のコマは、全身の枠の面積に対する比を前後から補う（labels.py）。描き直しは 1 回 1.5〜2 秒かかる。
# 10 コマおきの測りから見積もった補いの誤差: 30 コマおきで中央値 0.9%・9 割が 9% 以内（2026-11-04）
FULL_EVERY = 30


GLASS_KEYS = ("glass", "transp", "window", "acryl", "frost")  # 材質の path か MDL の名前にこれが入る物はガラスの類い


def occlude_glass(stage):
    """注釈を取る間だけ、ガラスの類いの材質の物を不透明な材質に差し替える（セッションのレイヤー）。
    意味の塗り分けはガラスを透かして向こうの人の画素を数えるが、描いた映像では飾りガラス・色ガラスの向こうはほとんど見えない
    （office のゲートの横のパネルの向こうの人を「全部見えている」としていた、2026-11-04）。→ 差し替えた物の数"""
    session = stage.GetSessionLayer()
    targets = []
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Gprim) or prim.GetPath().pathString.startswith("/Root/P"):
            continue
        mat, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
        if not mat:
            continue
        text = mat.GetPath().pathString.lower()
        for sh in Usd.PrimRange(mat.GetPrim()):
            a = sh.GetAttribute("info:mdl:sourceAsset") if sh.IsA(UsdShade.Shader) else None
            if a and a.Get():
                text += " " + str(a.Get().path).lower()
        if any(k in text for k in GLASS_KEYS):
            targets.append(prim.GetPath())
    with Usd.EditContext(stage, session):
        look = UsdShade.Material.Define(stage, "/TS_LabelOpaque")
        sh = UsdShade.Shader.Define(stage, "/TS_LabelOpaque/Shader")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(0.2, 0.2, 0.2))
        sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(1.0)
        look.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        for path in targets:  # インスタンスの中の物は書けないので、いちばん近いインスタンスを外す
            q = stage.GetPrimAtPath(path)
            while q and q.IsInstanceProxy():
                q = q.GetParent()
            if q and q.IsInstance():
                q.SetInstanceable(False)
        for path in targets:
            prim = stage.GetPrimAtPath(path)
            if prim:
                UsdShade.MaterialBindingAPI.Apply(prim).Bind(look, UsdShade.Tokens.strongerThanDescendants)
    return len(targets)


def seg_counts(seg, h, w):
    """意味の単位の塗り分け（印を付けた prim ごとに 1 つの番号）から、人の名前 → 見えている画素の数。"""
    sd = seg.get_data()
    img = np.asarray(sd["data"]).reshape(-1).astype(np.int64)
    cnt = np.bincount(img) if img.size else np.zeros(0, np.int64)
    out = {}
    for k, path in sd["info"].get("idToLabels", {}).items():
        i, path = int(k), str(path)
        if path.startswith("/Root/") and i < len(cnt) and cnt[i]:
            out[path.rsplit("/", 1)[-1]] = int(cnt[i])
    return out


def passes(boxes):
    """全身の枠が重ならない人の組に分ける（同じ組の人どうしは画面で重ならないので、組ごとに描けば全身の画素が数えられる）。"""
    groups = []
    for name, b in sorted(boxes.items(), key=lambda kv: -(kv[1][2] - kv[1][0]) * (kv[1][3] - kv[1][1])):
        for g in groups:
            if all(b[2] < c[0] or c[2] < b[0] or b[3] < c[1] or c[3] < b[1] for c in g.values()):
                g[name] = b
                break
        else:
            groups.append({name: b})
    return groups


async def full_silhouettes(stage, people, samples, seg, h, w, fps):
    """背景（空間の USD と置いた物）を消し、全身の枠が重ならない組ごとに人だけを描いて、人ごとの全身の画素の数を数える。
    samples: {コマ: {名前: 全身の枠}}。消すのはセッションのレイヤーの既定の値（time samples より強い）で、全部のコマを数えてから元に戻す
    （コマごとに消して戻すと、そのたびに場面全体を読み直して、1 コマ数秒かかった）。→ {コマ: {名前: 画素の数}}"""
    import omni.kit.app
    import omni.replicator.core as rep
    import omni.timeline
    tl = omni.timeline.get_timeline_interface()
    session = stage.GetSessionLayer()
    root = stage.GetPrimAtPath("/Root")
    env = [p for p in stage.GetPseudoRoot().GetChildren() if p.GetPath().pathString != "/Root"]
    env += [p for p in (root.GetChildren() if root else []) if p.GetName() not in people]
    env = [p for p in env if p.IsA(UsdGeom.Imageable) and not p.IsA(UsdGeom.Camera)]
    out = {}
    with Usd.EditContext(stage, session):
        touched = []
        for p in env:
            a = UsdGeom.Imageable(p).GetVisibilityAttr()
            a.Set(UsdGeom.Tokens.invisible)
            touched.append(a)
        # 組に入らない人は、表示を消す代わりに床の 1 km 下へ動かす（骨格つきの人物の表示の切り替えは、描き直しのたびに約 1.5 秒かかった）
        moves = {n: stage.GetPrimAtPath(f"/Root/{n}").GetAttribute("xformOp:translate") for n in people}
        away = Gf.Vec3d(0.0, 0.0, -1000.0)
        app = omni.kit.app.get_app()
        shown = None
        for f, boxes in sorted(samples.items()):
            tl.set_current_time(f / fps)
            out[f] = {}
            for g in passes(boxes):
                with Sdf.ChangeBlock():
                    for n, a in moves.items():
                        want = n in g
                        if shown is None or (n in shown) != want:
                            if want:
                                a.ClearDefault()  # 時刻ごとの位置に戻す
                            else:
                                a.Set(away)
                shown = set(g)
                await app.next_update_async()  # 動かしたのが描画に届いてから描く（届く前に描くと、前の組の画素になった）
                await rep.orchestrator.step_async(rt_subframes=1, delta_time=0.0, pause_timeline=True)
                c = seg_counts(seg, h, w)
                for n in g:
                    out[f][n] = c.get(n, 0)
        for a in moves.values():
            a.ClearDefault()
        for a in touched:
            a.ClearDefault()
    return out


async def labels(app, cam, f0, f1, fps, w, h, out, stage=None, people=()):
    """描いたのと同じコマを順に流し、人ごとの枠と画素を取る。tight = 見えている画素の枠（完全に隠れた人は出ない）、
    loose = 隠れた部分も含む全身の枠（画面で切られる）、px = 見えている画素の数、full = 全身の画素の数（FULL_EVERY コマごと）。
    Replicator の occlusionRatio・occlusion の注釈はこの人物モデルでは -1（計算されない）ので、隠れの割合は px と full から出す（labels.py）。"""
    import omni.replicator.core as rep
    import omni.timeline
    glass = occlude_glass(stage) if stage is not None else 0
    rp = rep.create.render_product(cam, (w, h))
    anns = {k: rep.AnnotatorRegistry.get_annotator(f"bounding_box_2d_{k}", init_params={"semanticTypes": ["class"]}) for k in ("tight", "loose")}
    seg = rep.AnnotatorRegistry.get_annotator("instance_segmentation", init_params={"semanticTypes": ["class"], "colorize": False})
    for a in [*anns.values(), seg]:
        a.attach([rp])
    tl = omni.timeline.get_timeline_interface()
    rows, t0, t_full = [], time.monotonic(), 0.0
    for f in range(f0, f1 + 1):
        tl.set_current_time(f / fps)
        await rep.orchestrator.step_async(rt_subframes=1, delta_time=0.0, pause_timeline=True)
        got = {}
        for k, a in anns.items():
            d = a.get_data()
            for r, path in zip(d["data"], d["info"]["primPaths"]):
                got.setdefault(path.rsplit("/", 1)[-1], {})[k] = [int(r["x_min"]), int(r["y_min"]), int(r["x_max"]), int(r["y_max"])]
        for name, n in seg_counts(seg, h, w).items():
            got.setdefault(name, {})["px"] = n
        rows.append({"frame": f, "people": got})
    if stage is not None:  # 全身の画素は、全部のコマを描いたあとでまとめて数える
        t1 = time.monotonic()
        samples = {r["frame"]: {n: v["loose"] for n, v in r["people"].items() if "loose" in v and n in people}
                   for r in rows if (r["frame"] - f0) % FULL_EVERY == 0 or r["frame"] == f1}
        full = await full_silhouettes(stage, list(people), {f: b for f, b in samples.items() if b}, seg, h, w, fps)
        for r in rows:
            for n, v in full.get(r["frame"], {}).items():
                r["people"][n]["full"] = v
        t_full = time.monotonic() - t1
    for a in [*anns.values(), seg]:
        a.detach()
    rp.destroy()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"camera": cam, "frames": [f0, f1], "width": w, "height": h, "full_every": FULL_EVERY, "full_s": round(t_full, 1),
               "glass_occluders": glass, "rows": rows}, open(out, "w"))
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
    placed, tinted, placed_names = 0, 0, []
    t0 = time.monotonic()
    pre = int(job.get("preroll", 0))
    only = set(job["people"]) if job.get("people") is not None else None
    for name, p in gt["people"].items():
        if only is not None and name not in only:
            continue
        s0 = p["start_frame"]
        tr, mv = gt["tracks"][name], gt["moving"][name]
        a, b = max(f0 - pre - 5, s0), min(f1 + 5, s0 + len(tr) - 1)  # 描く範囲にいる間だけ置く（速さのため）
        if a > b:
            continue
        # 歩く姿勢は、最後に止まった所（か現れた所）から進んだ距離で決まる（crowd_lib.add_track）。
        # 途中から描くときもそこから置き、分けて描いた区間の境目で姿勢が飛ばないようにする（全部を 1 本で描いたときと同じ姿勢）
        while a > s0 and mv[a - s0]:
            a -= 1
        frames = [(f, tr[f - s0][0], tr[f - s0][1], tr[f - s0][2], bool(mv[f - s0])) for f in range(a, b + 1)]
        cl.add_track(walker, name, p["model"], frames, z=float(job.get("z", 0.0)))
        placed_names.append(name)
        if job.get("labels"):
            label_person(stage.GetPrimAtPath(f"/Root/{name}"))
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
    times, label_times = {}, {}
    for cname in cams:
        c = gt["cameras"][cname]
        look_at_camera(stage, f"/Root/TS_{cname}", c)
        for _ in range(30):
            await app.next_update_async()
        folder = f"{run}/frames/{job.get('frames_dir') or cname}"
        a = max(0, f0 - pre)
        if not job.get("capture", True):  # 注釈だけを取り直す（映像は前に描いたもの。同じコマ・同じ人の置き方なら同じ姿勢）
            times[cname] = 0.0
            out = f"{run}/labels_raw/{job.get('frames_dir') or cname}.json"
            label_times[cname] = round(await labels(app, f"/Root/TS_{cname}", f0, f1, fps, c["width"], c["height"], out, stage, placed_names), 1)
            SHARED["restart"] = True
            log(cname, "labels only", f1 - f0 + 1, "frames in", label_times[cname], "s")
            continue
        sec = await capture(app, f"/Root/TS_{cname}", folder, a, f1, fps, c["width"], c["height"], job.get("preset", "RAY_TRACE"))
        for k in range(a, f0):  # 余分に描いた分は捨てる（隣の区間の画像と重ならないように。画像は folder/f_frames/f.<コマ>.png）
            for fn in glob.glob(f"{folder}/**/f.{k}.png", recursive=True):
                os.remove(fn)
        times[cname] = round(sec, 1)
        log(cname, "rendered", f1 - a + 1, "frames in", round(sec, 1), "s", f"(preroll {f0 - a})" if f0 > a else "")
        if job.get("labels"):
            out = f"{run}/labels_raw/{job.get('frames_dir') or cname}.json"
            lsec = await labels(app, f"/Root/TS_{cname}", f0, f1, fps, c["width"], c["height"], out, stage, placed_names)
            SHARED["restart"] = True  # 次のジョブでは注釈が空・誤りになるので、受け付けを起動し直す（agent_runner.py）
            label_times[cname] = round(lsec, 1)
            log(cname, "labels", f1 - f0 + 1, "frames in", round(lsec, 1), "s")
    json.dump({"frames": [f0, f1], "cameras": times, "labels_s": label_times, "people_placed": placed, "preroll": pre,
               "total_s": round(time.monotonic() - t_start, 1), "worker": os.environ.get("TWINSIM_WORKER", "main")},
              open(f"{run}/{job.get('log_name') or 'render_log.json'}", "w"))
    # 次のジョブを待つ間も、読み込んだ舞台を描き続けて GPU を使う（8 本で使用率 8 割ほど）。空の舞台にしておく
    try:
        await ctx.new_stage_async()
    except Exception as e:  # 描いた結果には関わらないので、失敗しても記録だけ
        log("空の舞台にできなかった:", e)
