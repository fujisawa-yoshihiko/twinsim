# twinsim へ写したもの（元: ~/digitaltwin/hospital-sim/scripts/demo_lib.py、commit c5d891a）。直すときは元と合わせる。
"""病院のシーンで人を経路に沿って歩かせるための補助（検証用）。

人物は Isaac Sim の人形 biped_demo_meters（歩行アニメーションと同じ 81 本の骨格）。
アニメーションと人形は Y が上、病院のシーンは Z が上なので、人物を X 軸まわりに 90 度回して立たせる。
アニメーションのファイルは単位の表示がセンチメートルだが、値はメートル（骨盤の高さ 0.94）なのでそのまま使う。
その場で歩くアニメーションを繰り返しながら、人物の位置を経路に沿って動かす（足は少し滑る）。
"""

import math

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

PEOPLE = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/People"
BIPED = f"{PEOPLE}/Characters/biped_demo/biped_demo_meters.usd"
WALK = f"{PEOPLE}/Animations/stand_walk_loop_in_place.skelanim.usd"
IDLE = f"{PEOPLE}/MotionLibrary/BuiltinActions/Idle/Idle.usd"
CM = 1.0  # アニメーションの関節の移動量の倍率（値はすでにメートル）
WALK_PERIOD = 80  # 歩行の 1 周期のコマ数（30 コマ/秒）
IDLE_PERIOD = 131


def resample(points, speed, fps):
    """経路を、毎コマ speed/fps ずつ進む位置の列にする。到着後は終点のまま。"""
    pts = [Gf.Vec2d(p[0], p[1]) for p in points]
    seg = [(pts[i + 1] - pts[i]).GetLength() for i in range(len(pts) - 1)]
    total = sum(seg)
    step = speed / fps
    out, i, acc = [], 0, 0.0
    n = int(math.ceil(total / step)) + 1
    for k in range(n):
        d = min(k * step, total)
        while i < len(seg) - 1 and acc + seg[i] < d:
            acc += seg[i]
            i += 1
        f = 0.0 if seg[i] == 0 else (d - acc) / seg[i]
        out.append(pts[i] + (pts[i + 1] - pts[i]) * min(max(f, 0.0), 1.0))
    return out, total


def headings(pos, look=8):
    """進む向き（Z 軸まわりの角度、度）。少し先の位置を見て、角の向きの変化をなめらかにする。"""
    out, last = [], 0.0
    for k in range(len(pos)):
        a, b = pos[max(k - look, 0)], pos[min(k + look, len(pos) - 1)]
        d = b - a
        if d.GetLength() > 1e-4:
            last = math.degrees(math.atan2(d[1], d[0]))
        out.append(last)
    # 角度が ±180 度をまたいで回り込まないよう、連続にする
    for k in range(1, len(out)):
        while out[k] - out[k - 1] > 180:
            out[k] -= 360
        while out[k] - out[k - 1] < -180:
            out[k] += 360
    return out


_SOURCES = {}  # 開いたアニメーションのステージを保持する（ステージが消えると prim も使えなくなる）


def _source(url):
    if url not in _SOURCES:
        _SOURCES[url] = Usd.Stage.Open(url)
    return UsdSkel.Animation(_SOURCES[url].GetDefaultPrim())


def bake_animation(stage, path, walk_frames, total_frames):
    """walk_frames コマまで歩行、その後は立ち止まった姿勢を繰り返すアニメーションを作る。"""
    walk, idle = _source(WALK), _source(IDLE)
    joints = list(walk.GetJointsAttr().Get())
    if list(idle.GetJointsAttr().Get()) != joints:
        idle = None
    anim = UsdSkel.Animation.Define(stage, path)
    anim.CreateJointsAttr(Vt.TokenArray(joints))
    tr, rot, sc = anim.CreateTranslationsAttr(), anim.CreateRotationsAttr(), anim.CreateScalesAttr()
    cache = {}

    def sample(src, t, key):
        if (key, t) not in cache:
            tt = src.GetTranslationsAttr().Get(t)
            cache[(key, t)] = (Vt.Vec3fArray([Gf.Vec3f(v) * CM for v in tt]), src.GetRotationsAttr().Get(t),
                               src.GetScalesAttr().Get(t))
        return cache[(key, t)]

    for f in range(total_frames + 1):
        if f <= walk_frames or idle is None:
            t, s = f % WALK_PERIOD, sample(walk, f % WALK_PERIOD, "w")
        else:
            t, s = (f - walk_frames) % IDLE_PERIOD, sample(idle, (f - walk_frames) % IDLE_PERIOD, "i")
        tr.Set(s[0], f)
        rot.Set(s[1], f)
        if s[2] is not None:
            sc.Set(s[2], f)
    return anim


def add_staff(stage, name, route_points, color, speed, fps, total_frames, marker=True):
    """人を 1 人置き、経路に沿って歩かせる。到着したコマを返す。"""
    pos, length = resample(route_points, speed, fps)
    yaw = headings(pos)
    root = UsdGeom.Xform.Define(stage, f"/Root/{name}")
    xf = UsdGeom.Xformable(root)
    xf.ClearXformOpOrder()
    t_op, r_op = xf.AddTranslateOp(), xf.AddRotateZOp()
    for f in range(total_frames + 1):
        k = min(f, len(pos) - 1)
        t_op.Set(Gf.Vec3d(pos[k][0], pos[k][1], 0.0), f)
        r_op.Set(yaw[k] + 90.0, f)  # 人形の正面（Y が上の空間の +Z）は、立たせると -Y を向くので 90 度足す
    body = stage.DefinePrim(f"/Root/{name}/Body")
    body.GetReferences().AddReference(BIPED)
    UsdGeom.Xformable(body).AddRotateXOp().Set(90.0)  # Y が上の人形を Z が上のシーンに立たせる
    anim_path = f"/Root/{name}/Body/WalkAnim"
    bake_animation(stage, anim_path, len(pos) - 1, total_frames)
    skel = stage.GetPrimAtPath(f"/Root/{name}/Body/Root")
    UsdSkel.BindingAPI.Apply(skel).CreateAnimationSourceRel().SetTargets([Sdf.Path(anim_path)])
    if marker:  # 真上から見ても分かるよう、頭の上に色の付いた円盤を置く
        disc = UsdGeom.Cylinder.Define(stage, f"/Root/{name}/Marker")
        disc.CreateRadiusAttr(0.55)
        disc.CreateHeightAttr(0.05)
        disc.CreateAxisAttr("Z")
        disc.CreateDisplayColorAttr(Vt.Vec3fArray([Gf.Vec3f(*color)]))
        UsdGeom.Xformable(disc).AddTranslateOp().Set(Gf.Vec3d(0, 0, 2.3))
    return len(pos) - 1, length


# --- 医療スタッフの人物（骨格 101 本）用: 歩行アニメーションを骨格の変換（リターゲット）で作り直して使う ---
SETUP = f"{PEOPLE}/Characters/Biped_Setup.usd"
MEDICAL = {"F": (f"{PEOPLE}/Characters/F_Medical_01/F_Medical_01.usd",
                 "female_adult_medical_01/ManRoot/female_adult_medical_01/female_adult_medical_01/female_adult_medical_01"),
           "M": (f"{PEOPLE}/Characters/M_Medical_01/M_Medical_01.usd",
                 "male_adult_medical_01/ManRoot/male_adult_medical_01/male_adult_medical_01/male_adult_medical_01")}


# 人形の関節 → 医療スタッフの骨格と同じ付け方の名前（人形はもともと Left_Thigh などの別の付け方で、Head しか一致しない）
TAG_MAP = {"Pelvis": "Hips", "Spine1": "Spine1", "Spine2": "Spine2", "Chest": "Chest", "Neck1": "Neck1",
           "Neck2": "Neck2", "Head": "Head"}
for _s, _side in (("L", "Left"), ("R", "Right")):
    TAG_MAP.update({f"{_s}_UpLeg": f"{_side}Leg", f"{_s}_LoLeg": f"{_side}Shin", f"{_s}_Ankle": f"{_side}Foot",
                    f"{_s}_Ball": f"{_side}ToeBase", f"{_s}_Clavicle": f"{_side}Shoulder", f"{_s}_UpArm": f"{_side}Arm",
                    f"{_s}_LoArm": f"{_side}ForeArm", f"{_s}_Wrist": f"{_side}Hand"})
    for _f in ("Index", "Middle", "Ring", "Pinky"):
        TAG_MAP.update({f"{_s}_{_f}Finger{k}": f"{_side}Hand{_f}{k}" for k in (2, 3, 4)})
    TAG_MAP.update({f"{_s}_ThumbFinger{k}": f"{_side}HandThumb{k + 1}" for k in (1, 2, 3)})


def _retag_source(stage, skel_path):
    p = stage.GetPrimAtPath(skel_path)
    joints = list(UsdSkel.Skeleton(p).GetJointsAttr().Get())
    tags = [TAG_MAP.get(j.rsplit("/", 1)[-1], "") for j in joints]
    p.GetAttribute("controlRig:retargetTags").Set(Vt.TokenArray(tags))
    return sum(1 for t in tags if t)


def retarget_sources(stage, target_skeleton, out_parent):
    """人形の骨格から target_skeleton へ、歩行と立ち止まりのアニメーションを作り直す。作ったアニメーションの path を返す。"""
    import omni.kit.commands
    rig = "/Root/AgentRig2"  # 名前を付け直した人形（変換器が古い対応づけを使い回さないよう、別の場所に読み込む）
    if not stage.GetPrimAtPath(f"{rig}/BipedSetup"):
        setup = stage.DefinePrim(f"{rig}/BipedSetup")
        setup.GetReferences().AddReference(SETUP)
        UsdGeom.Imageable(setup).MakeInvisible()
        for name, url in (("WalkSrc", WALK), ("IdleSrc", IDLE)):
            stage.DefinePrim(f"{rig}/{name}").GetReferences().AddReference(url)
    _retag_source(stage, f"{rig}/BipedSetup/biped_demo_meters/Root")
    stage.DefinePrim(out_parent, "Scope")
    omni.kit.commands.execute(
        "CreateRetargetAnimationsCommand",
        source_skeleton_path=f"{rig}/BipedSetup/biped_demo_meters/Root",
        target_skeleton_path=target_skeleton,
        source_animation_paths=[f"{rig}/WalkSrc", f"{rig}/IdleSrc"],
        target_animation_parent_path=out_parent,
        set_root_identity=True,
    )
    return [p.GetPath().pathString for p in stage.GetPrimAtPath(out_parent).GetChildren()
            if p.IsA(UsdSkel.Animation)]


def bake_loop(stage, path, walk_anim, idle_anim, walk_frames, total_frames, start=0):
    """stage の中のアニメーション（作り直したもの）から、立ち止まり（start まで）→ 歩行 → 立ち止まりの繰り返しを作る。"""
    w, i = UsdSkel.Animation(stage.GetPrimAtPath(walk_anim)), UsdSkel.Animation(stage.GetPrimAtPath(idle_anim))
    wt, it = w.GetRotationsAttr().GetTimeSamples(), i.GetRotationsAttr().GetTimeSamples()
    wp, ip = int(wt[-1] - wt[0]), int(it[-1] - it[0])
    anim = UsdSkel.Animation.Define(stage, path)
    anim.CreateJointsAttr(w.GetJointsAttr().Get())
    tr, rot, sc = anim.CreateTranslationsAttr(), anim.CreateRotationsAttr(), anim.CreateScalesAttr()
    for f in range(total_frames + 1):
        if f < start:
            src, t = i, it[0] + f % ip
        elif f <= start + walk_frames:
            src, t = w, wt[0] + (f - start) % wp
        else:
            src, t = i, it[0] + (f - start - walk_frames) % ip
        tr.Set(src.GetTranslationsAttr().Get(t), f)
        rot.Set(src.GetRotationsAttr().Get(t), f)
        s = src.GetScalesAttr().Get(t)
        if s is not None:
            sc.Set(s, f)
    return wp, ip


def add_medical_staff(stage, name, kind, route_points, speed, fps, total_frames, start=0, track=None):
    """医療スタッフの人物を 1 人置き、作り直した歩行アニメーションで経路に沿って歩かせる（start のコマで歩き出す）。
    track に list を渡すと、各コマの位置と向き（正解）を [(x, y, yaw), ...] で入れる。到着したコマなどを返す。"""
    url, skel_rel = MEDICAL[kind]
    pos, length = resample(route_points, speed, fps)
    yaw = headings(pos)
    root = UsdGeom.Xform.Define(stage, f"/Root/{name}")
    xf = UsdGeom.Xformable(root)
    xf.ClearXformOpOrder()
    t_op, r_op = xf.AddTranslateOp(), xf.AddRotateZOp()
    for f in range(total_frames + 1):
        k = min(max(f - start, 0), len(pos) - 1)
        t_op.Set(Gf.Vec3d(pos[k][0], pos[k][1], 0.0), f)
        r_op.Set(yaw[k] + 90.0, f)  # 人物の正面は -Y（controlRig:forwardAxis = MINUS Y）
        if track is not None:
            track.append((float(pos[k][0]), float(pos[k][1]), float(yaw[k])))
    body = stage.DefinePrim(f"/Root/{name}/Body")
    body.GetReferences().AddReference(url)  # Z が上・メートルなので回さない
    skel = f"/Root/{name}/Body/{skel_rel}"
    anims = retarget_sources(stage, skel, f"/Root/AgentRig/Retargeted_{name}")
    walk = next(a for a in anims if "Walk" in a)
    idle = next(a for a in anims if "Idle" in a)
    loop = f"/Root/{name}/Body/{skel_rel.split('/ManRoot/')[0]}/ManRoot/{skel_rel.split('/')[2]}/WalkLoop"  # SkelRoot の内側
    periods = bake_loop(stage, loop, walk, idle, len(pos) - 1, total_frames, start)
    UsdSkel.BindingAPI.Apply(stage.GetPrimAtPath(skel)).CreateAnimationSourceRel().SetTargets([Sdf.Path(loop)])
    return start + len(pos) - 1, length, anims, periods
