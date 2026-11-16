"""行動の目的になる部品（1.2、docs/roadmap.md の 1.2 の 2）: 窓口（service）・呼び出し（call）・座る場所（seats）・部屋（room）。

engine.Sim が ComponentsMixin を継ぐ（motion_model "cfsm" でも "lane" でも動く）。場所の形は空間（space.yaml の pois）、ふるまいの値は設定（services・rooms）。

段取り（Agent.plan の要素）:
  ("service", 名前, 応対の秒（None なら窓口の分布から）, 見回す角度)  列に並ぶ（呼び出しなら待つ場所で待つ）→ 空いた応対の場所へ歩く → 応対を受ける
  ("room", 名前, いる秒（None なら部屋の分布から）)                  扉まで歩く（定員が埋まっていれば扉の近く、呼び出しなら待つ場所で待つ）→ 中へ入る
                                                                    （映らない。状態 in_room）→ 時間がたつと同じ番号で出てくる
  ("seat", 名前, 秒, 状態, 見回す角度)                                空いた席へ歩いて座る（埋まっていれば近くに立つ）→ 時間がたつと立つ
グループは 1 組で動く: 窓口は先導の人だけが応対を受け、仲間は近く（待つ場所があれば隣の席）で待つ（状態 companion_wait）。部屋には一緒に入って一緒に出る。
状態: service_queue（窓口の列・部屋の扉の前で待つ）・service（応対中）・call_wait（呼ばれるのを待つ）・seated（座っている）・in_room（部屋の中）。
座る・立つ動作は素材（SitAndStandChair）の体の軌跡どおりに動く（play）。Agent.sit_spans は [座り始め, 座った, 立ち始め, 立ち終わり] のコマで、
正解の people[].sit と frames.csv の pose（sit_down・sit・stand_up）になる（outputs.py）。
"""

import math

import numpy as np

from . import dists

INF = math.inf
LINE_GAP = 0.65  # 窓口の列の前後の間隔（m。ゲートの列 QUEUE_GAP と同じ）
SERVICE_NEAR_M = 0.4  # 応対の場所からこの距離（m）の中に着いたら応対を受ける
COMPANION_BACK_M = 1.5  # 窓口・部屋で先導の人を待つ仲間が立つ所（応対の場所・扉から手前へ。m）
WALL_PREF = 2.0  # 立って待つ所を選ぶとき、壁から 0.6 m より遠い分 1 m あたり、近さに足す重み（壁ぎわを先に）
# 部屋の扉（描画で開け閉めする）: 入った人は中の点で扉が閉じるまで立ってから映らなくなる（閉じ始め 0.3 秒＋閉じる 0.8 秒＋余り）。
# 出る人は中の点に現れ、扉が開き切ってから歩き出す（扉が開いている間に人が中で消える・現れると、扉を正面から見るカメラで見えた。
# isaac_bridge.DOOR_OPEN と合わせる、2026-11-16）
ROOM_DOOR_IN_S, ROOM_DOOR_OUT_S = 1.3, 0.8
ROOM_MATE_SIDE_M = 0.6  # 部屋の中で、仲間が立つ所の中の点からの横のずれ（m）
SEAT_MOVE_M_S = 0.5  # 席の前から席へ・席から前へ移る速さ（m/s。座る・立つ動作の代わり。人の動きの決まりは通さない）
SEAT_APPROACH_M = 0.6  # 席の前の、歩いて着く点までの距離（m。そこから席へまっすぐ入る。席は歩ける所から外す（space.SEAT_BLOCK_M）ので、その外）
SIT_SEAT_M, SIT_TRUNK = 0.42, 0.53  # 座った人の頭の高さ = 座面の高さ + 背の高さ × 座高の比（座高は背の高さの 5 割強）
# 座る・立つ動作（描画の座る動きと同じ素材の体の動き。2026-11-16）: NVIDIA Isaac Sim の People の SitAndStandChair（MotionLibrary/BuiltinActions/Sit、
# 30 コマ/秒、CC BY 4.0）の、体（骨格の元の関節）の軌跡。席の向きの座標で (素材のコマ, 座った腰から前への距離 m, 席の向きとの差 度, 腰の高さ m)、2 コマおき。
# 座る 62〜156 コマ: 1.26 m 手前から歩いて来て左回りに振り向き（〜110）、0.2 m 手前から後ろへ腰を下ろす。立つ 266〜332 コマ: 腰を上げて前へ 0.42 m。
# 描画（isaac/render.py）は素材の体の前後の動きと向きを外して、人の位置と向き（この軌跡から作った正解）で動かすので、正解の位置と描いた体がずれない
SIT_CLIP = {"down": [62, 156], "loop": [156, 266], "up": [266, 332], "fps": 30,
            "source": "Isaac/6.1/Isaac/People/MotionLibrary/BuiltinActions/Sit/SitAndStandChair.usd"}
SIT_DOWN_TRACK = [
    (62, 1.263, -168.5, 0.968), (64, 1.208, -164.6, 0.963), (66, 1.154, -158.8, 0.954), (68, 1.102, -152.8, 0.944), (70, 1.057, -146.2, 0.943),
    (72, 1.018, -139.7, 0.943), (74, 0.975, -131.9, 0.949), (76, 0.928, -122.5, 0.956), (78, 0.878, -112.3, 0.962), (80, 0.824, -102.1, 0.964),
    (82, 0.767, -92.3, 0.954), (84, 0.706, -78.9, 0.936), (86, 0.636, -69.7, 0.914), (88, 0.57, -63.4, 0.909), (90, 0.511, -56.6, 0.911),
    (92, 0.459, -48.6, 0.912), (94, 0.414, -42.2, 0.909), (96, 0.375, -35.9, 0.905), (98, 0.34, -29.2, 0.895), (100, 0.307, -23.2, 0.877),
    (102, 0.278, -17.5, 0.853), (104, 0.252, -12.3, 0.824), (106, 0.231, -7.9, 0.787), (108, 0.214, -4.6, 0.745), (110, 0.198, -2.2, 0.704),
    (112, 0.182, -0.4, 0.665), (114, 0.163, 0.8, 0.632), (116, 0.142, 1.8, 0.605), (118, 0.118, 2.7, 0.58), (120, 0.094, 3.1, 0.563),
    (122, 0.074, 3.3, 0.562), (124, 0.059, 3.0, 0.563), (126, 0.046, 2.4, 0.559), (128, 0.034, 1.6, 0.552), (130, 0.024, 0.8, 0.549),
    (132, 0.015, 0.5, 0.547), (134, 0.008, 0.6, 0.544), (136, 0.003, 0.9, 0.54), (138, -0.001, 1.5, 0.537), (140, -0.006, 2.3, 0.535),
    (142, -0.012, 3.0, 0.534), (144, -0.015, 3.3, 0.533), (146, -0.015, 3.2, 0.531), (148, -0.01, 2.4, 0.53), (150, -0.006, 1.4, 0.528),
    (152, -0.003, 0.8, 0.528), (154, -0.003, 0.3, 0.527), (156, -0.005, 0.1, 0.525)]
STAND_UP_TRACK = [
    (266, -0.009, 0.7, 0.524), (268, -0.011, 0.9, 0.525), (270, -0.011, 1.0, 0.526), (272, -0.011, 1.1, 0.526), (274, -0.011, 1.2, 0.527),
    (276, -0.011, 1.3, 0.528), (278, -0.01, 1.5, 0.529), (280, -0.007, 1.7, 0.53), (282, -0.004, 1.9, 0.531), (284, 0.001, 2.0, 0.532),
    (286, 0.007, 2.0, 0.533), (288, 0.013, 2.0, 0.534), (290, 0.018, 1.9, 0.534), (292, 0.022, 1.9, 0.534), (294, 0.025, 2.1, 0.535),
    (296, 0.03, 2.2, 0.535), (298, 0.034, 2.2, 0.535), (300, 0.041, 2.0, 0.534), (302, 0.051, 1.5, 0.532), (304, 0.063, 0.5, 0.531),
    (306, 0.078, -0.6, 0.533), (308, 0.096, -1.8, 0.544), (310, 0.114, -2.7, 0.566), (312, 0.133, -3.5, 0.599), (314, 0.153, -3.9, 0.645),
    (316, 0.173, -4.3, 0.696), (318, 0.195, -4.4, 0.747), (320, 0.219, -3.9, 0.795), (322, 0.248, -2.7, 0.839), (324, 0.282, -1.2, 0.879),
    (326, 0.319, 0.1, 0.912), (328, 0.356, 1.3, 0.939), (330, 0.389, 2.1, 0.955), (332, 0.416, 2.7, 0.962)]
TURN_END_FWD = 0.198  # 素材で振り向き終わる所（110 コマ、座った腰の 0.2 m 前）。そこより手前の歩いて来る分は、席の前の点（SEAT_APPROACH_M）からに縮める
PELVIS_SIT, PELVIS_STAND = 0.525, 0.962  # 素材の腰の高さ（座った・立った。体の枠の高さを、座る・立つ途中で間を取るのに使う）


def _clip_at(track, c):
    """素材のコマ c（小数）の (前への距離, 向きの差, 腰の高さ)。表の間は直線で補う。"""
    c = min(max(c, track[0][0]), track[-1][0])
    for (c0, *v0), (c1, *v1) in zip(track, track[1:]):
        if c <= c1:
            u = (c - c0) / (c1 - c0)
            return tuple(a + (b - a) * u for a, b in zip(v0, v1))
    return tuple(track[-1][1:])


def sit_clip_frame(f, span, fps):
    """コマ f の素材のコマ（座る動作の中でなければ None）。span は people[].sit の 1 つ [座り始め, 座った, 立ち始め, 立ち終わり]。
    render.py の sit_clip_time と同じ決め方（座っている間は、ここでは loop の始まりのコマで代表する）。"""
    d0, s0, s1, u1 = span
    if not d0 <= f <= u1:
        return None
    if f < s0:
        a, b = SIT_CLIP["down"]
        return a + (f - d0) * (b - a) / max(1, s0 - d0)
    if f <= s1:
        return float(SIT_CLIP["loop"][0])
    a, b = SIT_CLIP["up"]
    return a + (f - s1) * (b - a) / max(1, u1 - s1)


SIT_REACH_M = 0.5  # 座った人の膝・足の先の、腰からの前への距離（m。描画の座る動き: 腿 0.45 m ＋足）


def box_shape(p, f, fps, height, yaw):
    """正解の枠の形: people[名前]（sit）とコマ f → (枠の高さ m, 前へ出る膝・足の先 (dx, dy) か None)。
    座っている間は座った高さ（SIT_SEAT_M + SIT_TRUNK × 背の高さ）で、膝と足の先が SIT_REACH_M 前に出る。座る・立つ動作の間は、素材の腰の高さで間を取る。"""
    spans = p.get("sit") if isinstance(p, dict) else p
    if not spans:
        return height, None
    _, rise = sit_pose(f, spans, fps)
    if rise >= 1.0:
        return height, None
    seated = SIT_SEAT_M + SIT_TRUNK * height
    r = SIT_REACH_M * (1.0 - rise)
    return seated + rise * (height - seated), (r * math.cos(math.radians(yaw)), r * math.sin(math.radians(yaw)))


def sit_pose(f, spans, fps):
    """コマ f の姿勢（sit_down・sit・stand_up）と、立った高さを 1 とした腰の高さの割合（座る動作の外なら (None, 1.0)）。"""
    for span in spans:
        c = sit_clip_frame(f, span, fps)
        if c is None:
            continue
        if f < span[1]:
            pel, pose = _clip_at(SIT_DOWN_TRACK, c)[2], "sit_down"
        elif f <= span[2]:
            pel, pose = PELVIS_SIT, "sit"
        else:
            pel, pose = _clip_at(STAND_UP_TRACK, c)[2], "stand_up"
        return pose, min(1.0, max(0.0, (pel - PELVIS_SIT) / (PELVIS_STAND - PELVIS_SIT)))
    return None, 1.0
# 文献の値がない既定（仮。docs/validity.md の台帳）。設定の services・rooms で変える
SERVICE_S_DEFAULT = {"type": "lognormal", "median": 60.0, "sigma": 0.5, "min": 10.0, "max": 600.0}
STAY_S_DEFAULT = {"type": "lognormal", "median": 300.0, "sigma": 0.6, "min": 30.0, "max": 3600.0}


def _poly_slots(pts, gap, n):
    """折れ線 pts の始まりから gap おきの n 点（折れ線が尽きたら、最後の向きに伸ばす）。"""
    pts = [np.asarray(p, float) for p in pts]
    if len(pts) == 1:
        return [pts[0].copy() for _ in range(n)]
    out, seg, s = [], 0, 0.0
    d = pts[1] - pts[0]
    for k in range(n):
        want = k * gap
        while seg < len(pts) - 2 and want > s + float(np.hypot(*(pts[seg + 1] - pts[seg]))):
            s += float(np.hypot(*(pts[seg + 1] - pts[seg])))
            seg += 1
        d = pts[seg + 1] - pts[seg]
        L = max(float(np.hypot(*d)), 1e-9)
        out.append(pts[seg] + d / L * (want - s))
    return out


class Service:
    """窓口。points は応対を受ける人の立つ点、faces は向く点。mode: line（line の線に並ぶ）・area（wait の範囲・席で、着いた順に待つ）・
    call（呼び出し。wait の範囲・席で待ち、空いた順に呼ばれる。area との違いは状態の名前だけ）。"""

    def __init__(self, name, points, faces, service_s=None, mode="line", line=None, wait=None, rng=None, aside=None):
        self.name = name
        # 付き添いが待つ所: 点・席（seats）やゾーンの名前・なし（応対の場所の手前）
        self.aside = aside if isinstance(aside, str) else np.asarray(aside, float) if aside is not None else None
        self.points = [np.asarray(p, float) for p in points]
        self.faces = [np.asarray(f, float) for f in faces]
        self.busy = [None] * len(self.points)
        self.service_s = service_s or SERVICE_S_DEFAULT
        self.mode, self.wait, self.rng = mode, wait, rng
        self.line = [np.asarray(p, float) for p in (line or [])]
        self.queue = []
        self._slots = _poly_slots(self.line, LINE_GAP, 40) if self.line else []

    def slot(self, k):
        return self._slots[min(k, len(self._slots) - 1)] if self._slots else self.points[0]

    def sample(self):
        return max(1.0, float(dists.sample(self.service_s, self.rng)))


class Room:
    """部屋。door は扉の前（歩ける所）、inside は中の点（歩ける所の外でよい。映らない）。capacity は同時に入れる組の数。
    mode: door（扉の前で待つ）・call（wait の範囲・席で待ち、空いた順に呼ばれる）。"""

    def __init__(self, name, door, inside, capacity=1, stay_s=None, mode="door", wait=None, rng=None):
        self.name = name
        self.door, self.inside = np.asarray(door, float), np.asarray(inside, float)
        self.capacity = int(capacity)
        self.stay_s = stay_s or STAY_S_DEFAULT
        self.mode, self.wait, self.rng = mode, wait, rng
        self.queue, self.parties = [], []

    def sample(self):
        return max(1.0, float(dists.sample(self.stay_s, self.rng)))


class SeatSet:
    """座る場所。seats は [(席の点, 向き（度）), ...]。席の点は歩ける所の外（家具の中）でもよい。席の前 SEAT_APPROACH_M の点まで歩き、そこからまっすぐ座る。"""

    def __init__(self, name, seats):
        self.name = name
        self.seats = []
        for xy, yaw in seats:
            xy = np.asarray(xy, float)
            f = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
            self.seats.append((xy, float(yaw), xy + f * SEAT_APPROACH_M))
        self.taken = [None] * len(self.seats)

    def center(self):
        return np.mean([s[0] for s in self.seats], axis=0)


class ComponentsMixin:
    """Sim に足す部品の動き。Sim は self.services・self.rooms・self.seatsets（名前 → 物）と、wait の範囲（space.zones）を使う。"""

    # ---- 段取りの入口 ----
    def comp_step(self, a, t, p, step):
        kind = step[0]
        a.comp = {"step": step, "kind": kind}
        leader = self.party_leader(a, step)
        if kind == "seat":
            ss = self.seatsets[step[1]]
            near = [self.seatsets[step[1]].seats[j][0] for j, n in enumerate(ss.taken) if n is not None and self._mate(a, n)]
            self.take_seat(a, t, p, ss, step[3], step[2], near=near, glance=step[4])
            a.events.setdefault("seat", []).append([round(t, 2), None, step[1]])
            return
        if leader is not None:  # 仲間: 窓口の手前・部屋の扉の前（待つ場所があればそこ、先導の人の隣）で待つ（部屋には一緒に入る）
            a.comp.update(role="follower", leader=leader)
            obj = self.services.get(step[1]) if kind == "service" else self.rooms.get(step[1])
            lc = leader.comp or {}
            if kind == "room" and lc.get("room") is obj and lc.get("step") is step:
                # 先導の人はもう部屋へ向かった・入った: あとを追って入る（前は、前の段取りで待っていた仲間が組に入れてもらえず、
                # 先導の人が出てくるまで扉の前で最長 25 分待った、hospital_outpatient、2026-11-13）
                a.comp["room"] = obj
                self._enter_room(a, t, p, obj, lc.get("stay", obj.sample()), leader)
                return
            if kind == "service" and isinstance(obj.aside, str):  # 空間の aside が席・ゾーンの名前: そこで待つ
                self.wait_place(a, t, p, obj.aside, "companion_wait", anchor=obj.points[0], near_agent=None)
                return
            if kind == "service" and obj.aside is not None:  # 空間の aside（付き添いが待つ点）
                anchor = obj.aside
            elif kind == "service":  # 応対の場所から、向く点と逆へ 1.5 m（前は先導の人の今の位置で、入口で現れた所に立ち、後の仲間が現れられなかった）
                d = obj.points[0] - obj.faces[0]
                anchor = obj.points[0] + d / max(float(np.hypot(*d)), 1e-9) * COMPANION_BACK_M
            else:
                d = obj.door - obj.inside
                anchor = obj.door + d / max(float(np.hypot(*d)), 1e-9) * COMPANION_BACK_M
            self.wait_place(a, t, p, obj.wait if obj.mode not in ("line", "door") else None, "companion_wait", anchor=anchor, near_agent=leader)
            return
        if kind == "service":
            S = self.services[step[1]]
            a.comp.update(role="leader", obj=S, t_join=t)
            S.queue.append(a)
            a.events.setdefault("service", []).append({"name": S.name, "join": round(t, 2)})
            if S.mode == "line":
                self.to_line_slot(a, t, p, S, len(S.queue) - 1)
            else:
                self.wait_place(a, t, p, S.wait, "service_queue" if S.mode == "area" else "call_wait", anchor=S.points[0])
        elif kind == "room":
            R = self.rooms[step[1]]
            a.comp.update(role="leader", obj=R, t_join=t)
            R.queue.append(a)
            a.events.setdefault("room", []).append({"name": R.name, "join": round(t, 2)})
            if R.mode == "call":
                self.wait_place(a, t, p, R.wait, "call_wait", anchor=R.door)
            else:
                spot = self.alloc_stand(a, R.door + (R.door - R.inside) / max(float(np.hypot(*(R.door - R.inside))), 1e-9) * 0.8)
                self.walk_then(a, p, spot, "pass", lambda a, t, p: self.hold(a, t, p, "service_queue", R.door))

    def _mate(self, a, name):
        b = self.by_name.get(name)
        return b is not None and a.group is not None and b.group == a.group

    def party_leader(self, a, step):
        """a がグループの仲間（先導の人でない）で、先導の人がこの段取りをこれから・今する（済んでいない）なら、その先導の人。"""
        if a.group is None:
            return None
        gi = self.group_info.get(a.group)
        if not gi or gi["leader"] in (None, a.name):
            return None
        b = self.by_name[gi["leader"]]
        if b.mode == "done":
            return None
        return b if any(b.plan[j] is step for j in range(max(b.k, 0), len(b.plan))) else None

    def party(self, a):
        """先導の人 a と、a を待っている仲間（同じ段取り）。"""
        step = a.comp["step"]
        return [a] + [b for b in self.agents if b is not a and getattr(b, "comp", None) and b.comp.get("leader") is a and b.comp["step"] is step
                      and b.mode not in ("done", "pending")]

    # ---- 歩く・待つ ----
    def walk_then(self, a, p, target, state, fn, taper=True, straight=False, direct=False):
        """target まで歩き、着いたら fn(a, t, p) を呼ぶ。straight は歩ける所の外（部屋の中）との行き来（経路を探さず、壁を見ない）。
        direct は席への出入り: 人の動きの決まりを通さず、まっすぐ SEAT_MOVE_M_S で移る（席は壁の近くにあり、壁から離れる向きで
        席の点に届かず、0.45 m に 26 秒かかった、2026-11-13）。"""
        if straight or direct:
            a.path = self._path([tuple(map(float, p)), tuple(map(float, target))])
            a.s, a.mode, a.state, a.taper, a.l = 0.0, "walk", state, True, 0.0
            a.no_walls = True
        else:
            self.walk_to(a, p, target, state, mode="walk", taper=taper, l0=0.0)
        a.direct = direct
        a.until_zone = None
        a.on_arrive = fn

    def hold(self, a, t, p, state, face=None, glance=30.0):
        """その場で待つ（放されるまで）。"""
        a.mode, a.until, a.hold, a.direct = "stop", INF, True, False
        self.stand(a, t, p, state, tuple(face) if face is not None else None, glance)

    def next_waits_on_seat(self, a):
        """a が今座っている席の場所で、次の段取り（窓口・部屋の呼び出し・着いた順の待ち）も待つか（立ち上がらずに続ける）。"""
        seat = a.seat
        if seat is None or not a.sitting or a.k + 1 >= len(a.plan):
            return False
        nxt = a.plan[a.k + 1]
        obj = self.services.get(nxt[1]) if nxt[0] == "service" else self.rooms.get(nxt[1]) if nxt[0] == "room" else None
        if obj is None or obj.mode in ("line", "door"):
            return False
        return obj.wait == seat[0].name or (self.party_leader(a, nxt) is not None and obj.wait == seat[0].name)

    def wait_place(self, a, t, p, wait, state, anchor=None, near_agent=None):
        """待つ場所 wait（席の名前か、ゾーンの名前か、None）で待つ。席が埋まっていれば席の近く、ゾーンなら中の空いた所、None なら anchor の近くに立つ。
        もうその席の場所に座っていれば、座ったまま待つ。"""
        if wait in self.seatsets and a.seat is not None and a.seat[0].name == wait and a.sitting:
            ss, j = a.seat
            xy, yaw, _ = ss.seats[j]
            self.hold(a, t, self.here[a.name], state, xy + np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))]), 15.0)
            return
        if wait in self.seatsets:
            ss = self.seatsets[wait]
            near = []
            if near_agent is not None and getattr(near_agent, "seat", None) is not None and near_agent.seat[0] is ss:
                near = [ss.seats[near_agent.seat[1]][0]]
            self.take_seat(a, t, p, ss, state, INF, near=near)
            return
        if wait in self.space.zones:
            poly = self.space.zones[wait]
            c = np.mean(np.asarray(poly, float), axis=0)
            spot = self.free_spot(a, c if near_agent is None or near_agent.xy is None else near_agent.xy)
        else:
            target = anchor if anchor is not None else p
            spot = self.alloc_stand(a, tuple(map(float, target)))
        face = anchor
        self.walk_then(a, p, spot, "pass", lambda a, t, p: self.hold(a, t, p, state, face))

    def to_line_slot(self, a, t, p, S, k):
        a.comp["slot"] = k
        a.link_key = f"queue:{S.name}"  # 列の前後の人を結ぶ線（engine._update_formation）。自分の列の線はよけない
        q = S.slot(k)
        if not self.space.walkable(*q):
            q = np.asarray(self.alloc_stand(a, tuple(S.slot(max(0, k - 1)))), float)
        self.walk_then(a, p, q, "service_queue", lambda a, t, p: self.hold(a, t, p, "service_queue", S.points[0], 0.0))

    # ---- 座る ----
    def take_seat(self, a, t, p, ss, state, dur, near=(), glance=20.0):
        """空いた席へ歩いて座り、座ってから dur 秒（INF なら放されるまで）。席が埋まっていれば、席の近くに立って dur 秒。"""
        free = [j for j, n in enumerate(ss.taken) if n is None]
        if not free:  # 席が埋まっている: 席の近くに立って待つ
            a.seat = None
            spot = self.free_spot(a, ss.center())
            self.walk_then(a, p, spot, "pass", lambda a, t, p: self._stand_wait(a, t, p, state, dur))
            return
        if near:
            j = min(free, key=lambda j: min(float(np.hypot(*(ss.seats[j][0] - q))) for q in near))
        else:
            j = min(free, key=lambda j: float(np.hypot(*(ss.seats[j][2] - np.asarray(p, float)))) + 0.3 * a.rng.random())
        ss.taken[j] = a.name
        a.seat = (ss, j)
        xy, yaw, approach = ss.seats[j]

        def sit(a, t, p):  # 席の前の点に着いた: 素材の軌跡どおりに振り向いて腰を下ろす（座る動作）→ 座る
            self.play(a, t, self.sit_down_track(a, p, xy, yaw), state, lambda a, t, p: self._sit_down(a, t, state, dur))
            a.sit_spans.append([self.frame_of(t), None, None, None])
        self.walk_then(a, p, approach, "pass", sit)

    def frame_of(self, t):
        return int(round(t * self.fps))

    def play(self, a, t, pts, state, then):
        """決まった軌跡 pts（このコマから 1 コマずつの [(x, y, 向き)]）どおりに動き、終わったら then(a, t, p)。人の動きの決まり（よける・壁）は通さない
        （座る・立つ動作、部屋の中の点で扉が閉じる・開くのを待つ間。席・部屋の中は歩ける所の外）。ほかの人からは、その場に立つ人としてよけられる。"""
        a.mode, a.until, a.hold, a.direct = "stop", INF, True, False
        a.state = state
        a.script = {"f0": self.frame_of(t), "pts": pts, "then": then}
        self.here[a.name] = np.array(pts[0][:2], float)  # 止まっている人の位置（次のコマの初めに読まれる）
        a.xy = self.here[a.name].copy()

    def sit_down_track(self, a, p, xy, yaw):
        """座る動作の軌跡: 素材の 62〜156 コマ（SIT_DOWN_TRACK）。席の向きの座標の前への距離のうち、振り向き終わる（TURN_END_FWD）より手前の
        歩いて来る分は、今いる所（席の前の点の近く）からに縮める。向きは今の向きから席の向きへ、素材の振り向きの進み具合で回す（近い向きへ）。"""
        xy, p = np.asarray(xy, float), np.asarray(p, float)
        f = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        a0 = SIT_DOWN_TRACK[0]
        start = xy + f * SEAT_APPROACH_M
        y0 = a.yaw if a.yaw is not None else yaw + 180.0
        turn = (yaw - y0 + 180.0) % 360.0 - 180.0
        c0, c1 = SIT_CLIP["down"]
        n = max(1, int(round((c1 - c0) / SIT_CLIP["fps"] * self.fps)))
        pts = []
        for k in range(n + 1):
            fwd, dyaw, _ = _clip_at(SIT_DOWN_TRACK, c0 + (c1 - c0) * k / n)
            w = 0.0
            if fwd > TURN_END_FWD:
                w = (fwd - TURN_END_FWD) / (a0[1] - TURN_END_FWD)
                fwd = TURN_END_FWD + w * (SEAT_APPROACH_M - TURN_END_FWD)
            q = xy + f * fwd + (p - start) * w  # 着いた所のずれは、振り向き終わるまでに消す
            u = (dyaw - a0[2]) / (0.0 - a0[2])
            pts.append((float(q[0]), float(q[1]), y0 + turn * u))
        return pts

    def stand_up_track(self, a, xy, yaw):
        """立つ動作の軌跡: 素材の 266〜332 コマ（STAND_UP_TRACK）。腰を上げて席の前へ 0.42 m。"""
        xy = np.asarray(xy, float)
        f = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        c0, c1 = SIT_CLIP["up"]
        n = max(1, int(round((c1 - c0) / SIT_CLIP["fps"] * self.fps)))
        pts = []
        for k in range(n + 1):
            fwd, dyaw, _ = _clip_at(STAND_UP_TRACK, c0 + (c1 - c0) * k / n)
            q = xy + f * fwd
            pts.append((float(q[0]), float(q[1]), yaw + dyaw))
        return pts

    def free_spot(self, a, center, radius=6.0, gap=0.6):
        """center の近く（radius m の中）の歩ける所（壁から 0.3 m）で、ほかの人の立つ場所・立っている人から gap 以上離れた点を、近い順に探して割り当てる
        （alloc_stand の輪 2.3 m が埋まると真ん中の点を返し、席の埋まった待合で立って待つ人が同じ点に重なった、hospital_outpatient の種 7、2026-11-13）。"""
        sp = self.space
        c = np.asarray(center, float)
        others = [np.asarray(xy, float) for k, xy in self.alloc.items() if k != a.name]
        others += [self.here[b.name] for b in self.agents if b is not a and b.mode in ("stop", "meet", "wait") and b.name in self.here]
        O = np.array(others, float).reshape(-1, 2)
        i0, i1 = max(0, int((c[1] - radius - sp.y0) / sp.res)), min(sp.ny, int((c[1] + radius - sp.y0) / sp.res) + 1)
        j0, j1 = max(0, int((c[0] - radius - sp.x0) / sp.res)), min(sp.nx, int((c[0] + radius - sp.x0) / sp.res) + 1)
        ii, jj = np.nonzero(sp.grid[i0:i1, j0:j1] & (sp.clear[i0:i1, j0:j1] >= 0.3))
        pts = np.stack([sp.x0 + (jj + j0) * sp.res, sp.y0 + (ii + i0) * sp.res], 1)
        d = np.hypot(*(pts - c).T)
        # 壁ぎわを先に（通路の真ん中に立つと、待合の島の南の通路をふさぎ、呼ばれた人が出られなかった、2026-11-13）
        score = d + WALL_PREF * np.maximum(0.0, sp.clear[i0:i1, j0:j1][ii, jj] - 0.6)
        for k in np.argsort(score):
            if d[k] > radius:
                continue
            q = pts[k]
            if len(O) and float(np.hypot(*(O - q).T).min()) < gap:
                continue
            self.alloc[a.name] = (float(q[0]), float(q[1]))
            return self.alloc[a.name]
        return self.alloc_stand(a, tuple(c))

    def _stand_wait(self, a, t, p, state, dur):
        self.hold(a, t, p, state)
        a.until = t + dur

    def _sit_down(self, a, t, state, dur):
        ss, j = a.seat
        xy, yaw, _ = ss.seats[j]
        f = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        self.hold(a, t, xy, state, xy + f, 0.0)  # 座っている間は見回さない（体ごと回ると、脚が隣の席・肘掛けを横切った、2026-11-16）
        a.yaw = yaw  # 座る動作の終わりの向きのまま（hold の向きへゆっくり回り直さない）
        a.until = t + dur
        a.sitting = True
        a.sit_spans[-1][1] = self.frame_of(t)
        then = getattr(a, "leave_after", None)
        if then is not None:  # 座る動作の途中で放された: 座ってすぐ立つ
            a.leave_after = None
            self.leave_seat(a, t, xy, then)

    def leave_seat(self, a, t, p, then):
        """席から立ち（立つ動作）、席の前の点まで出てから then(a, t, p)。席を取って歩いている途中なら、席を空けてそのまま then。
        座る動作の途中なら、座り終えてから立つ（動作を途中で切ると体が跳ぶ）。"""
        seat = getattr(a, "seat", None)
        if seat is None:
            a.hold = False
            then(a, t, p)
            return
        if getattr(a, "script", None) is not None:  # 座る動作の途中
            a.leave_after = then
            return
        a.hold = False
        ss, j = seat
        ss.taken[j] = None
        a.seat = None
        xy, yaw, approach = ss.seats[j]
        if a.sitting:
            a.sitting = False
            a.sit_spans[-1][2] = self.frame_of(t)

            def stood(a, t, p):
                a.sit_spans[-1][3] = self.frame_of(t)
                # 立ち終わった所（席の 0.42 m 前）は家具の近くで歩ける所の外のことがあるので、席の前の点まで出てから（席の中から経路を引けず、
                # 座りかけで放された付き添いが 848 秒動けなかった、hospital_outpatient の種 15、2026-11-13）
                self.walk_then(a, p, approach, "pass", then, direct=True)
            self.play(a, t, self.stand_up_track(a, xy, yaw), a.state, stood)
        elif getattr(a, "direct", False) or not self.space.walkable(*p):
            self.walk_then(a, p, approach, "pass", then, direct=True)
        else:
            then(a, t, p)

    # ---- 毎コマ ----
    def step_components(self, t):
        for S in self.services.values():
            for i, b in enumerate(S.busy):
                if b is not None or not S.queue:
                    continue
                a = S.queue.pop(0)
                S.busy[i] = a
                self._call(a, t, lambda a, t, p, S=S, i=i: self._go_serve(a, t, p, S, i))
                if S.mode == "line":  # 列を詰める
                    for k, b in enumerate(S.queue):
                        if b.comp.get("slot") != k:
                            self.to_line_slot(b, t, self.where(b)[0], S, k)
        for R in self.rooms.values():
            # 部屋にいる組: 扉へ・中へ歩く、中にいる、中の点で扉を待つ（stop）人がいる組
            R.parties = [pt for pt in R.parties if any(b.mode in ("away", "walk", "stop") and getattr(b, "comp", None) and b.comp.get("room") is R for b in pt)]
            while R.queue and len(R.parties) < R.capacity:
                a = R.queue.pop(0)
                pt = self.party(a)
                R.parties.append(pt)
                stay = a.comp["step"][2] if a.comp["step"][2] is not None else R.sample()
                a.comp["stay"] = stay
                for b in pt:
                    b.comp["room"] = R
                    self._call(b, t, lambda b, t, p, R=R, stay=stay, lead=a: self._enter_room(b, t, p, R, stay, lead))
        for a in self.agents:  # 仲間を待つ人: 先導の人がその段取りを済ませたら次へ
            c = getattr(a, "comp", None)
            if not c or c.get("role") != "follower" or c.get("room") is not None or c.get("released") or not a.hold and a.mode != "walk":
                continue
            lead = c["leader"]
            if lead.mode == "done" or not any(lead.plan[j] is c["step"] for j in range(max(lead.k, 0), len(lead.plan))):
                c["released"] = True  # 一度だけ（席の前へ戻る途中にもう一度放すと、席の中から次の段取りへ進み、動けなくなった、2026-11-13）
                self.leave_seat(a, t, self.where(a)[0], self._finish)

    def _call(self, a, t, go):
        """待っている人を呼ぶ: 座っていれば立ち、go(a, t, p) で次へ。"""
        a.events.setdefault("call", []).append(round(t, 2))
        p = self.where(a)[0]
        self.leave_seat(a, t, p, go)

    def _go_serve(self, a, t, p, S, i):
        a.link_key = None
        rec = a.events["service"][-1]
        rec["called"] = round(t, 2)
        a.hold = False

        def serve(a, t, p):
            if float(np.hypot(*(np.asarray(p, float) - S.points[i]))) > SERVICE_NEAR_M:  # まだ遠い（混んで手前で「着いた」ことになった）: 歩き続ける
                self.walk_then(a, p, S.points[i], "pass", serve)
                return
            dur = a.comp["step"][2] if a.comp["step"][2] is not None else S.sample()
            # 着いた所で応対を受ける（応対の点へ置き直すと、手前で止まった人が 1 コマで最大 1.4 m 跳んだ、2026-11-13）
            self.hold(a, t, p, "service", S.faces[i], a.comp["step"][3] if len(a.comp["step"]) > 3 else 0.0)
            a.until = t + dur
            a.hold = False
            rec["start"], rec["end"], rec["point"] = round(t, 2), round(t + dur, 2), i

            def done(S=S, i=i):
                S.busy[i] = None
            # 応対のあと 1 m 下がってから次へ歩くのも試したが、下がった人が列の先頭や歩く人に重なり、重なりが 0.50 → 1.72 に増えた（16 回、2026-11-13）
            a.on_done = done
        self.walk_then(a, p, S.points[i], "pass", serve)

    def _enter_room(self, a, t, p, R, stay, lead):
        a.hold = False
        a.room_in_t = None  # 中の点に着いた時刻（仲間がそろうのを待つのに使う）
        if a is lead:
            a.events["room"][-1]["called"] = round(t, 2)

        def go_in(a, t, p):
            def inside(a, t, p):  # 中の点に着いた: 扉が閉じるまで立ち（映る）、それから映らなくなる
                if getattr(R, "_exit", {}).get(id(lead)) is None:
                    R._exit = getattr(R, "_exit", {})
                    R._exit[id(lead)] = t + stay
                rec = a.events.setdefault("room", [])
                if a is not lead or not rec:
                    rec.append({"name": R.name})
                rec[-1]["enter"] = round(t, 2)
                rec[-1]["exit"] = round(max(R._exit[id(lead)], t + ROOM_DOOR_IN_S), 2)
                yaw = a.yaw if a.yaw is not None else 0.0
                q = np.asarray(p, float)  # 着いた所（中の点へ置き直すと、1 コマで最大 0.34 m 跳んだ）

                a.room_in_t, a.room_wait = t, True

                def away(a, t, p):
                    # 仲間がまだ中へ歩いている間は、扉が開いたままなので立って待つ（先に入った人が、開いた扉の向こうで消えた、2026-11-16）。
                    # 最後の仲間が着いてから ROOM_DOOR_IN_S（扉が閉じる）で全員が映らなくなる。仲間が来ないときは 30 秒まで
                    mates = self.room_mates(a, R)
                    last = max((getattr(b, "room_in_t", None) or math.inf for b in mates), default=t)
                    if t < last + ROOM_DOOR_IN_S - 1e-9 and t < a.room_in_t + 30.0:
                        self.play(a, t, [(float(p[0]), float(p[1]), a.yaw if a.yaw is not None else 0.0)] * 2, "pass", away)
                        return
                    a.mode, a.state, a.hold, a.room_wait = "away", "in_room", False, False
                    self.here[a.name] = np.asarray(p, float).copy()
                    a.until = max(R._exit[id(lead)], t)
                    a.events["room"][-1]["exit"] = round(a.until, 2)
                self.play(a, t, [(float(q[0]), float(q[1]), yaw)] * (int(round(ROOM_DOOR_IN_S * self.fps)) + 1), "pass", away)
            # 仲間は中の点から横へずらした所へ（同じ点だと、扉が閉じるまで中で立つ先の人にぶつかって着けなかった、2026-11-16）
            pt = self.room_mates(a, R)
            k = pt.index(a) if a in pt else 0
            d = np.asarray(R.inside, float) - np.asarray(R.door, float)
            side = np.array([-d[1], d[0]]) / max(float(np.hypot(*d)), 1e-9)
            target = np.asarray(R.inside, float) + side * ROOM_MATE_SIDE_M * math.ceil(k / 2) * (1 if k % 2 else -1)
            self.walk_then(a, p, target, "pass", inside, straight=True)
        self.walk_then(a, p, R.door, "pass", go_in)

    def room_mates(self, a, R):
        """a と一緒に部屋 R へ入る仲間（a を含む。先導の人が先、あとは名前の順）。呼ばれた組（R.parties）のほか、あとから先導の人を追って入る仲間も。"""
        pt = next((pt for pt in R.parties if a in pt), [a])
        same = [b for b in self.agents if b.mode != "done" and getattr(b, "comp", None) and b.comp.get("room") is R
                and (b in pt or (a.group is not None and b.group == a.group))]
        lead = pt[0] if pt else a
        return sorted(set(same) | {a}, key=lambda b: (b is not lead, b.name))

    def step_away(self, f, t):
        """部屋の中の人（映らない）: その場に記録し、時間がたったら扉へまっすぐ出てくる。"""
        for a in self.agents:
            if a.mode != "away":
                continue
            xy = self.here[a.name]
            if t >= a.until:  # このコマから映る: 中の点で扉が開き切るまで立ってから、扉へ歩く（このコマの記録は step_agents が書く）
                R = a.comp["room"]
                a.xy = np.asarray(xy, float).copy()
                d = np.asarray(R.door, float) - np.asarray(xy, float)
                yaw = math.degrees(math.atan2(d[1], d[0]))

                def out(a, t, p, R=R):
                    a.room_wait = False
                    self.walk_then(a, p, R.door, "pass", self._finish, straight=True)
                a.room_wait = True
                self.play(a, t, [(float(xy[0]), float(xy[1]), yaw)] * (int(round(ROOM_DOOR_OUT_S * self.fps)) + 1), "pass", out)
                continue
            a.frames.append((f, float(xy[0]), float(xy[1]), a.yaw if a.yaw is not None else 0.0, False))
            a.states.append("in_room")

    def _finish(self, a, t, p):
        """部品の段取りを終えて次へ。"""
        if a.comp is not None and a.comp.get("kind") == "seat" and a.events.get("seat"):
            a.events["seat"][-1][1] = round(t, 2)
        self.next_step(a, t, p)
