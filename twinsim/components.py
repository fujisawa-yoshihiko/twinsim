"""行動の目的になる部品（1.2、docs/roadmap.md の 1.2 の 2）: 窓口（service）・呼び出し（call）・座る場所（seats）・部屋（room）。

engine.Sim が ComponentsMixin を継ぐ（motion_model "cfsm" でも "lane" でも動く）。場所の形は空間（space.yaml の pois）、ふるまいの値は設定（services・rooms）。

段取り（Agent.plan の要素）:
  ("service", 名前, 応対の秒（None なら窓口の分布から）, 見回す角度)  列に並ぶ（呼び出しなら待つ場所で待つ）→ 空いた応対の場所へ歩く → 応対を受ける
  ("room", 名前, いる秒（None なら部屋の分布から）)                  扉まで歩く（定員が埋まっていれば扉の近く、呼び出しなら待つ場所で待つ）→ 中へ入る
                                                                    （映らない。状態 in_room）→ 時間がたつと同じ番号で出てくる
  ("seat", 名前, 秒, 状態, 見回す角度)                                空いた席へ歩いて座る（埋まっていれば近くに立つ）→ 時間がたつと立つ
グループは 1 組で動く: 窓口は先導の人だけが応対を受け、仲間は近く（待つ場所があれば隣の席）で待つ（状態 companion_wait）。部屋には一緒に入って一緒に出る。
状態: service_queue（窓口の列・部屋の扉の前で待つ）・service（応対中）・call_wait（呼ばれるのを待つ）・seated（座っている）・in_room（部屋の中）。
座っている間は Agent.sit_spans（コマの区間）に入り、正解の pose が sit になる（outputs.py）。
"""

import math

import numpy as np

from . import dists

INF = math.inf
LINE_GAP = 0.65  # 窓口の列の前後の間隔（m。ゲートの列 QUEUE_GAP と同じ）
SERVICE_NEAR_M = 0.4  # 応対の場所からこの距離（m）の中に着いたら応対を受ける
COMPANION_BACK_M = 1.5  # 窓口・部屋で先導の人を待つ仲間が立つ所（応対の場所・扉から手前へ。m）
WALL_PREF = 2.0  # 立って待つ所を選ぶとき、壁から 0.6 m より遠い分 1 m あたり、近さに足す重み（壁ぎわを先に）
SEAT_MOVE_M_S = 0.5  # 席の前から席へ・席から前へ移る速さ（m/s。座る・立つ動作の代わり。人の動きの決まりは通さない）
SEAT_APPROACH_M = 0.6  # 席の前の、歩いて着く点までの距離（m。そこから席へまっすぐ入る。席は歩ける所から外す（space.SEAT_BLOCK_M）ので、その外）
SIT_SEAT_M, SIT_TRUNK = 0.42, 0.53  # 座った人の頭の高さ = 座面の高さ + 背の高さ × 座高の比（座高は背の高さの 5 割強）
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

        def sit(a, t, p):
            self.walk_then(a, p, xy, "pass", lambda a, t, p: self._sit_down(a, t, state, dur), direct=True)
        self.walk_then(a, p, approach, "pass", sit)

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
        self.hold(a, t, xy, state, xy + f, 15.0)
        a.until = t + dur
        a.sitting = True
        a.sit_spans.append([int(round(t * self.fps)), None])

    def leave_seat(self, a, t, p, then):
        """席から立ち、席の前の点まで出てから then(a, t, p)。席を取って歩いている途中なら、席を空けてそのまま then。"""
        seat = getattr(a, "seat", None)
        a.hold = False
        if seat is None:
            then(a, t, p)
            return
        ss, j = seat
        ss.taken[j] = None
        a.seat = None
        was = a.sitting
        if was:
            a.sitting = False
            a.sit_spans[-1][1] = int(round(t * self.fps))
        # 座っていた・席へ入る途中・歩ける所の外（席は家具）なら、席の前の点へ戻ってから（席の中から経路を引けず、座りかけで放された付き添いが
        # 848 秒動けなかった、hospital_outpatient の種 15、2026-11-13）
        if was or getattr(a, "direct", False) or not self.space.walkable(*p):
            self.walk_then(a, p, ss.seats[j][2], "pass", then, direct=True)
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
            R.parties = [pt for pt in R.parties if any(b.mode in ("away", "walk") and getattr(b, "comp", None) and b.comp.get("room") is R for b in pt)]
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
        if a is lead:
            a.events["room"][-1]["called"] = round(t, 2)

        def go_in(a, t, p):
            def inside(a, t, p):
                a.mode, a.state = "away", "in_room"
                self.here[a.name] = np.asarray(p, float).copy()  # 着いた所（中の点へ置き直すと、1 コマで最大 0.34 m 跳んだ）
                if getattr(R, "_exit", {}).get(id(lead)) is None:
                    R._exit = getattr(R, "_exit", {})
                    R._exit[id(lead)] = t + stay
                a.until = R._exit[id(lead)]
                rec = a.events.setdefault("room", [])
                if a is not lead or not rec:
                    rec.append({"name": R.name})
                rec[-1]["enter"] = round(t, 2)
                rec[-1]["exit"] = round(a.until, 2)
            self.walk_then(a, p, R.inside, "pass", inside, straight=True)
        self.walk_then(a, p, R.door, "pass", go_in)

    def step_away(self, f, t):
        """部屋の中の人（映らない）: その場に記録し、時間がたったら扉へまっすぐ出てくる。"""
        for a in self.agents:
            if a.mode != "away":
                continue
            xy = self.here[a.name]
            if t >= a.until:  # このコマから歩く（このコマの記録は step_agents が書く）
                R = a.comp["room"]
                a.xy = np.asarray(xy, float).copy()
                self.walk_then(a, xy, R.door, "pass", self._finish, straight=True)
                continue
            a.frames.append((f, float(xy[0]), float(xy[1]), a.yaw if a.yaw is not None else 0.0, False))
            a.states.append("in_room")

    def _finish(self, a, t, p):
        """部品の段取りを終えて次へ。"""
        if a.comp is not None and a.comp.get("kind") == "seat" and a.events.get("seat"):
            a.events["seat"][-1][1] = round(t, 2)
        self.next_step(a, t, p)
