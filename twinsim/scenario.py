"""シナリオ（設定。JSON か YAML、形式は docs/spec.md）を読み、空間・人の発生・EV・ゲートから Sim を組み立てる。"""

import copy
import json
import math
import random
import re
from pathlib import Path

import numpy as np
import yaml

from . import dists
from .characters import MODELS
from .engine import Agent, Car, Gate, Meet, Sim
from .literature import PROFILES, WEIDMANN_FD, lift_demand_per_min
from .space import ROOT, load_space, point_in_poly

TEMPLATES = ROOT / "templates"
STATE_OF_GROUP = {"reception": "reception", "lounge": "dwell", "sign": "sign_check"}
# 既定の値は文献から（literature.py の REFS、一覧は docs/validity.md）。people.profile を書くと、その組の値が既定になる
DEFAULTS = {
    "seed": 0, "fps": 30, "duration_s": 120,
    "people": {"speed": {"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9},  # Weidmann 1993
               "models": "all",
               "group_speed": {"model": "moussaid2010", "slope_m_s": 0.04},  # 1 人増えるごとに 0.04 m/s 遅く（Moussaïd ら 2010、低密度）
               "group_lateral_m": 0.66,  # 2 人連れの横の間隔（Zanlungo ら 2017、大阪 ATC の 1018 組の平均）
               "lateral_max_m": 1.0,  # 経路から横へよけられる幅（廊下の確かめ verify_fundamental_diagram で決めた）
               "speed_density": dict(WEIDMANN_FD)},  # 前の人の密度で遅くなる（Weidmann 1993）。null で切る
    "gates": {}, "streams": [], "cameras": [],
    "render": {"width": 1280, "height": 720, "tint": "per_person", "props": []},
    "outputs": ["ground_truth", "frames", "tasks", "graph", "mot", "aicity", "preview", "validity"],
}


OUTPUTS = ("ground_truth", "frames", "tasks", "graph", "mot", "aicity", "preview", "validity")
# 設定の一番上のキー（docs/spec.md）。綴りの誤りを既定の値のまま黙って動かさないように、ほかのキーは誤りにする
CONFIG_KEYS = set(DEFAULTS) | {"name", "title", "title_en", "description", "space", "demand", "elevator", "validity", "variants", "variant", "graph",
                               "mot_stride", "congestion_levels", "calibration"}
CAMERA_KEYS = {"name", "eye", "target", "focal_mm", "h_aperture_mm", "width", "height", "clock_offset_s", "drop_rate", "note"}
ORIGIN_FORMS = '場所の名前か、{"xy": [x, y]}・{"line": [[x0, y0], [x1, y1]]}'


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        # 分布（type を持つ dict）は丸ごと置き換える。混ぜると、既定の min・max が書いた分布を黙って切ってしまう
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and "type" not in v and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def plain(v):
    """numpy の数や Path を、JSON と YAML に書ける形にする。"""
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, Path):
        return str(v)
    return v.item() if hasattr(v, "dtype") and hasattr(v, "item") else v


def _parse_json(text, where):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{where} の JSON の誤り（{e.lineno} 行 {e.colno} 文字目）: {e.msg}") from e


def read_config(src):
    """設定を既定の値を足さずに読む。src は dict・JSON の文字列・ファイル（.json・.yaml）の場所・テンプレートの名前のどれでも。"""
    if isinstance(src, dict):
        return copy.deepcopy(src)
    text = str(src)
    if text.lstrip().startswith("{"):
        return _parse_json(text, "設定")
    p = Path(text).expanduser()
    if p.is_file():
        body = p.read_text(encoding="utf-8")
        spec = _parse_json(body, str(p)) if p.suffix == ".json" else yaml.safe_load(body)
    elif (TEMPLATES / f"{text}.yaml").is_file():
        spec = yaml.safe_load((TEMPLATES / f"{text}.yaml").read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(f"設定 {text} がない（ファイルの場所かテンプレートの名前: {', '.join(list_templates())}）")
    if not isinstance(spec, dict):
        raise ValueError(f"設定 {text} の中身が {{...}} の形ではない")
    return spec


def list_templates():
    return sorted(p.stem for p in TEMPLATES.glob("*.yaml"))


def load_scenario(src, overrides=None):
    """設定を読み、既定の値を足して確かめる。src は read_config と同じ。overrides は一部を上書きする dict（API・GUI から）。
    people.profile（literature.PROFILES）があれば、既定 → その組の値 → シナリオ → overrides の順に重ねる。"""
    spec = read_config(src)
    prof = ((overrides or {}).get("people") or {}).get("profile") or (spec.get("people") or {}).get("profile")
    base = DEFAULTS
    if prof:
        if prof not in PROFILES:
            raise ValueError(f"people.profile {prof} はない（{', '.join(PROFILES)}）")
        base = deep_merge(DEFAULTS, {"people": PROFILES[prof]["people"]})
    spec = deep_merge(base, spec)
    if overrides:
        spec = deep_merge(spec, overrides)
    spec = plain(spec)
    if "space" not in spec:
        raise ValueError("設定に space（空間の名前かフォルダの場所）がない")
    apply_variant(spec)
    normalize_streams(spec)
    validate(spec)
    return spec


load_config = load_scenario


def is_safe_name(name):
    """ファイルの名前に使う名前（設定の name・カメラの名前）か。/ や .. を通すと結果の外に書いてしまう。"""
    return isinstance(name, str) and re.fullmatch(r"[\w-]+", name) is not None


def is_xy(p):
    return (isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p))


def is_xyz(p):
    return (isinstance(p, (list, tuple)) and len(p) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p))


def origin_center(origin, pois):
    """流れの現れる所の代表の点。origin は場所の名前か {"xy": ..}・{"line": ..}。"""
    if isinstance(origin, str):
        return pois[origin]["xy"]
    if "xy" in origin:
        return list(origin["xy"])
    (x0, y0), (x1, y1) = origin["line"]
    return [(x0 + x1) / 2, (y0 + y1) / 2]


def normalize_streams(spec):
    """座標で置いた流れに名前を付け（記録と集計は、流れを名前で呼ぶ）、名前だけで書いた行き先を {"to": 名前} にそろえる。"""
    for i, s in enumerate(spec["streams"]):
        if isinstance(s.get("origin"), dict) and "name" not in s:
            s["name"] = s["origin"].get("name") or f"stream{i + 1}"
    for owner in [*spec["streams"], (spec.get("elevator") or {}).get("alight") or {}]:
        if "destinations" in owner:
            owner["destinations"] = [{"to": d} if isinstance(d, str) else d for d in owner["destinations"]]


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
    errs = [f"知らないキー {k}（使えるのは {', '.join(sorted(CONFIG_KEYS))}）" for k in spec if k not in CONFIG_KEYS]
    for k in ("duration_s", "fps"):
        if not isinstance(spec.get(k), (int, float)) or isinstance(spec.get(k), bool) or spec[k] <= 0:
            errs.append(f"{k} は正の数（今は {spec.get(k)!r}）")
    if isinstance(spec.get("fps"), float) and not spec["fps"].is_integer():
        errs.append(f"fps は正の整数（今は {spec['fps']!r}）")
    if not isinstance(spec.get("seed"), int) or isinstance(spec.get("seed"), bool):
        errs.append(f"seed は整数（今は {spec.get('seed')!r}）")  # null だと実行ごとに結果が変わる
    errs += [f"outputs に知らない名前 {o}（使えるのは {', '.join(OUTPUTS)}）" for o in spec["outputs"] if o not in OUTPUTS]
    if "aicity" in spec["outputs"] and "mot" not in spec["outputs"]:
        errs.append("outputs の aicity には mot も要る")
    stride = spec.get("mot_stride", 1)
    if not isinstance(stride, int) or isinstance(stride, bool) or stride < 1:
        errs.append(f"mot_stride は 1 以上の整数（今は {stride!r}）")
    cell = (spec.get("graph") or {}).get("cell_m", 2.0)
    if not isinstance(cell, (int, float)) or cell <= 0 or abs(cell / space.res - round(cell / space.res)) > 1e-9:
        errs.append(f"graph.cell_m は空間の格子 {space.res} m の倍数（今は {cell!r}）")
    if spec.get("variant") is not None and spec["variant"] not in (spec.get("variants") or {}):
        errs.append(f"variant {spec['variant']} が variants にない")
    errs += [f"gates: {k} はゲートの場所ではない" for k in spec["gates"] if space.pois.get(k, {}).get("kind") != "gate"]
    errs += [f"render.props: 場所 {k} がない" for k in spec["render"].get("props", []) if k not in space.pois]
    if spec.get("name") is not None and not is_safe_name(spec["name"]):
        errs.append(f"name に使えるのは文字・数字・_・- だけ（今は {spec['name']!r}）")

    def check_to(d, where):
        to = d.get("to") if isinstance(d, dict) else d
        if to is None:
            errs.append(f"{where}: to がない")
            return
        if to == "elevator":
            if not spec.get("elevator"):
                errs.append(f"{where}: 行き先 elevator には elevator の設定が要る")
        elif to not in space.pois and not any(k.startswith(to + "_") for k in space.pois):
            errs.append(f"{where}: 行き先 {to} が空間 {space.name} にない")
        if isinstance(d, dict):
            for g in [*d.get("via", []), *(d.get("meet") or {}).get("via", [])]:
                if space.pois.get(g, {}).get("kind") != "gate":
                    errs.append(f"{where}: ゲート {g} がない")
            if d.get("then"):
                if isinstance(d["then"], dict) and d["then"].get("meet"):
                    errs.append(f"{where}.then: meet は一番上の行き先にだけ書ける")
                check_to(d["then"], where + ".then")

    def check_origin(o, where):
        if isinstance(o, str):
            if o not in space.pois:
                errs.append(f"{where}: origin {o} がない（{ORIGIN_FORMS}）")
            return False
        if not isinstance(o, dict) or ("xy" in o) == ("line" in o) or set(o) - {"xy", "line", "name"}:
            errs.append(f"{where}: origin {o!r} の形が正しくない（{ORIGIN_FORMS}）")
            return False
        if "xy" in o:
            pts = [o["xy"]] if is_xy(o["xy"]) else None
        else:
            line = o["line"]
            ok = isinstance(line, (list, tuple)) and len(line) == 2 and all(is_xy(p) for p in line)
            pts = [[line[0][0] + (line[1][0] - line[0][0]) * u, line[0][1] + (line[1][1] - line[0][1]) * u] for u in (0, 0.25, 0.5, 0.75, 1)] if ok else None
        if pts is None:
            errs.append(f"{where}: origin {o!r} の座標が正しくない（{ORIGIN_FORMS}）")
            return False
        for x, y in pts:
            if not space.walkable(x, y):
                nx, ny = space.snap(x, y, 0.3)
                errs.append(f"{where}: origin の点 ({x:.2f}, {y:.2f}) は歩ける所の外（近くの歩ける所は ({nx:.2f}, {ny:.2f})）")
                return False
        return True

    def origin_ends(o):
        return [o["xy"]] if "xy" in o else o["line"]

    def check_reach(starts, names, where):
        """座標で置いた発生位置から、行き先へ歩いて行けるか（別の部屋に置くと途中で止まるので、計算の前に知らせる）。"""
        for start in starts:
            for name in names:
                if name in space.pois:
                    try:
                        space.route(start, space.poi_xy(name))
                    except ValueError:
                        errs.append(f"{where}: {start} から {name} へ歩いて行けない")

    if not isinstance(spec["streams"], list):
        errs.append("streams は配列")
    for i, s in enumerate(spec["streams"] if isinstance(spec["streams"], list) else []):
        where = f"streams[{i}]"
        placed = check_origin(s.get("origin"), where)
        rate = s.get("rate")
        if rate is None:
            errs.append(f"{where}: rate がない")
        elif isinstance(rate, dict) and rate.get("type", "constant") not in ("constant", "piecewise", "lift_demand", "times"):
            errs.append(f"{where}: rate の type {rate['type']} は使えない（constant・piecewise・lift_demand・times）")
        if not s.get("destinations"):
            errs.append(f"{where}: destinations がない")
        names = []
        for j, d in enumerate(s.get("destinations") or []):
            check_to(d, f"{where}.destinations[{j}]")
            names += [*d.get("via", []), d.get("to")] if isinstance(d, dict) else [d]
            meet = d.get("meet") if isinstance(d, dict) else None
            if meet and "from" in meet and check_origin(meet["from"], f"{where}.destinations[{j}].meet.from"):
                check_reach(origin_ends(meet["from"]), [d.get("to")], f"{where}.destinations[{j}].meet.from")
        if placed:
            check_reach(origin_ends(s["origin"]), names, where)
    ev = spec.get("elevator")
    if ev:
        if not ev.get("cars"):
            errs.append("elevator: cars がない")
        for c in ev.get("cars", []):
            if space.pois.get(c, {}).get("kind") != "elevator":
                errs.append(f"elevator: 扉 {c} がない")
        if not any(p.get("kind") == "wait_zone" for p in space.pois.values()):
            errs.append(f"elevator: 空間 {space.name} に EV を待つ場所がない")
        kind = (ev.get("schedule") or {}).get("type", "interval")
        if kind not in ("interval", "times", "on_demand"):
            errs.append(f"elevator.schedule の type {kind} は使えない（interval・times・on_demand）")
        for j, d in enumerate((ev.get("alight") or {}).get("destinations", [])):
            check_to(d, f"elevator.alight.destinations[{j}]")
            if isinstance(d, dict) and d.get("meet"):
                errs.append(f"elevator.alight.destinations[{j}]: meet は流れの行き先にだけ書ける")
    if not isinstance(spec["cameras"], list) or not all(isinstance(c, dict) for c in spec["cameras"]):
        raise ValueError("シナリオの誤り:\n  " + "\n  ".join([*errs, "cameras はカメラのオブジェクトの配列"]))
    names = [c.get("name") for c in spec["cameras"]]
    for c in spec["cameras"]:
        n = c.get("name")
        if not n:
            errs.append("cameras: name がない")
            continue
        if not is_safe_name(n):
            errs.append(f"cameras: 名前に使えるのは文字・数字・_・- だけ（今は {n!r}）")
            continue
        if names.count(n) > 1:
            errs.append(f"cameras: {n} が 2 回ある")
        errs += [f"cameras: {n} に知らないキー {k}（使えるのは {', '.join(sorted(CAMERA_KEYS))}）" for k in c if k not in CAMERA_KEYS]
        full = {**space.spec.get("cameras", {}).get(n, {}), **c}
        if not ("eye" in full and "target" in full):
            errs.append(f"cameras: {n} に eye・target がなく、空間の候補にもない")
        elif not (is_xyz(full["eye"]) and is_xyz(full["target"])):
            errs.append(f"cameras: {n} の eye・target は [x, y, z]")
        elif list(full["eye"]) == list(full["target"]):
            errs.append(f"cameras: {n} の eye と target が同じ点")
        elif space.spec.get("ceiling_m") and float(full["eye"][2]) - space.z >= float(space.spec["ceiling_m"]) - 0.05:
            # 正解の枠は天井を知らないので、天井より上のカメラでは、映っていない人に枠が付いてしまう
            errs.append(f"cameras: {n} の高さ {float(full['eye'][2]) - space.z:g} m が、空間 {space.name} の天井（{space.spec['ceiling_m']} m）以上")
    if spec["render"].get("tint") not in ("per_person", False, None):
        errs.append(f"render.tint は per_person か false（今は {spec['render'].get('tint')!r}）")
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


def resolve_rate(spec, rate, size_spec):
    """rate → arrival_times が読める形（グループ/分）と、その根拠の記録。
    rate の per_min はグループ（まとまり）の数/分。unit: persons なら人/分として、平均の人数で割る。
    type: lift_demand は demand（建物の人数・混む 5 分の割合・時間帯）から人/分を出す（Peters ら 2011）。"""
    mean_size = max(dists.mean(size_spec), 1.0) if size_spec else 1.0
    if isinstance(rate, dict) and rate.get("type") == "lift_demand":
        d = deep_merge(spec.get("demand") or {}, {k: v for k, v in rate.items() if k not in ("type", "flow", "share")})
        persons = lift_demand_per_min(d, rate.get("flow", "incoming")) * float(rate.get("share", 1.0))
        return ({"type": "constant", "per_min": persons / mean_size},
                {"persons_per_min": round(persons, 3), "groups_per_min": round(persons / mean_size, 3), "mean_group_size": round(mean_size, 3),
                 "demand": d, "flow": rate.get("flow", "incoming"), "source": "peters2011"})
    if isinstance(rate, dict) and rate.get("unit") == "persons":
        r = copy.deepcopy(rate)
        if r.get("type", "constant") == "constant":
            r["per_min"] = r["per_min"] / mean_size
            persons = rate["per_min"]
        else:
            r["per_min"] = [[t, v / mean_size] for t, v in r["per_min"]]
            T = float(spec.get("duration_s", 60))
            persons = float(np.mean([dists.rate_at(rate, t) * 60 for t in np.linspace(0, T, 200)]))  # 時間の平均
        return r, {"unit": "persons", "persons_per_min": round(persons, 3), "mean_group_size": round(mean_size, 3),
                   **({"source": rate["source"]} if rate.get("source") else {})}
    return rate, {"unit": "groups", "mean_group_size": round(mean_size, 3)}


class Builder:
    def __init__(self, spec):
        self.spec = spec
        self.space = load_space(spec["space"])
        self.rng = random.Random(spec["seed"])
        self.n = 0
        self.group_n = 0
        self.profile = PROFILES.get(spec["people"].get("profile"), {})
        self.meta = {"profile": spec["people"].get("profile"), "rates": {}, "elevator": {}, "gates": {}}
        models = spec["people"]["models"]
        self.models = list(MODELS) if models == "all" else list(models)
        self.ev_zone = None
        for p in self.space.pois.values():
            if p.get("kind") == "wait_zone":
                self.ev_zone = p["zone"]
                self.ev_poi = p

    # ---- 行き先 → 段取り ----
    def resolve_to(self, to):
        if to == "elevator" or to in self.space.pois:
            return to
        cands = sorted(k for k in self.space.pois if k.startswith(to + "_"))
        return self.rng.choice(cands)

    def poi_point(self, name):
        """入口・出口の点。line: [[x0, y0], [x1, y1]] があれば、その線の上のどこか（幅のある入口）。"""
        p = self.space.poi(name)
        if "line" in p:
            (x0, y0), (x1, y1) = p["line"]
            u = self.rng.random()
            return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)
        return self.space.poi_xy(name)

    def origin_point(self, origin):
        """人が現れる点。origin は場所の名前か、{"xy": [x, y]}・{"line": [[x0, y0], [x1, y1]]}。"""
        if isinstance(origin, str):
            return self.poi_point(origin)
        if "xy" in origin:
            return tuple(map(float, origin["xy"]))
        (x0, y0), (x1, y1) = origin["line"]
        u = self.rng.random()
        return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * u)

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
            steps += [("walk", self.poi_point(name), "pass")]
            hidden = sp.pois[name].get("hidden")
            if hidden:  # カメラに映らない所（扉の向こうなど）まで歩いてから消える
                steps.append(("straight", tuple(map(float, hidden)), "pass"))
            steps.append(("exit",))
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
        size_spec = size_spec or self.spec["people"].get("group_size")
        size = max(int(dists.sample(size_spec, self.rng)), 1) if size_spec else 1  # 0 が出る分布でも 1 組は 1 人以上
        group = None
        if size > 1:
            self.group_n += 1
            group = f"G{self.group_n:03d}"
        speeds = [float(dists.sample(self.spec["people"]["speed"], self.rng)) for _ in range(size)]
        speed = self.group_speed(speeds)
        lat = self.spec["people"]["group_lateral_m"]
        oxy = origin_xy or self.origin_point(origin)
        label = origin if isinstance(origin, str) else origin.get("name") or stream  # 記録の出発地（OD の集計に使う）
        comp = []
        base_plan = self.plan_for(d, comp)
        hidden = self.space.pois[origin].get("hidden") if isinstance(origin, str) and origin_xy is None else None
        if hidden:  # カメラに映らない所（扉の向こうなど）に現れ、現れる場所までまっすぐ歩いて入る
            base_plan = [("straight", tuple(oxy), "pass")] + base_plan
            oxy = tuple(map(float, hidden))
        made = []
        for k in range(size):
            l_pref = (k - (size - 1) / 2) * lat if size > 1 else self.rng.uniform(-0.3, 0.3)
            plan = base_plan if k == 0 else self.plan_for_copy(base_plan)
            a = self.new_agent(plan, t0 + k * self.rng.uniform(0.0, 0.4), oxy, speed if size > 1 else speeds[0], l_pref, group,
                               {"type": typ, "stream": stream, "destination": d["to"], "origin": label})
            made.append(a)
        for c in comp:  # 待ち合わせ: 先に来た人（グループ全員）と、あとから来る同行者
            for a in made:
                c["meet"].members.add(a.name)
            cs = c["spec"]
            delay = float(dists.sample(cs.get("delay", {"type": "uniform", "min": 8, "max": 25}), self.rng))
            corigin = cs.get("from", origin)
            cxy = self.space.poi_xy(corigin) if isinstance(corigin, str) else self.origin_point(corigin)
            clabel = corigin if isinstance(corigin, str) else corigin.get("name") or stream
            cplan = [("gate", g) for g in cs.get("via", [])] + [("walk", c["xy"], "pass"), ("meet", c["meet"], c["face"], "companion_wait", 0.0)]
            if c["then"]:
                cplan += self.plan_for(c["then"])
            ca = self.new_agent(cplan, t0 + delay, cxy, speed, 0.3, group or f"G{self.group_n + 1:03d}",
                                {"type": typ, "stream": stream, "destination": d["to"], "origin": clabel, "role": "companion"})
            if group is None:
                self.group_n += 1
                for a in made:
                    a.group = ca.group
            c["meet"].members.add(ca.name)
            made.append(ca)
        for a in made:
            sim.add(a)
        return made

    def group_speed(self, speeds):
        """グループで歩く速さ。moussaid2010: 一人ひとりの速さの平均から、1 人増えるごとに slope_m_s ずつ遅く。min: いちばん遅い人に合わせる。"""
        if len(speeds) == 1:
            return speeds[0]
        gs = self.spec["people"].get("group_speed") or {"model": "min"}
        if gs.get("model") == "moussaid2010":
            floor = float(self.spec["people"]["speed"].get("min", 0.5)) if isinstance(self.spec["people"]["speed"], dict) else 0.5
            return max(floor, sum(speeds) / len(speeds) - float(gs.get("slope_m_s", 0.04)) * (len(speeds) - 1))
        return min(speeds)

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
                    step = float(dists.sample(sch["interval"], self.rng))
                    if step <= 0:  # 0 のままだと終わらない
                        raise ValueError(f"elevator.schedule.interval は正の値（{step} が出た）")
                    t += step
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
                svc = spec["gates"].get(k, {}).get("service_s", self.profile.get("gate_service_s", 1.5))
                gates[k] = Gate(k, p, svc, random.Random(f"{spec['seed']}-{k}"))
                from_lit = k not in spec["gates"] and self.profile.get("gate_service_s")
                self.meta["gates"][k] = {"service_s": svc, "source": "fruin1987" if from_lit else "scenario"}
        ev = spec.get("elevator")
        cars, spots, policy, on_arrival = [], [], None, None
        timing = None
        if ev:
            # 扉が開いてから、降りる人 → 乗る人の順に 1 人 transfer_s 秒（Peters Research の既定 1.0 s、CIBSE の計算例 1.2 s）
            timing = {"door_open_s": float(ev.get("door_open_s", 1.0)),
                      "transfer_s": float(ev.get("transfer_s", self.profile.get("elevator", {}).get("transfer_s", 1.0)))}
            self.meta["elevator"].update(timing)
            for c in ev["cars"]:
                p = sp.poi(c)
                cars.append(Car(c, tuple(p["xy"]), tuple(p["face"]), int(ev.get("capacity", 8)), float(p.get("cabin_m", 0.0))))
            spots = wait_spots(sp, self.ev_poi)
            if ev.get("schedule", {}).get("type") == "on_demand":
                policy = self.on_demand_policy(ev)
            else:
                self.schedule(cars, ev, spec["duration_s"])
            alight = ev.get("alight")
            if alight:
                count = alight.get("count", {"type": "poisson", "lam": 1.0})
                if isinstance(count, dict) and count.get("type") == "lift_demand":
                    count = self.alight_count_from_demand(count, ev, len(cars))
                    self.meta["elevator"]["alight"] = count

                def on_arrival(sim, car, t, alight=alight, count=count):
                    n = int(dists.sample(count, self.rng))
                    names = []
                    door = np.array(car.door)
                    out_dir = door - np.array(car.inside)
                    out_dir /= max(np.linalg.norm(out_dir), 1e-9)
                    for k in range(n):
                        typ = dists.sample(alight.get("types"), self.rng) if alight.get("types") else "person"
                        d = self.pick_destination(alight["destinations"], typ)
                        plan = [("walk", tuple(door + out_dir * 3.0), "alight")] + self.plan_for(d)  # 扉から 3 m 出るまでは降車
                        side = np.array([-out_dir[1], out_dir[0]]) * self.rng.uniform(-0.3, 0.3)
                        if car.depth_m > 0:  # かごの中から歩いて出る（扉の前に急に現れないように）
                            oxy = np.array(car.cabin) - out_dir * 0.3 * k + side
                            plan = [("straight", tuple(door + out_dir * 0.4 + side), "alight")] + plan
                        else:
                            oxy = door + out_dir * (0.4 + 0.5 * k) + side
                        t_out = t + timing["door_open_s"] + timing["transfer_s"] * k  # 扉が開いてから 1 人ずつ
                        a = self.new_agent(plan, t_out, oxy, float(dists.sample(spec["people"]["speed"], self.rng)),
                                           self.rng.uniform(-0.3, 0.3), None,
                                           {"type": typ, "stream": "alight", "destination": d["to"] if isinstance(d, dict) else d,
                                            "origin": car.name, "alight_zones": (self.ev_zone,)})
                        a.state = "alight"
                        sim.add(a)
                        names.append(a.name)
                    return names
        sim = Sim(sp, fps, total, gates, cars, spots, lmax=float(spec["people"].get("lateral_max_m", 0.6)), on_arrival=on_arrival,
                  elevator_policy=policy, speed_density=spec["people"].get("speed_density"), ev_timing=timing)
        for s in spec["streams"]:
            size_spec = s.get("group_size") or spec["people"].get("group_size")
            rate, note = resolve_rate(spec, s["rate"], size_spec)
            self.meta["rates"][s.get("name", s["origin"])] = note
            for t0 in dists.arrival_times(rate, spec["duration_s"], self.rng, float(s.get("start_s", 0.0))):
                self.spawn_group(sim, t0, s["origin"], s["destinations"], s.get("types"), size_spec, s.get("name", s["origin"]))
        return sim

    def alight_count_from_demand(self, count, ev, n_cars):
        """EV から降りる人（出る流れ、人/分）を、1 回の到着あたりのポアソンの平均に直す。"""
        d = deep_merge(self.spec.get("demand") or {}, {k: v for k, v in count.items() if k not in ("type", "flow")})
        persons = lift_demand_per_min(d, count.get("flow", "outgoing"))
        sch = ev.get("schedule", {"type": "interval", "interval": {"type": "uniform", "min": 35, "max": 60}})
        if sch.get("type", "interval") == "interval":
            per_min = n_cars * 60.0 / dists.mean(sch["interval"])
        elif sch["type"] == "times":
            per_min = sum(len(v) for v in sch.get("times", {}).values()) / (self.spec["duration_s"] / 60.0)
        else:
            raise ValueError("elevator.alight.count の lift_demand は schedule が interval か times のときだけ使える")
        lam = persons / max(per_min, 1e-9)
        return {"type": "poisson", "lam": round(lam, 3), "persons_per_min": round(persons, 3), "source": "peters2011"}


def build(spec):
    b = Builder(spec)
    return b.build(), b
