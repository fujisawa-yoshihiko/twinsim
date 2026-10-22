# twinsim へ写したもの（元: ~/digitaltwin/hospital-sim/scripts/crowd_lib.py、commit d99d640）。直すときは元と合わせる。
# twinsim での変更: add_track に床の高さ z を渡せるようにした（小部屋の床は z = -0.77）。
"""人を多く歩かせるための補助（人流の実験用）。demo_lib の医療スタッフの方法を、人物モデル 10 種類と「歩いている間だけ表示」に広げたもの。

- 人物モデル（Isaac/People/Characters の 10 種類）は、どれも Z が上・メートル・骨格 101 本（RL_BoneRoot から始まる同じ骨格）。
- 歩行アニメーションは、人形（biped）から骨格の変換（demo_lib.retarget_sources）で作り直す。変換は人物モデルごとに 1 回だけ。
- 歩いている間（歩き出し〜到着）だけ表示し、その前後は隠す（立ち止まりのアニメーションの表示が崩れる問題を避ける。正解も歩いている間だけ）。
- 経路は、ナビメッシュの最短経路を横に少しずらしてから歩ける所に戻したもの。人どうしはよけない（すれ違いで重なることがある）。
- 歩く速さに合わせて、歩行アニメーションの再生の速さを変える（足の滑りを減らす）。歩き出しの足の位相も人ごとにずらす。
"""

import math

from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, Vt

PEOPLE = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/People"
MODELS = {  # 人物モデル: 性別
    "F_Business_02": "F", "F_Medical_01": "F", "M_Medical_01": "M",
    "female_adult_police_01_new": "F", "female_adult_police_02": "F", "female_adult_police_03_new": "F",
    "male_adult_construction_01_new": "M", "male_adult_construction_03": "M", "male_adult_construction_05_new": "M",
    "male_adult_police_04": "M",
}
ANIM_SPEED = 1.2  # 歩行アニメーションをそのままの速さで再生したときに合う歩く速さ（m/秒）の目安


def model_url(model):
    return f"{PEOPLE}/Characters/{model}/{model}.usd"


def find_under(stage, path, schema):
    for p in Usd.PrimRange(stage.GetPrimAtPath(path)):
        if p.IsA(schema):
            return p
    return None


def offset_route(navmesh, pts, d, step=0.5):
    """経路を step m ごとの点にし、進む向きに対して横へ d m ずらしてから、ナビメッシュの歩ける所に戻す。"""
    dense = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        dense += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
    dense.append(tuple(pts[-1]))
    out = []
    for i, (x, y) in enumerate(dense):
        a, b = dense[max(i - 2, 0)], dense[min(i + 2, len(dense) - 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        n = math.hypot(tx, ty) or 1.0
        q, _ = navmesh.query_closest_point(target=(x - ty / n * d, y + tx / n * d, 0.0))
        out.append((q[0], q[1]))
    return out


class Walker:
    """人物モデルごとに作り直した歩行アニメーションを覚えておき、人を置いていく。"""

    def __init__(self, stage, demo_lib, fps):
        self.stage, self.dl, self.fps = stage, demo_lib, fps
        self.walk = {}  # 人物モデル → 作り直した歩行アニメーションの path
        self.height = {}  # 人物モデル → 背の高さ（m）

    def _walk_anim(self, model, skel_path):
        if model not in self.walk:
            anims = self.dl.retarget_sources(self.stage, skel_path, f"/Root/AgentRig/Retargeted_{model}")
            self.walk[model] = next(a for a in anims if "Walk" in a)
        return self.walk[model]

    def add(self, name, model, route_xy, speed, start, phase=0.0):
        """人を 1 人置く。start のコマで歩き出し、到着したら消える。正解（各コマの位置と向き）と情報を返す。"""
        stage = self.stage
        pos, length = self.dl.resample(route_xy, speed, self.fps)
        yaw = self.dl.headings(pos)
        n = len(pos)
        arrive = start + n - 1
        root = UsdGeom.Xform.Define(stage, f"/Root/{name}")
        xf = UsdGeom.Xformable(root)
        xf.ClearXformOpOrder()
        t_op, r_op = xf.AddTranslateOp(), xf.AddRotateZOp()
        vis = root.CreateVisibilityAttr()
        body = stage.DefinePrim(f"/Root/{name}/Body")
        body.GetReferences().AddReference(model_url(model))  # Z が上・メートルなので回さない
        skel = find_under(stage, body.GetPath(), UsdSkel.Skeleton)
        skel_root = find_under(stage, body.GetPath(), UsdSkel.Root)
        if model not in self.height:
            cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
            self.height[model] = round(float(cache.ComputeWorldBound(body).ComputeAlignedRange().GetMax()[2]), 3)
        walk = UsdSkel.Animation(stage.GetPrimAtPath(self._walk_anim(model, skel.GetPath().pathString)))
        wt = walk.GetRotationsAttr().GetTimeSamples()
        wp = wt[-1] - wt[0]
        loop = UsdSkel.Animation.Define(stage, skel_root.GetPath().AppendChild("WalkLoop"))  # SkelRoot の内側
        loop.CreateJointsAttr(walk.GetJointsAttr().Get())
        tr, rot, sc = loop.CreateTranslationsAttr(), loop.CreateRotationsAttr(), loop.CreateScalesAttr()
        rate = speed / ANIM_SPEED
        cache = {}
        track = []
        with Sdf.ChangeBlock():
            for k in range(n):
                f = start + k
                t_op.Set(Gf.Vec3d(pos[k][0], pos[k][1], 0.0), f)
                r_op.Set(yaw[k] + 90.0, f)  # 人物の正面は -Y
                t = wt[0] + round(((k * rate + phase * wp) % wp) * 4) / 4  # 0.25 コマ刻み（USD が間を補う）
                if t not in cache:
                    cache[t] = (walk.GetTranslationsAttr().Get(t), walk.GetRotationsAttr().Get(t), walk.GetScalesAttr().Get(t))
                a, b, c = cache[t]
                tr.Set(a, f)
                rot.Set(b, f)
                if c is not None:
                    sc.Set(c, f)
                track.append((round(float(pos[k][0]), 4), round(float(pos[k][1]), 4), round(float(yaw[k]), 2)))
            if start > 0:
                vis.Set(UsdGeom.Tokens.invisible, 0)
            vis.Set(UsdGeom.Tokens.inherited, start)
            vis.Set(UsdGeom.Tokens.invisible, arrive + 1)
        UsdSkel.BindingAPI.Apply(skel).CreateAnimationSourceRel().SetTargets([loop.GetPath()])
        info = {"model": model, "kind": MODELS[model], "height_m": self.height[model], "start_frame": start,
                "arrive_frame": arrive, "length_m": round(float(length), 2), "speed_m_s": round(speed, 3)}
        return info, track


STAND_T = 61.0  # 立っている姿勢に使う歩行のコマ（s79_stand_pose.py で選んだ、両足がほぼそろったコマ）
STRIDE_M = ANIM_SPEED * 80 / 30  # 歩行のアニメーション 1 周（80 コマ）で進む距離（約 3.2 m）


def add_track(walker, name, model, frames, stand_t=STAND_T, z=0.0):
    """1 コマずつの位置（flow_scene_lib の Agent.frames: (コマ, x, y, 向き, 歩いているか)）で人を置く。
    歩いている間は進んだ距離に合わせて歩行を再生し、止まっている間は立っている姿勢にする。見えるのは frames の間だけ。"""
    stage = walker.stage
    root = UsdGeom.Xform.Define(stage, f"/Root/{name}")
    xf = UsdGeom.Xformable(root)
    xf.ClearXformOpOrder()
    t_op, r_op = xf.AddTranslateOp(), xf.AddRotateZOp()
    vis = root.CreateVisibilityAttr()
    body = stage.DefinePrim(f"/Root/{name}/Body")
    body.GetReferences().AddReference(model_url(model))
    skel = find_under(stage, body.GetPath(), UsdSkel.Skeleton)
    skel_root = find_under(stage, body.GetPath(), UsdSkel.Root)
    if model not in walker.height:
        cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        walker.height[model] = round(float(cache.ComputeWorldBound(body).ComputeAlignedRange().GetMax()[2]), 3)
    walk = UsdSkel.Animation(stage.GetPrimAtPath(walker._walk_anim(model, skel.GetPath().pathString)))
    wt = walk.GetRotationsAttr().GetTimeSamples()
    wp = wt[-1] - wt[0]
    loop = UsdSkel.Animation.Define(stage, skel_root.GetPath().AppendChild("WalkLoop"))
    loop.CreateJointsAttr(walk.GetJointsAttr().Get())
    tr, rot, sc = loop.CreateTranslationsAttr(), loop.CreateRotationsAttr(), loop.CreateScalesAttr()
    cache, phase, prev, unwrap = {}, (stand_t - wt[0]) / wp, None, None
    track, moving = [], []
    with Sdf.ChangeBlock():
        for f, x, y, yaw, mv in frames:
            if unwrap is not None:  # 向きが ±180 度をまたいで回り込まないよう、連続にする
                while yaw - unwrap > 180:
                    yaw -= 360
                while yaw - unwrap < -180:
                    yaw += 360
            unwrap = yaw
            t_op.Set(Gf.Vec3d(x, y, z), f)
            r_op.Set(yaw + 90.0, f)  # 人物の正面は -Y
            if mv and prev is not None:
                phase += ((x - prev[0]) ** 2 + (y - prev[1]) ** 2) ** 0.5 / STRIDE_M
                t = wt[0] + round(((phase % 1.0) * wp) * 4) / 4
            else:
                t = stand_t
                phase = (stand_t - wt[0]) / wp  # 歩き出すときは立った姿勢から
            prev = (x, y)
            if t not in cache:
                cache[t] = (walk.GetTranslationsAttr().Get(t), walk.GetRotationsAttr().Get(t), walk.GetScalesAttr().Get(t))
            a, b, c = cache[t]
            tr.Set(a, f)
            rot.Set(b, f)
            if c is not None:
                sc.Set(c, f)
            track.append([round(x, 4), round(y, 4), round(((yaw + 180) % 360) - 180, 2)])
            moving.append(1 if mv else 0)
        first, last = frames[0][0], frames[-1][0]
        if first > 0:
            vis.Set(UsdGeom.Tokens.invisible, 0)
        vis.Set(UsdGeom.Tokens.inherited, first)
        vis.Set(UsdGeom.Tokens.invisible, last + 1)
    UsdSkel.BindingAPI.Apply(skel).CreateAnimationSourceRel().SetTargets([loop.GetPath()])
    info = {"model": model, "kind": MODELS[model], "height_m": walker.height[model], "start_frame": first, "arrive_frame": last}
    return info, track, moving
