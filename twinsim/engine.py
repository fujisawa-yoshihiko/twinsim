"""人の動きの計算（1 コマずつ、Isaac Sim なしで動く）。
digitaltwin の hospital-sim/scripts/flow_scene_lib.py・flow_scene2_lib.py（経路に沿った歩行とよけ合い、段取りの列で動く人）を、
複数台のエレベーター・入館のゲート（レーンごとの列）・出口・壁へのめり込みの補正に広げたもの。

段取り（Agent.plan の要素）:
  ("walk", 行き先, 状態, {"until_zone": ゾーン})  行き先まで歩く（経路は空間の A*）。until_zone に入ったら次へ
  ("gate", ゲートの名前)                          列の短いレーンに並び、前の人が通ってから service_s 秒あけて通る
  ("stop", 秒, 向く点, 状態, 見回す角度)          その場で止まる
  ("meet", Meet, 向く点, 状態, 見回す角度)        待ち合わせの全員がそろうまで待つ（同行者待ち）
  ("wait_ev", 見回す角度)                         EV 待ちの場所に立ち、着いた EV に着いた順に定員まで乗る（扉で消える）
  ("exit",)                                       消える（出口・建物の外へ）
状態（1 コマごとの正解）: pass・gate_queue・ev_approach・ev_wait・alight・reception・dwell・sign_check・companion_wait
"""

import math
import random

import numpy as np

TURN_DEG_S = 90.0


class Path:
    """折れ線の経路。step m ごとの点にしておき、s（経路に沿った長さ）と l（左向きを正とする横のずれ）から位置を返す。"""

    def __init__(self, pts, step=0.25):
        pts = [tuple(map(float, p[:2])) for p in pts]
        if len(pts) == 1:
            pts = pts * 2
        dense = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            dense += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        dense.append(pts[-1])
        self.p = np.array(dense)
        seg = np.linalg.norm(np.diff(self.p, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])
        t = np.zeros_like(self.p)
        for i in range(len(self.p)):
            a, b = self.p[max(i - 2, 0)], self.p[min(i + 2, len(self.p) - 1)]
            d = b - a
            n = np.linalg.norm(d)
            t[i] = d / n if n > 1e-9 else (t[i - 1] if i else np.array([1.0, 0.0]))
        self.t = t

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        i = int(np.searchsorted(self.cum, s, side="right") - 1)
        i = min(max(i, 0), len(self.p) - 2)
        f = (s - self.cum[i]) / max(self.cum[i + 1] - self.cum[i], 1e-9)
        pos = self.p[i] + (self.p[i + 1] - self.p[i]) * f
        tan = self.t[i] * (1 - f) + self.t[i + 1] * f
        tan /= max(np.linalg.norm(tan), 1e-9)
        return pos, tan


class Meet:
    def __init__(self, members):
        self.members = set(members)
        self.arrived = set()
        self.done = False


class Agent:
    def __init__(self, name, plan, t0, speed, l_pref, group=None, info=None):
        self.name, self.plan, self.t0, self.speed, self.l_pref, self.group = name, list(plan), t0, speed, l_pref, group
        self.info = dict(info or {})  # 人物モデル・種類・流れなど（正解に書く）
        self.k = -1
        self.mode = "pending"
        self.path, self.s, self.l = None, 0.0, l_pref
        self.until, self.state, self.spot, self.until_zone = 0.0, None, None, None
        self.frames, self.states, self.events = [], [], {}
        self.yaw, self.dir = None, None
        self.base_yaw, self.glance, self.next_glance, self.glance_i = None, 0.0, 0.0, 0
        self.rng = random.Random(name)
        self.taper = False
        self.lane, self.gate_dir, self.gate_slot = None, None, None
        self.wait_glance, self.requeue = 0.0, False


class Lane:
    def __init__(self, gate, k, center):
        self.gate, self.k, self.center = gate, k, np.asarray(center, float)
        self.queue = []
        self.free_at = -1e9


class Gate:
    def __init__(self, name, spec, service_s):
        (x0, y0), (x1, y1) = spec["line"]
        n = int(spec.get("lanes", 1))
        self.name, self.service_s = name, service_s
        self.in_dir = np.asarray(spec.get("in_dir", [0.0, -1.0]), float)
        self.in_dir /= np.linalg.norm(self.in_dir)
        self.lanes = [Lane(self, k, (x0 + (x1 - x0) * (k + 0.5) / n, y0 + (y1 - y0) * (k + 0.5) / n)) for k in range(n)]
        self.lanes_in = [self.lanes[k] for k in spec.get("lanes_in", range(n))]  # 入館に使うレーン（既定はすべて）
        self.lanes_out = [self.lanes[k] for k in spec.get("lanes_out", range(n))]


class Car:
    def __init__(self, name, door, inside, capacity):
        self.name, self.door, self.inside, self.capacity = name, tuple(door), tuple(inside), capacity
        self.arrivals = []


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


class Sim:
    """sim = Sim(space, fps, total_frames, gates, cars, spots); sim.add(agent); sim.run()。
    on_arrival(sim, car, t) は EV が着いたときに呼ばれ、降りる人を足すのに使う（scenario.py が入れる）。
    elevator_policy(sim, t) は毎秒呼ばれ、EV の到着を足してよい（UC2 の運行の最適化を差し込む所）。"""

    def __init__(self, space, fps, total_frames, gates=None, cars=None, spots=None, lmax=0.6, on_arrival=None, elevator_policy=None):
        self.space, self.fps, self.total, self.dt = space, fps, total_frames, 1.0 / fps
        self.gates = gates or {}
        self.cars = cars or []
        self.spots = [tuple(s) for s in (spots or [])]
        self.free = [True] * len(self.spots)
        self.queue = []
        self.lmax = lmax
        self.agents, self.by_name, self.here = [], {}, {}
        self.on_arrival, self.elevator_policy = on_arrival, elevator_policy
        self.ev_events, self.gate_events = [], []
        self.t = 0.0
        self.alloc = {}  # 止まる人の立つ場所（名前 → (x, y)）。同じ点に何人も立たないように割り当てる

    def add(self, a):
        self.agents.append(a)
        self.by_name[a.name] = a

    # ---- 位置 ----
    def pos(self, a):
        p, t = a.path.at(a.s)
        l = a.l * min(1.0, max(0.0, a.path.length - a.s)) if a.taper else a.l
        nrm = np.array([-t[1], t[0]])
        q = p + nrm * l
        for _ in range(3):  # 壁にめり込むなら横のずれを縮める
            if self.space.walkable(q[0], q[1]):
                break
            l *= 0.5
            q = p + nrm * l
        else:
            q = p
        return q, t

    def where(self, a):
        if a.mode in ("walk", "to_spot", "board", "to_gate", "gate_pass"):
            return self.pos(a)
        y = math.radians(a.yaw or 0.0)
        return self.here[a.name], np.array([math.cos(y), math.sin(y)])

    # ---- EV 待ちの場所 ----
    def door_d(self, i):
        return min(math.hypot(self.spots[i][0] - c.door[0], self.spots[i][1] - c.door[1]) for c in self.cars) if self.cars else 0.0

    def pick_spot(self, p):
        cand = [i for i, ok in enumerate(self.free) if ok]
        if not cand:
            return None
        return min(cand, key=lambda k: self.door_d(k) + 0.3 * math.hypot(self.spots[k][0] - p[0], self.spots[k][1] - p[1]))

    def nearest_door(self, p):
        if not self.cars:
            return p
        return min((c.door for c in self.cars), key=lambda d: math.hypot(d[0] - p[0], d[1] - p[1]))

    # ---- 立つ場所 ----
    def alloc_stand(self, a, target, gap=0.65):
        """target に近く、ほかの人の立つ場所から gap m 以上離れた、歩ける所（壁から 0.2 m）を割り当てる。"""
        others = [xy for k, xy in self.alloc.items() if k != a.name]
        tx, ty = float(target[0]), float(target[1])
        cands = [(tx, ty)]
        for r in (0.7, 1.2, 1.7, 2.3):
            n = int(2 * math.pi * r / 0.6)
            off = a.rng.random() * 2 * math.pi
            cands += [(tx + r * math.cos(off + 2 * math.pi * k / n), ty + r * math.sin(off + 2 * math.pi * k / n)) for k in range(n)]
        for x, y in cands:
            if not self.space.walkable(x, y) or self.space.clearance(x, y) < 0.2:
                continue
            if all(math.hypot(x - ox, y - oy) >= gap for ox, oy in others):
                self.alloc[a.name] = (x, y)
                return (x, y)
        self.alloc[a.name] = (tx, ty)
        return (tx, ty)

    # ---- 段取り ----
    def face(self, a, t, p, q, glance):
        a.base_yaw = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) if q is not None else (a.yaw if a.yaw is not None else 0.0)
        a.glance, a.glance_i = glance, 0
        a.next_glance = t + a.rng.uniform(2.0, 4.0)

    def stand(self, a, t, p, state, q=None, glance=0.0):
        self.here[a.name] = np.asarray(p, float)
        a.state = state
        self.face(a, t, p, q, glance)

    def walk_to(self, a, p, target, state, mode="walk", taper=False, l0=None):
        a.path = Path(self.space.route(tuple(p), tuple(target)))
        a.s, a.mode, a.state, a.taper = 0.0, mode, state, taper
        a.l = a.l_pref if l0 is None else l0

    def next_step(self, a, t, p):
        if 0 <= a.k < len(a.plan) and a.plan[a.k][0] in ("stop", "meet"):
            self.alloc.pop(a.name, None)  # 止まり終えたので立つ場所を空ける
        a.k += 1
        a.until_zone = None
        if a.k >= len(a.plan):
            a.mode = "done"
            a.events["end"] = round(t, 2)
            return
        step = a.plan[a.k]
        kind = step[0]
        nxt = a.plan[a.k + 1][0] if a.k + 1 < len(a.plan) else None
        if kind == "walk":
            opts = step[3] if len(step) > 3 else {}
            target = self.alloc_stand(a, step[1]) if nxt in ("stop", "meet") else step[1]
            self.walk_to(a, p, target, step[2], taper=nxt in ("stop", "meet"), l0=a.l_pref if a.k == 0 else 0.0)
            a.until_zone = opts.get("until_zone")
        elif kind == "gate":
            g = self.gates[step[1]]
            d = 1.0 if float((g.lanes[0].center - np.asarray(p)) @ g.in_dir) > 0 else -1.0  # 入館の向きに進むか
            a.gate_dir = g.in_dir * d
            lanes = g.lanes_in if d > 0 else g.lanes_out
            lane = min(lanes, key=lambda ln: (len(ln.queue), float(np.linalg.norm(ln.center - p))))
            lane.queue.append(a)
            a.lane = lane
            self.retarget_gate(a, t, p, len(lane.queue) - 1)
        elif kind == "stop":
            a.mode, a.until = "stop", t + step[1]
            self.stand(a, t, p, step[3], step[2], step[4])
            a.events.setdefault("stops", []).append([round(t, 2), round(t + step[1], 2), step[3]])
        elif kind == "meet":
            a.mode = "meet"
            self.stand(a, t, p, step[3], step[2], step[4])
            step[1].arrived.add(a.name)
            a.events["meet_start"] = round(t, 2)
        elif kind == "wait_ev":
            a.events["hall"] = round(t, 2)
            i = self.pick_spot(p)
            a.wait_glance = step[1]
            if i is None:
                a.mode, a.spot = "wait", None
                self.stand(a, t, p, "ev_wait", self.nearest_door(p), step[1])
                self.queue.append(a)
                a.events["wait_start"] = round(t, 2)
            else:
                self.free[i] = False
                a.spot = i
                self.walk_to(a, p, self.spots[i], "ev_approach", mode="to_spot", taper=True, l0=0.0)
        elif kind == "exit":
            a.mode = "done"
            a.events["end"] = round(t, 2)
            self.alloc.pop(a.name, None)

    def retarget_gate(self, a, t, p, k):
        """列の k 番目の場所（レーンの手前 0.7 m から 0.6 m おき）へ歩く。"""
        slot = a.lane.center - a.gate_dir * (0.7 + 0.6 * k)
        a.gate_slot = k
        if math.hypot(slot[0] - p[0], slot[1] - p[1]) < 0.15:
            a.mode = "gate_wait"
            self.stand(a, t, p, "gate_queue", tuple(a.lane.center + a.gate_dir), 0.0)
            return
        near = math.hypot(slot[0] - p[0], slot[1] - p[1]) < 3.0
        a.path = Path([tuple(p), tuple(slot)]) if a.mode in ("gate_wait", "to_gate") and near else Path(self.space.route(tuple(p), tuple(slot)))
        a.s, a.mode, a.state, a.taper = 0.0, "to_gate", "pass", True
        a.l = 0.0 if k < 3 else a.l

    def step_gates(self, t):
        for g in self.gates.values():
            for lane in g.lanes:
                if not lane.queue:
                    continue
                head = lane.queue[0]
                if head.mode == "gate_wait" and t >= lane.free_at:
                    p = self.here[head.name]
                    exit_ = lane.center + head.gate_dir * 1.0
                    head.path = Path([tuple(p), tuple(lane.center), tuple(exit_)])
                    head.s, head.mode, head.state, head.taper, head.l = 0.0, "gate_pass", "pass", False, 0.0
                    lane.free_at = t + g.service_s
                    lane.queue.pop(0)
                    self.gate_events.append({"t": round(t, 2), "gate": g.name, "lane": lane.k, "person": head.name,
                                             "dir": "in" if float(head.gate_dir @ g.in_dir) > 0 else "out"})
                    head.events.setdefault("gate", []).append(round(t, 2))
                    for k, b in enumerate(lane.queue):
                        if b.mode in ("gate_wait", "to_gate"):
                            q, _ = self.where(b)
                            self.retarget_gate(b, t, q, k)

    def step_elevators(self, f, t):
        for car in self.cars:
            if f not in car._frames:
                continue
            boarded = []
            for a in self.queue[:car.capacity]:
                p, _ = self.where(a)
                if a.spot is not None:
                    self.free[a.spot] = True
                a.path, a.s, a.l, a.mode, a.state, a.taper = Path([tuple(p), car.door]), 0.0, 0.0, "board", "ev_wait", True
                a.events["board_start"] = round(t, 2)
                a.events["car"] = car.name
                boarded.append(a.name)
            self.queue = self.queue[car.capacity:]
            for a in self.queue:  # 残った人は扉に近い空いた場所へ詰める
                p, _ = self.where(a)
                i = self.pick_spot(p)
                if i is None or (a.spot is not None and self.door_d(i) > self.door_d(a.spot) - 0.5):
                    continue
                if a.spot is not None:
                    self.free[a.spot] = True
                self.free[i] = False
                a.spot = i
                self.walk_to(a, p, self.spots[i], "ev_wait", mode="to_spot", taper=True, l0=0.0)
                a.requeue = True
            alighted = self.on_arrival(self, car, t) if self.on_arrival else []
            self.ev_events.append({"t": round(t, 2), "car": car.name, "boarded": boarded, "alighted": alighted})

    def run(self):
        for car in self.cars:
            car._frames = {int(round(x * self.fps)) for x in car.arrivals}
        for f in range(self.total):
            t = f * self.dt
            self.t = t
            if self.elevator_policy and f % self.fps == 0:
                before = {c.name: len(c.arrivals) for c in self.cars}
                self.elevator_policy(self, t)
                for c in self.cars:
                    if len(c.arrivals) != before[c.name]:
                        c._frames = {int(round(x * self.fps)) for x in c.arrivals}
            for a in self.agents:
                if a.mode == "pending" and t >= a.t0:
                    a.events["start"] = round(t, 2)
                    self.next_step(a, t, a.info["origin_xy"])
            self.step_elevators(f, t)
            self.step_gates(t)
            self.step_agents(f, t)
        return self

    def step_agents(self, f, t):
        dt = self.dt
        active = [a for a in self.agents if a.mode in ("walk", "to_spot", "board", "stop", "meet", "wait", "to_gate", "gate_wait", "gate_pass")]
        P = {id(a): self.where(a) for a in active}
        for a in active:
            p, tan = P[id(a)]
            if a.mode in ("stop", "meet", "wait", "gate_wait"):
                a.dir = None
                if a.glance and t >= a.next_glance:
                    a.glance_i += 1
                    a.next_glance = t + a.rng.uniform(1.5, 3.5)
                goal = a.base_yaw + a.glance * (0, 1, 0, -1)[a.glance_i % 4]
                cur = a.yaw if a.yaw is not None else goal
                a.yaw = cur + max(-TURN_DEG_S * dt, min(TURN_DEG_S * dt, _wrap(goal - cur)))
                a.frames.append((f, float(p[0]), float(p[1]), a.yaw, False))
                a.states.append(a.state)
                if a.mode == "stop" and t >= a.until:
                    self.next_step(a, t, p)
                elif a.mode == "meet":
                    m = a.plan[a.k][1]
                    if not m.done and m.arrived >= m.members:
                        m.done = True
                        for name in sorted(m.members):
                            b = self.by_name[name]
                            b.events["meet_end"] = round(t, 2)
                            self.next_step(b, t, self.here[b.name])
                continue
            nrm = np.array([-tan[1], tan[0]])
            factor, dl = 1.0, (a.l_pref - a.l) * 0.8 * dt if a.mode == "walk" else -a.l * 2.0 * dt
            for b in active:
                if b is a:
                    continue
                mate = a.group is not None and a.group == b.group
                reach = 0.7 if mate else 1.4
                rel = P[id(b)][0] - p
                r = float(np.hypot(*rel))
                if r > reach:
                    continue
                ahead, lat = float(rel @ tan), float(rel @ nrm)
                same = b.dir is not None and float(b.dir @ tan) > 0.5
                queued = (a.mode == "to_gate" and b.lane is a.lane and b.mode in ("to_gate", "gate_wait")
                          and (b.gate_slot or 0) < (a.gate_slot or 0) and abs(lat) < 0.45)  # 同じレーンの列で自分より前の人の 0.6 m 手前で止まる
                if (same or queued) and 0 < ahead < (0.8 if mate else 1.2) and abs(lat) < (0.35 if mate else 0.6):
                    factor = min(factor, max(0.0, (ahead - 0.5) / 0.5) if mate else max(0.0, (ahead - 0.6) / 0.6))
                elif 0 < ahead < 0.6 and abs(lat) < 0.45:
                    factor = min(factor, 0.3)
                if a.mode == "gate_pass" or (a.mode == "to_gate" and a.path.length - a.s < 2.0):
                    continue  # ゲートを通る間と、列の場所の 2 m 手前からは横へよけない
                side = -1.0 if lat > 0 else 1.0 if lat < 0 else (1.0 if hash(a.name) % 2 else -1.0)
                dl += side * (reach - r) / reach * 2.0 * dt
            a.l = float(np.clip(a.l + dl, -self.lmax, self.lmax))
            step = a.speed * factor * dt
            a.s += step
            p2, tan2 = self.pos(a)
            moving = step > 0.2 * dt
            d = p2 - p
            a.dir = d / np.hypot(*d) if moving and np.hypot(*d) > 1e-6 else None
            if a.dir is not None:
                want = math.degrees(math.atan2(d[1], d[0]))
                cur = a.yaw if a.yaw is not None else want
                a.yaw = cur + max(-3 * TURN_DEG_S * dt, min(3 * TURN_DEG_S * dt, _wrap(want - cur)))
            if a.yaw is None:
                a.yaw = math.degrees(math.atan2(tan2[1], tan2[0]))
            if a.state == "alight" and self.space.zone_of(*p2) not in a.info.get("alight_zones", ()):
                a.state = "pass"
            a.frames.append((f, float(p2[0]), float(p2[1]), a.yaw, moving))
            a.states.append(a.state)
            arrived = a.s >= a.path.length - 1e-6
            if a.until_zone and self.space.zone_of(*p2) == a.until_zone:
                arrived = True
            if not arrived:
                continue
            if a.mode == "to_spot":
                a.mode = "wait"
                self.stand(a, t, p2, "ev_wait", self.nearest_door(p2), a.wait_glance)
                if not a.requeue:
                    a.events["wait_start"] = round(t, 2)
                    self.queue.append(a)
                a.requeue = False
            elif a.mode == "board":
                a.mode = "done"
                a.events["board"] = round(t, 2)
                a.events["end"] = round(t, 2)
            elif a.mode == "to_gate":
                a.mode = "gate_wait"
                self.stand(a, t, p2, "gate_queue", tuple(a.lane.center + a.gate_dir), 0.0)
            elif a.mode == "gate_pass":
                a.lane = None
                self.next_step(a, t, p2)
            else:
                self.next_step(a, t, p2)


def state_runs(states, first_frame):
    """1 コマずつの状態を [始まりのコマ, 終わりのコマ, 状態] の列に縮める。"""
    runs = []
    for k, s in enumerate(states):
        if runs and runs[-1][2] == s:
            runs[-1][1] = first_frame + k
        else:
            runs.append([first_frame + k, first_frame + k, s])
    return runs
