"""シナリオ（templates/*.yaml、形式は docs/spec.md）を読み、空間・人の発生・EV・ゲートから Sim を組み立てる。"""

import copy
import math
import random
from pathlib import Path

import numpy as np
import yaml

from . import dists
from .characters import MODELS
from .engine import Agent, Car, Gate, Meet, Sim
from .space import ROOT, load_space, point_in_poly

TEMPLATES = ROOT / "templates"
STATE_OF_GROUP = {"reception": "reception", "lounge": "dwell", "sign": "sign_check"}
DEFAULTS = {
    "seed": 0, "fps": 30, "duration_s": 120,
    "people": {"speed": {"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9}, "models": "all",
               "group_lateral_m": 0.45},
    "gates": {}, "streams": [], "cameras": [],
    "render": {"width": 1280, "height": 720, "tint": "per_person", "props": []},
    "outputs": ["ground_truth", "frames", "tasks", "graph", "mot", "preview"],
}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_scenario(src, overrides=None):
    """ファイルの場所・テンプレートの名前・dict のどれでも。overrides は一部を上書きする dict（API・GUI から）。"""
    if isinstance(src, dict):
        spec = src
    else:
        p = Path(src)
        if not p.exists():
            p = TEMPLATES / f"{src}.yaml"
        spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    spec = deep_merge(DEFAULTS, spec)
    if overrides:
        spec = deep_merge(spec, overrides)
    apply_variant(spec)
    validate(spec)
    return spec


def apply_variant(spec):
    """variants: {A: {名前: 値}} と variant: A があれば、行き先の variant_p: 名前 の p をその値にする（A/B の比較）。"""
    v = spec.get("variants", {}).get(spec.get("variant"))
    if not v:
        return

    def walk(ds):
        for d in ds:
            if isinstance(d, dict) and d.get("variant_p") in v:
                d["p"] = v[d["variant_p"]]
    for s in spec["streams"]:
        walk(s.get("destinations", []))
    if spec.get("elevator", {}).get("alight"):
        walk(spec["elevator"]["alight"].get("destinations", []))


def validate(spec):
    space = load_space(spec["space"])
    errs = []

    def check_to(d, where):
        to = d.get("to") if isinstance(d, dict) else d
        if to is None:
            errs.append(f"{where}: to がない")
            return
        if to != "elevator" and to not in space.pois and not any(k.startswith(to + "_") for k in space.pois):
            errs.append(f"{where}: 行き先 {to} が空間 {space.name} にない")
        if isinstance(d, dict):
            for g in d.get("via", []):
                if g not in space.pois:
                    errs.append(f"{where}: ゲート {g} がない")
            if d.get("then"):
                check_to(d["then"], where + ".then")

    for i, s in enumerate(spec["streams"]):
        if s.get("origin") not in space.pois:
            errs.append(f"streams[{i}]: origin {s.get('origin')} がない")
        for j, d in enumerate(s.get("destinations", [])):
            check_to(d, f"streams[{i}].destinations[{j}]")
    ev = spec.get("elevator")
    if ev:
        for c in ev.get("cars", []):
            if c not in space.pois:
                errs.append(f"elevator: 扉 {c} がない")
        for j, d in enumerate(ev.get("alight", {}).get("destinations", [])):
            check_to(d, f"elevator.alight.destinations[{j}]")
    for c in spec["cameras"]:
        if "eye" not in c and c.get("name") not in space.spec.get("cameras", {}):
            errs.append(f"cameras: {c.get('name')} に eye・target がなく、空間の候補にもない")
    if errs:
        raise ValueError("シナリオの誤り:\n  " + "\n  ".join(errs))


def wait_spots(space, poi):
    """EV 待ちの場所の格子（ゾーンの中・歩ける・壁から 0.3 m・扉の前の通り道を空ける）。"""
    poly = space.zones[poi["zone"]]
    sp = float(poi.get("spacing", 0.6))
    aisle = float(poi.get("door_aisle", 0.5))
    doors = [(tuple(map(float, p["xy"])), tuple(map(float, p["face"]))) for p in space.pois.values() if p.get("kind") == "elevator"]
    xs, ys = [q[0] for q in poly], [q[1] for q in poly]
    out = []
    for x in np.arange(min(xs) + sp / 2, max(xs), sp):
        for y in np.arange(min(ys) + sp / 2, max(ys), sp):
            x, y = float(x), float(y)
            if not point_in_poly(poly, x, y) or not space.walkable(x, y) or space.clearance(x, y) < 0.3:
                continue
            bad = False
            for (dx, dy), (fx, fy) in doors:
                out_dir = np.array([dx - fx, dy - fy]) / max(math.hypot(dx - fx, dy - fy), 1e-9)  # 扉から広間へ
                rel = np.array([x - dx, y - dy])
                ahead, lat = float(rel @ out_dir), abs(float(rel @ np.array([-out_dir[1], out_dir[0]])))
                if -0.2 < ahead < 2.5 and lat < aisle or math.hypot(*rel) < 0.8:
                    bad = True
            if not bad:
                out.append((round(x, 2), round(y, 2)))
    return out


class Builder:
    def __init__(self, spec):
        self.spec = spec
        self.space = load_space(spec["space"])
        self.rng = random.Random(spec["seed"])
        self.n = 0
        self.group_n = 0
        models = spec["people"]["models"]
        self.models = list(MODELS) if models == "all" else list(models)
        ev = spec.get("elevator") or {}
        self.ev_zone = None
        for k, p in self.space.pois.items():
            if p.get("kind") == "wait_zone":
                self.ev_zone = p["zone"]
                self.ev_poi = p

    # ---- 行き先 → 段取り ----
    def resolve_to(self, to):
        if to == "elevator" or to in self.space.pois:
            return to
        cands = sorted(k for k in self.space.pois if k.startswith(to + "_"))
        return self.rng.choice(cands)

    def plan_for(self, d, comp=None):
        """行き先の指定（dict か名前）→ 段取りの列。comp は同行者（待ち合わせ）を作るときの情報を返す list。"""
        if isinstance(d, str):
            d = {"to": d}
        sp = self.space
        steps = [("gate", g) for g in d.get("via", [])]
        to = d["to"]
        group = to
        name = self.resolve_to(to)
        if name == "elevator":
            poly = sp.zones[self.ev_zone]
            c = (float(np.mean([q[0] for q in poly])), float(np.mean([q[1] for q in poly])))
            steps += [("walk", c, "pass", {"until_zone": self.ev_zone}), ("wait_ev", d.get("glance", 20.0))]
            return steps
        poi = sp.poi(name)
        kind = poi.get("kind")
        xy = sp.poi_xy(name)
        if kind in ("exit", "spawn"):
            steps += [("walk", xy, "pass"), ("exit",)]
            return steps
        face = tuple(poi["face"]) if "face" in poi else None
        state = d.get("state") or STATE_OF_GROUP.get(group.split("_")[0], "dwell")
        steps.append(("walk", xy, "pass"))
        meet = d.get("meet")
        if meet and comp is not None and self.rng.random() < meet.get("p", 1.0):
            m = Meet(set())
            comp.append({"meet": m, "spec": meet, "xy": xy, "face": face, "then": d.get("then")})
            steps.append(("meet", m, face, "companion_wait", d.get("glance", 45.0)))
        else:
            steps.append(("stop", float(dists.sample(d.get("dwell", 10.0), self.rng)), face, state, d.get("glance", 0.0)))
        if d.get("then"):
            steps += self.plan_for(d["then"])
        return steps

    def pick_destination(self, dests, typ):
        ok = [d for d in dests if not d.get("types") or typ in d["types"]]
        if not ok:
            ok = dests
        w = [float(d.get("p", 1.0)) for d in ok]
        r = self.rng.random() * sum(w)
        for d, wi in zip(ok, w):
            r -= wi
            if r <= 0:
                return d
        return ok[-1]

    def new_agent(self, plan, t0, origin_xy, speed, l_pref, group, info):
        self.n += 1
        name = f"P{self.n:04d}"
        model = self.rng.choice(self.models)
        kind, height = MODELS[model]
        inf = {"model": model, "kind": kind, "height_m": height, "origin_xy": tuple(origin_xy), "tint_index": self.n}
        inf.update(info)
        return Agent(name, plan, t0, speed, l_pref, group=group, info=inf)

    def spawn_group(self, sim, t0, origin, dests, typ_spec, size_spec, stream, origin_xy=None):
        typ = dists.sample(typ_spec, self.rng) if typ_spec else "person"
        d = self.pick_destination(dests, typ)
        size = int(dists.sample(size_spec, self.rng)) if size_spec else 1
        group = None
        if size > 1:
            self.group_n += 1
            group = f"G{self.group_n:03d}"
        speeds = [float(dists.sample(self.spec["people"]["speed"], self.rng)) for _ in range(size)]
        speed = min(speeds)
        lat = self.spec["people"]["group_lateral_m"]
        oxy = origin_xy or self.space.poi_xy(origin)
        comp = []
        base_plan = self.plan_for(d, comp)
        made = []
        for k in range(size):
            l_pref = (k - (size - 1) / 2) * lat if size > 1 else self.rng.uniform(-0.3, 0.3)
            plan = base_plan if k == 0 else self.plan_for_copy(base_plan)
            a = self.new_agent(plan, t0 + k * self.rng.uniform(0.0, 0.4), oxy, speed if size > 1 else speeds[0], l_pref, group,
                               {"type": typ, "stream": stream, "destination": d["to"], "origin": origin})
            made.append(a)
        for c in comp:  # 待ち合わせ: 先に来た人（グループ全員）と、あとから来る同行者
            for a in made:
                c["meet"].members.add(a.name)
            cs = c["spec"]
            delay = float(dists.sample(cs.get("delay", {"type": "uniform", "min": 8, "max": 25}), self.rng))
            corigin = cs.get("from", origin)
            cplan = [("gate", g) for g in cs.get("via", [])] + [("walk", c["xy"], "pass"), ("meet", c["meet"], c["face"], "companion_wait", 0.0)]
            if c["then"]:
                cplan += self.plan_for(c["then"])
            first = made[0]
            ca = self.new_agent(cplan, t0 + delay, self.space.poi_xy(corigin), speed, 0.3, group or f"G{self.group_n + 1:03d}",
                                {"type": typ, "stream": stream, "destination": d["to"], "origin": corigin, "role": "companion"})
            if group is None:
                self.group_n += 1
                for a in made:
                    a.group = ca.group
            c["meet"].members.add(ca.name)
            made.append(ca)
        for a in made:
            sim.add(a)
        return made

    def plan_for_copy(self, plan):
        return list(plan)  # 段取りの要素は共有してよい（Meet は同じものを指す）

    # ---- EV ----
    def schedule(self, cars, ev, total_s):
        sch = ev.get("schedule", {"type": "interval", "interval": {"type": "uniform", "min": 35, "max": 60}})
        if sch.get("type", "interval") == "interval":
            for c in cars:
                t = float(dists.sample(sch.get("offset", {"type": "uniform", "min": 3, "max": 30}), self.rng))
                while t < total_s:
                    c.arrivals.append(round(t, 2))
                    t += float(dists.sample(sch["interval"], self.rng))
        elif sch["type"] == "times":
            for c in cars:
                c.arrivals = [float(x) for x in sch.get("times", {}).get(c.name, [])]

    def on_demand_policy(self, ev):
        """待つ人がいて、どの号機も travel_s 以内に着く予定がなければ、いちばん早く呼べる号機を呼ぶ（簡単な運行の例）。"""
        sch = ev["schedule"]
        busy_until = {}

        def policy(sim, t):
            if not sim.queue:
                return
            soon = [x for c in sim.cars for x in c.arrivals if t <= x <= t + float(sch.get("max_wait_s", 60))]
            if soon:
                return
            free = [c for c in sim.cars if busy_until.get(c.name, -1) <= t]
            if not free:
                return
            c = self.rng.choice(free)
            x = t + float(dists.sample(sch.get("travel_s", {"type": "uniform", "min": 10, "max": 40}), self.rng))
            c.arrivals.append(round(x, 2))
            busy_until[c.name] = x + float(sch.get("dwell_s", 8))
        return policy

    def build(self):
        spec, sp = self.spec, self.space
        fps = int(spec["fps"])
        total = int(round(spec["duration_s"] * fps))
        gates = {}
        for k, p in sp.pois.items():
            if p.get("kind") == "gate":
                gates[k] = Gate(k, p, float(spec["gates"].get(k, {}).get("service_s", 1.5)))
        ev = spec.get("elevator")
        cars, spots, policy, on_arrival = [], [], None, None
        if ev:
            for c in ev["cars"]:
                p = sp.poi(c)
                cars.append(Car(c, tuple(p["xy"]), tuple(p["face"]), int(ev.get("capacity", 8))))
            spots = wait_spots(sp, self.ev_poi)
            if ev.get("schedule", {}).get("type") == "on_demand":
                policy = self.on_demand_policy(ev)
            else:
                self.schedule(cars, ev, spec["duration_s"])
            alight = ev.get("alight")
            if alight:
                def on_arrival(sim, car, t, alight=alight):
                    n = int(dists.sample(alight.get("count", {"type": "poisson", "lam": 1.0}), self.rng))
                    names = []
                    door = np.array(car.door)
                    out_dir = door - np.array(car.inside)
                    out_dir /= max(np.linalg.norm(out_dir), 1e-9)
                    for k in range(n):
                        typ = dists.sample(alight.get("types"), self.rng) if alight.get("types") else "person"
                        d = self.pick_destination(alight["destinations"], typ)
                        plan = [("walk", tuple(door + out_dir * 3.0), "alight")] + self.plan_for(d)  # 扉から 3 m 出るまでは降車
                        oxy = door + out_dir * (0.4 + 0.5 * k) + np.array([-out_dir[1], out_dir[0]]) * self.rng.uniform(-0.3, 0.3)
                        a = self.new_agent(plan, t + 0.5 + 0.8 * k, oxy, float(dists.sample(spec["people"]["speed"], self.rng)),
                                           self.rng.uniform(-0.3, 0.3), None,
                                           {"type": typ, "stream": "alight", "destination": d["to"] if isinstance(d, dict) else d,
                                            "origin": car.name, "alight_zones": (self.ev_zone,)})
                        a.state = "alight"
                        sim.add(a)
                        names.append(a.name)
                    return names
        sim = Sim(sp, fps, total, gates, cars, spots, on_arrival=on_arrival, elevator_policy=policy)
        for s in spec["streams"]:
            for t0 in dists.arrival_times(s["rate"], spec["duration_s"], self.rng, float(s.get("start_s", 0.0))):
                self.spawn_group(sim, t0, s["origin"], s["destinations"], s.get("types"), s.get("group_size"), s.get("name", s["origin"]))
        return sim


def build(spec):
    b = Builder(spec)
    return b.build(), b
