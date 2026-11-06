"""計算の結果を文献の値と比べる（妥当性の確かめ）。使い方: python -m twinsim check <結果の場所>（validity.* も書く）

二つを分けて書く:
  入力の再現   文献の分布を入れた量が、計算のあとも同じ分布になっているか（歩く速さ・グループの人数・到着の量・EV の乗り込み）。
               エンジンが入れた分布を崩していないかの確かめで、現実に合うかの確かめではない
  出てくる量   入れていない量が文献の範囲に入るか（密度での速さ・ゲートの間隔・待つ人どうしの距離・2 人連れの間隔）
もう一つ、シナリオの値ごとに根拠（文献・形だけ文献・仮）を並べた台帳を書く。仮の値は実データ（ゲートの記録・EV の運行記録）で合わせる。

書くもの: validity.json（数値）・validity.md（表）・validity.png（図）
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml

from .literature import GROUP_SHARE, LIFT_MIX, PROFILES, REFS, weidmann_speed, ztp_person_share

WALK_STATES = ("pass", "alight")
STAND_STATES = ("ev_wait", "gate_queue")
HALL_INTIMATE_M = 0.45
DYAD_AFTER_GATE_S = 5.0  # 2 人連れの距離は、ゲートを通ってからこの秒数（離れた 2 人が並び直す間）を外す
DENSITY_R = 1.5
FREE_R = 2.5  # 自由に歩く速さ: 前の半円のこの半径（m）に人がいない歩き（cfsm で 2.0 m/s の人が前の人に詰まらない距離 0.36 + 1.06 × 2.0）
PROFILE_GROUP_REF = {"office_commute_jp": "osaka_underground", "leisure_low_density": "toulouse_low"}
DYAD_REF = {"office_commute_jp": ("同僚", 0.851, 0.718), "leisure_low_density": ("友人", 0.792, 0.662)}
DYAD_ALL = ("1018 組の平均", 0.823, 0.657)  # Zanlungo ら 2017 の表 2 を組の数で重みづけ
DENSITY_BINS = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]


def _expand_states(runs, f0, n):
    out = [None] * n
    for s0, s1, st in runs:
        for f in range(max(s0, f0), min(s1, f0 + n - 1) + 1):
            out[f - f0] = st
    return out


class Run:
    def __init__(self, run_dir):
        self.dir = Path(run_dir).expanduser()
        self.gt = json.loads((self.dir / "ground_truth.json").read_text())
        p = self.dir / "summary.json"
        self.summary = json.loads(p.read_text()) if p.exists() else {}
        p = self.dir / "scenario_resolved.yaml"
        self.spec = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
        self.fps = int(self.gt["fps"])
        self.P = {}
        for name, info in self.gt["people"].items():
            tr = np.array(self.gt["tracks"][name], float)
            f0 = int(info["start_frame"])
            self.P[name] = {"f0": f0, "xy": tr[:, :2], "yaw": tr[:, 2], "moving": np.array(self.gt["moving"][name], bool),
                            "state": _expand_states(info["states"], f0, len(tr)), "group": info.get("group"),
                            "info": info, "queue_spans": self._queue_spans(info)}

    def _queue_spans(self, info):
        """ゲートの列に加わってから通るまで（コマ）。列の歩きは流れの速さと密度の比べから外す。"""
        ev = info.get("events", {})
        return [(int(round(j * self.fps)), int(round(tp * self.fps))) for j, tp in zip(ev.get("gate_join", []), ev.get("gate", []))]

    def at(self, name, f):
        d = self.P[name]
        k = f - d["f0"]
        return k if 0 <= k < len(d["xy"]) else None


def samples(run, step_s=0.5):
    """0.5 秒ごとに、その場にいる人の [人, コマ, 速さ（前後 0.5 秒の移動）, 前の半円の密度, 状態, 歩いているか, 前の半円 FREE_R の人数]。
    密度はエンジンと同じ定義（前の半円・半径 1.5 m・グループの仲間は数えない）。"""
    fps = run.fps
    h = fps // 2
    step = max(1, int(round(step_s * fps)))
    total = int(run.gt["total_frames"])
    area = 0.5 * math.pi * DENSITY_R ** 2
    rows = []
    for f in range(h, total - h, step):
        here = [(n, run.at(n, f)) for n in run.P]
        here = [(n, k) for n, k in here if k is not None]
        if not here:
            continue
        xy = np.array([run.P[n]["xy"][k] for n, k in here])
        yaw = np.radians([run.P[n]["yaw"][k] for n, k in here])
        hd = np.stack([np.cos(yaw), np.sin(yaw)], 1)
        grp = [run.P[n]["group"] for n, _ in here]
        rel = xy[None, :, :] - xy[:, None, :]
        dist = np.linalg.norm(rel, axis=2)
        ahead = np.einsum("ijk,ik->ij", rel, hd) > 0
        same = np.array([[gi is not None and gi == gj for gj in grp] for gi in grp])
        cnt = ((dist < DENSITY_R) & ahead & ~same & ~np.eye(len(here), dtype=bool)).sum(1)
        cnt_free = ((dist < FREE_R) & ahead & ~same & ~np.eye(len(here), dtype=bool)).sum(1)
        for i, (n, k) in enumerate(here):
            d = run.P[n]
            if k - h < 0 or k + h >= len(d["xy"]):
                continue
            v = float(np.linalg.norm(d["xy"][k + h] - d["xy"][k - h]) / (2 * h / fps))
            st = d["state"][k]
            if st == "pass" and any(a <= f <= b for a, b in d["queue_spans"]):
                st = "gate_approach"  # 列に向かう歩き（流れの比べに入れない）
            rows.append((n, f, v, cnt[i] / area, st, bool(d["moving"][k]), int(cnt_free[i])))
    return rows


def verdict(ok, note=None):
    v = "対象外" if ok is None else "合う" if bool(ok) else "注意"
    return {"verdict": v, **({"note": note} if note else {})}


# ---- 入力の再現 ----
def free_speed(run, rows):
    """自由に歩く速さ。前の半円 FREE_R（2.5 m）に人のいない歩き（グループの人は除く）の、人ごとの中央値。
    2 つを確かめる: (1) 歩き方: その人たちの速さが、その人たちに与えた速さ（正解の speed_m_s）と ± 0.05 m/s で合う。
    (2) 入れた値: 全員（グループの人は除く）に与えた速さの分布が、文献（またはシナリオ）の平均 ± 0.08・標準偏差 ± 0.08 に入る。
    前は 1.5 m の半円で選び、文献の値とじかに比べていた。cfsm では速い人は前の人が 0.36 + 1.06 × 速さ（1.9 m/s で 2.4 m）より近いと遅くなるので、
    1.5 m では速い人が遅く出た（与えた速さに対する比 1.8 m/s で 0.82）。また混んだ流れでは、速い人ほど前の人に追いつき「前に人がいない」場面に
    入らないので、測れる人が遅い人に偏る（verify_fundamental_diagram で 1.23 m/s。2.5 m にすると比はどの速さでも 0.99〜1.00、2026-11-06）。"""
    by = defaultdict(list)
    for n, _f, v, _rho, st, mv, n_free in rows:
        if st in WALK_STATES and n_free == 0 and mv and v > 0.2 and run.P[n]["group"] is None:
            by[n].append(v)
    names = [n for n, v in by.items() if len(v) >= 3]
    per = np.array([float(np.median(by[n])) for n in names])
    if len(per) < 10:
        return {"n_people": int(len(per)), **verdict(None, "前に人のいない歩きの人が 10 人未満")}, per
    m, s = float(per.mean()), float(per.std(ddof=1))
    sp = (run.spec.get("people") or {}).get("speed")
    mu, sd, note = 1.34, 0.26, None
    if isinstance(sp, dict) and sp.get("type") == "normal" and (sp.get("mean"), sp.get("sd")) != (1.34, 0.26):
        mu, sd = float(sp["mean"]), float(sp["sd"])
        note = f"シナリオの速さ {mu:g} ± {sd:g}（文献の値ではない）と比べた"
    elif isinstance(sp, (int, float)):
        mu, sd, note = float(sp), 0.0, f"シナリオの速さ {sp}（一定）と比べた"
    out = {"n_people": int(len(per)), "mean_m_s": round(m, 3), "sd_m_s": round(s, 3), "target": {"mean": mu, "sd": sd},
           "literature": {"mean": 1.34, "sd": 0.26, "source": "weidmann1993"}}
    given = np.array([run.P[n]["info"].get("speed_m_s") or np.nan for n in names], float)
    every = np.array([d["info"]["speed_m_s"] for d in run.P.values() if d["group"] is None and d["info"].get("speed_m_s")], float)
    if np.isnan(given).any() or len(every) < 10:  # 与えた速さのない正解（古い版）: 文献の値とじかに比べる
        return {**out, **verdict(abs(m - mu) <= 0.08 and max(0.0, sd - 0.08) <= s <= sd + 0.08, note)}, per
    gm, gs = float(given.mean()), float(given.std(ddof=1))
    em, es = float(every.mean()), float(every.std(ddof=1))
    walk_ok = abs(m - gm) <= 0.05 and abs(s - gs) <= 0.05
    input_ok = abs(em - mu) <= 0.08 and max(0.0, sd - 0.08) <= es <= sd + 0.08
    out.update({"given_same_people": {"mean": round(gm, 3), "sd": round(gs, 3)},
                "given_all": {"n": int(len(every)), "mean": round(em, 3), "sd": round(es, 3)},
                "walk_matches_given": bool(walk_ok), "input_matches_target": bool(input_ok)})
    return {**out, **verdict(walk_ok and input_ok, note)}, per


def group_sizes(run):
    """人の数の割合（1〜5 人以上）。EV から降りる人（1 人ずつ出る）と、待ち合わせの同行者は数えない。"""
    members = defaultdict(list)
    singles = 0
    streams = Counter()
    for n, d in run.P.items():
        info = d["info"]
        if info.get("stream") == "alight" or info.get("role") == "companion":
            continue
        streams[info.get("stream")] += 1
        if d["group"] is None:
            singles += 1
        else:
            members[d["group"]].append(n)
    sizes = [1] * singles + [len(v) for v in members.values()]
    counts = Counter(min(s, 5) for s in sizes)
    persons = [counts[k] * k if k < 5 else sum(s for s in sizes if s >= 5) for k in range(1, 6)]
    tot = max(sum(persons), 1)
    return [p / tot for p in persons], sizes, members, streams


def expected_group_share(run, streams):
    """シナリオの人数の分布（ゼロ切断ポアソン）から、人の数の割合の期待値（流れごとの人数で重みづけ）。"""
    spec = run.spec
    if not spec:
        return None
    default = (spec.get("people") or {}).get("group_size")
    acc, w = np.zeros(5), 0.0
    for s in spec.get("streams", []):
        name = s.get("name", s.get("origin"))
        gs = s.get("group_size") or default
        n = streams.get(name, 0)
        if not n:
            continue
        if gs is None:
            share = [1.0, 0, 0, 0, 0]
        elif isinstance(gs, dict) and gs.get("type") == "zero_truncated_poisson":
            share = ztp_person_share(gs["lam"], 5)
        else:
            return None
        acc += n * np.array(share)
        w += n
    return list(acc / w) if w else None


def arrival_dispersion(run, stream):
    """流れの人数の分散 ÷ 平均。グループで来るので、人の側から見たグループの人数の平均 Σ k・（k 人組の人の割合）。
    前は一律 1.2 で、グループの多い流れ（verify_counterflow、約 1.8）では正しい到着でも 1 割ほどが「注意」になった（2026-11-06）。"""
    spec = run.spec or {}
    default = (spec.get("people") or {}).get("group_size")
    for s in spec.get("streams", []):
        if s.get("name", s.get("origin")) != stream:
            continue
        gs = s.get("group_size") or default
        if gs is None:
            return 1.0
        if isinstance(gs, dict) and gs.get("type") == "zero_truncated_poisson":
            return float(sum((k + 1) * x for k, x in enumerate(ztp_person_share(gs["lam"], 5))))
    return 1.2


def arrivals(run):
    """流れごとの到着（人/分）と、シナリオで決めた値（summary.json の inputs.rates）。着いたのに入口がふさがっていて終わりまで外で待った人
    （summary.json の outside_at_end）も数える（ゲートで運べる量より多く入れる確かめで、外で待つ人を数えず 75 → 61 人/分に見えた、2026-11-06）。"""
    dur = run.gt["total_frames"] / run.fps
    by = Counter()
    for d in run.P.values():
        info = d["info"]
        if info.get("stream") != "alight" and info.get("role") != "companion":
            by[info.get("stream")] += 1
    outside = run.summary.get("outside_at_end") or {}
    by.update({s: n for s, n in outside.items() if s != "alight"})
    rates = (run.summary.get("inputs") or {}).get("rates", {})
    out = {}
    for s, n in by.items():
        obs = n / dur * 60
        r = rates.get(s, {})
        item = {"persons": n, "observed_per_min": round(obs, 2), **({"outside_at_end": outside[s]} if outside.get(s) else {})}
        if "persons_per_min" in r:
            exp = r["persons_per_min"] * dur / 60
            z = (n - exp) / math.sqrt(max(exp * arrival_dispersion(run, s), 1e-9))  # グループで来るので分散は平均より大きい
            item.update({"expected_per_min": r["persons_per_min"], "z": round(z, 2), "source": r.get("source"), **verdict(abs(z) <= 2)})
        out[s] = item
    return out


def lift_mix(run):
    board = sum(1 for d in run.P.values() if "board" in d["info"].get("events", {}))
    alight = sum(1 for d in run.P.values() if d["info"].get("stream") == "alight")
    if board + alight == 0:
        return {**verdict(None, "EV がない")}
    period = ((run.spec.get("demand") or {}).get("period")) or "morning"
    mix = LIFT_MIX.get(period, LIFT_MIX["morning"])
    ref = mix["outgoing"] / (mix["incoming"] + mix["outgoing"])
    share = alight / (board + alight)
    n = board + alight
    se = math.sqrt(ref * (1 - ref) / n)
    uses_demand = any(isinstance(s.get("rate"), dict) and s["rate"].get("type") == "lift_demand" for s in run.spec.get("streams", []))
    res = {"boarded": board, "alighted": alight, "outgoing_share": round(share, 3),
           "literature": {"period": period, "outgoing_share": round(ref, 3), "source": "peters2011"},
           "still_waiting_at_end": run.summary.get("still_waiting_at_end")}
    if not uses_demand:
        res.update(verdict(None, "到着が lift_demand ではないので比べない（参考の値）"))
    else:
        res.update(verdict(abs(share - ref) <= 2 * se + 0.03, "乗れずに残った人がいると入る側が少なく見える" if res["still_waiting_at_end"] else None))
    return res


def boarding_intervals(run):
    t_by = {}
    for n, d in run.P.items():
        ev = d["info"].get("events", {})
        if "board" in ev:
            t_by[n] = ev["board"]
    diffs = []
    for e in run.gt.get("elevator_events", []):
        ts = sorted(t_by[n] for n in e["boarded"] if n in t_by)
        diffs += [b - a for a, b in zip(ts, ts[1:])]
    tp = ((run.summary.get("inputs") or {}).get("elevator") or {}).get("transfer_s")
    if len(diffs) < 5:
        return {"n": len(diffs), **verdict(None, "続けて乗った人が 5 組未満")}, diffs
    med = float(np.median(diffs))
    return {"n": len(diffs), "median_s": round(med, 2), "scenario_transfer_s": tp,
            "literature": {"range_s": [1.0, 1.2], "source": "peters_transfer"}, **verdict(0.7 <= med <= 1.6)}, diffs


# ---- 出てくる量 ----
def speed_density(run, rows):
    """密度ごとの速さ。絶対の速さ（m/s）と、その人の思う速さに対する比（Weidmann の式の v/v0 と比べる）。
    判定は比で、0.5 人/m² 以上の区間（30 点以上）の差の二乗平均。絶対の速さは、速い人ほど前に人がいるので低めに出る。"""
    W = [r for r in rows if r[4] in WALK_STATES]
    v = np.array([r[2] for r in W])
    rho = np.array([r[3] for r in W])
    ratio = np.array([r[2] / max(run.P[r[0]]["info"].get("speed_m_s", 1.34), 0.1) for r in W])
    bins = []
    for lo, hi in zip(DENSITY_BINS, DENSITY_BINS[1:]):
        m = (rho >= lo) & (rho < hi) if lo > 0 else (rho < hi)
        if m.sum() >= 30:
            mid = (lo + hi) / 2
            bins.append({"rho": [lo, hi], "n": int(m.sum()), "mean_v": round(float(v[m].mean()), 3), "sd_v": round(float(v[m].std()), 3),
                         "weidmann_v": round(weidmann_speed(mid), 3), "mean_ratio": round(float(ratio[m].mean()), 3),
                         "weidmann_ratio": round(weidmann_speed(mid) / 1.34, 3)})
    dense = [b for b in bins if b["rho"][0] >= 0.5]
    res = {"bins": bins, "max_rho": round(float(rho.max()), 2) if len(rho) else 0.0,
           "literature": {"model": "Kladek の式", "v0": 1.34, "gamma": 1.913, "rho_max": 5.4, "source": "weidmann1993"}}
    judge = (run.spec.get("validity") or {}).get("speed_density") == "judge"
    if not dense:
        res.update(verdict(None, "0.5 人/m² 以上の場面が少なく、確かめられない（verify_fundamental_diagram で確かめる）"))
    else:
        res["rmse_ratio"] = round(math.sqrt(np.mean([(b["mean_ratio"] - b["weidmann_ratio"]) ** 2 for b in dense])), 3)
        res["rmse_m_s"] = round(math.sqrt(np.mean([(b["mean_v"] - b["weidmann_v"]) ** 2 for b in dense])), 3)
        if judge:
            res.update(verdict(res["rmse_ratio"] <= 0.12))
        else:  # 曲がり角・合流・ゲートの前後を含む空間では、一方向の廊下の関係より遅くて自然
            res.update({"verdict": "参考", "note": "Weidmann の式は一方向の廊下の関係。判定は verify_fundamental_diagram で"})
    return res, (rho, ratio)


def group_speed(run, rows, members):
    by = defaultdict(list)
    for n, _f, v, rho, st, mv, *_ in rows:
        if st == "pass" and rho == 0 and mv and v > 0.2:
            by[n].append(v)
    pts = []
    for _g, names in members.items():
        vs = [x for n in names for x in by.get(n, [])]
        if len(vs) >= 3:
            pts.append((min(len(names), 5), float(np.median(vs))))
    for n, d in run.P.items():
        if d["group"] is None and d["info"].get("stream") != "alight" and len(by.get(n, [])) >= 3:
            pts.append((1, float(np.median(by[n]))))
    sizes = sorted({s for s, _ in pts})
    ng = sum(1 for s, _ in pts if s > 1)
    if ng < 15 or len(sizes) < 2:
        return {"n_groups": ng, **verdict(None, f"グループが少ない（{ng} 組）。verify_groups で確かめる")}, pts
    x = np.array([s for s, _ in pts if s <= 4], float)
    y = np.array([v for s, v in pts if s <= 4])
    slope = float(np.polyfit(x, y, 1)[0])
    return {"n_groups": ng, "slope_m_s_per_member": round(slope, 3),
            "mean_by_size": {int(s): round(float(np.mean([v for k, v in pts if k == s])), 3) for s in sizes},
            "literature": {"slope_low_density": -0.04, "slope_moderate_density": -0.08, "source": "moussaid2010"},
            **verdict(-0.14 <= slope <= 0.0, "グループが少ないと傾きはぶれる" if ng < 30 else None)}, pts


def dyad_distance(run, members):
    """2 人連れが並んで歩くときの距離・横の間隔（Zanlungo ら 2017 は廊下を歩く 2 人の値）。ゲートの列に加わってから通って
    DYAD_AFTER_GATE_S 秒までは外す（列では前後に並び、ゲートは 1 人ずつ通るので離れてから並び直す。列の中を数えて 1.1〜1.8 m になった、2026-11-06）。"""
    profile = (run.spec.get("people") or {}).get("profile")
    rel_name, r_ref, x_ref = DYAD_REF.get(profile, DYAD_ALL)
    r_all, x_all = [], []
    for _g, names in members.items():
        if len(names) != 2:
            continue
        a, b = (run.P[n] for n in names)
        f0, f1 = max(a["f0"], b["f0"]), min(a["f0"] + len(a["xy"]), b["f0"] + len(b["xy"]))
        skip = [(j, tp + int(DYAD_AFTER_GATE_S * run.fps)) for j, tp in a["queue_spans"] + b["queue_spans"]]
        for f in range(f0, f1, run.fps // 2):
            if any(s0 <= f <= s1 for s0, s1 in skip):
                continue
            ka, kb = f - a["f0"], f - b["f0"]
            if a["state"][ka] == "pass" and b["state"][kb] == "pass" and a["moving"][ka] and b["moving"][kb]:
                rel = b["xy"][kb] - a["xy"][ka]
                y = math.radians(a["yaw"][ka])
                r_all.append(float(np.hypot(*rel)))
                x_all.append(abs(float(rel @ np.array([-math.sin(y), math.cos(y)]))))
    if len(r_all) < 20:
        return {"n_samples": len(r_all), **verdict(None, "2 人連れの歩く場面が少ない")}, r_all
    r, x = float(np.mean(r_all)), float(np.mean(x_all))
    return {"n_samples": len(r_all), "mean_distance_m": round(r, 3), "mean_abreast_m": round(x, 3),
            "literature": {"relation": rel_name, "distance_m": r_ref, "abreast_m": x_ref, "source": "zanlungo2017"},
            **verdict(abs(r - r_ref) <= 0.15)}, r_all


def gate_headways(run):
    """列ができているときの、同じレーンを続けて通る 2 人の間隔（ゲートがふさがっている間の 1 人あたりの時間）。
    後ろの人が、前の人が通るより前に列で止まっていた（状態 gate_queue の始まりが、自分の前の通過より後で、前の人の通過より前）場面だけ数える。
    列が進むたびに全員が次の場所へ歩く（そのあいだは歩く途中 pass）ので、「前の人が通った瞬間に列の状態」で選ぶと、
    種 1〜8 のどれも 10 回に届かなかった（2026-11-06）。"""
    q_start = defaultdict(list)
    for n, d in run.P.items():
        for s0, _s1, st in d["info"]["states"]:
            if st == "gate_queue":
                q_start[n].append(s0 / run.fps)
    passes = defaultdict(list)
    lanes = defaultdict(list)
    for e in run.gt.get("gate_events", []):
        lanes[(e["gate"], e["lane"])].append(e)
        passes[e["person"]].append(e["t"])
    hw, peak = [], 0
    for evs in lanes.values():
        evs.sort(key=lambda e: e["t"])
        ts = [e["t"] for e in evs]
        for k in range(1, len(evs)):
            prev, cur = evs[k - 1]["t"], evs[k]
            last = max((x for x in passes[cur["person"]] if x < cur["t"]), default=-math.inf)
            if any(last < s0 <= prev for s0 in q_start[cur["person"]]):
                hw.append(cur["t"] - prev)
        j = 0
        for i in range(len(ts)):
            while ts[i] - ts[j] > 60:
                j += 1
            peak = max(peak, i - j + 1)
    if len(hw) < 10:
        return {"n": len(hw), "max_per_min_per_lane": peak, **verdict(None, "列ができた場面が 10 回未満")}, hw
    med = float(np.median(hw))
    return {"n": len(hw), "median_s": round(med, 2), "p10_s": round(float(np.percentile(hw, 10)), 2), "p90_s": round(float(np.percentile(hw, 90)), 2),
            "max_per_min_per_lane": peak, "literature": {"card_reader_s": [1.5, 4.0], "per_min": [25, 40], "source": "fruin1987"},
            **verdict(1.5 <= med <= 4.0)}, hw


def gridlock(run):
    """詰まって動けなくなった人: 終わりの時点でまだいて、歩く途中（pass）かゲートの列に並ぶ途中（gate_queue）なのに、最後の 30 秒で 0.3 m 未満しか
    動いていない人（ゲートが通していれば列は 30 秒のうちに進む。列の人を数えず、ゲートの 1 つのレーンが 150 秒止まったのを見逃した、2026-11-06）。
    その 30 秒のあいだずっと歩く途中か列の途中だった人だけを数える（止まる段取りの後に歩き出したばかりの人は数えない）。
    ただし、その 30 秒の間に終わりの位置から 2 m より遠くへ行った人（行って戻った人）は数えない（ゲートを通って引き返した人が、
    たまたま 30 秒前と同じ所にいたのを数えた、2026-11-06。押されて前後に 1 m ほど動きながら出られない人は数える）。"""
    total = int(run.gt["total_frames"])
    w = 30 * run.fps
    stuck = []
    for n, d in run.P.items():
        end = d["f0"] + len(d["xy"]) - 1
        if end < total - 1 or len(d["xy"]) <= w or any(st not in ("pass", "gate_queue") for st in d["state"][-1 - w:]):
            # 30 秒のあいだずっと歩く途中か列の途中だった人だけ（受付で止まっていて終わりの 6 秒前に歩き出した人を数えた、2026-11-06）
            continue
        win = d["xy"][-1 - w:]
        if float(np.linalg.norm(win[-1] - win[0])) < 0.3 and float(np.linalg.norm(win - win[-1], axis=1).max()) <= 2.0:
            stuck.append(n)
    return {"n_stuck": len(stuck), "people": stuck[:10], **verdict(len(stuck) == 0, "最後の 30 秒、歩く途中・列の途中で止まったままの人" if stuck else None)}


def bottleneck(run):
    """出入口（validity.bottleneck: {x, y: [下, 上], width_m}）を通った人数の 1 分ごとの最大 → 幅 1 m・1 秒あたりの流れ。
    文献: Weidmann の式から出る一方向の流れの最大 1.22 人/(m·s)（密度 1.75 人/m² のとき）。"""
    b = (run.spec.get("validity") or {}).get("bottleneck")
    if not b:
        return None
    x, (y0, y1), wd = float(b["x"]), b["y"], float(b["width_m"])
    times = []
    for _n, d in run.P.items():
        xs = d["xy"][:, 0]
        k = np.nonzero((xs[:-1] < x) & (xs[1:] >= x))[0]
        for i in k:
            if y0 - 0.3 <= d["xy"][i, 1] <= y1 + 0.3:
                times.append((d["f0"] + i) / run.fps)
    times.sort()
    best, j = 0, 0
    for i in range(len(times)):
        while times[i] - times[j] > 60:
            j += 1
        best = max(best, i - j + 1)
    js = best / 60.0 / wd
    return {"passed": len(times), "max_per_min": best, "specific_flow": round(js, 2),
            "literature": {"experiment_1m": [1.90, 2.19], "source": "seyfried2009", "weidmann_max_specific_flow": 1.22},
            **verdict(1.90 * 0.85 <= js <= 2.19 * 1.15, "判定は幅 1.0 m の実験値 1.90〜2.19 人/(m·s) の ±15%（Weidmann の式の最大 1.22 は実験より少ない）")}


def waiting(run):
    """EV を待った時間・ゲートの列に並んだ時間・入口がふさがって外で待った時間（比べる文献はなく、参考の値）。"""
    ev = [d["info"]["events"]["board_start"] - d["info"]["events"]["wait_start"] for d in run.P.values()
          if "board_start" in d["info"].get("events", {}) and "wait_start" in d["info"]["events"]]
    gq = [(s1 - s0 + 1) / run.fps for d in run.P.values() for s0, s1, st in d["info"]["states"] if st == "gate_queue"]
    out = {"verdict": "参考"}
    if ev:
        out["ev_wait_s"] = {"n": len(ev), "mean": round(float(np.mean(ev)), 1), "p90": round(float(np.percentile(ev, 90)), 1)}
    if gq:
        out["gate_queue_s"] = {"n": len(gq), "mean": round(float(np.mean(gq)), 1), "p90": round(float(np.percentile(gq, 90)), 1)}
    sw = [d["info"]["events"]["spawn_wait_s"] for d in run.P.values() if d["info"].get("events", {}).get("spawn_wait_s")]
    if sw:
        out["outside_wait_s"] = {"n": len(sw), "mean": round(float(np.mean(sw)), 1), "p90": round(float(np.percentile(sw, 90)), 1)}
    out["still_waiting_at_end"] = run.summary.get("still_waiting_at_end")
    if run.summary.get("outside_at_end"):
        out["outside_at_end"] = sum(run.summary["outside_at_end"].values())
    return out


def standing_spacing(run):
    """立って待つ人（EV・ゲートの列）どうしの、いちばん近い距離（グループの仲間は除く）。Hall 1966 の密接の距離 0.45 m 未満が少ないか。
    前は歩いて横を通る人までの距離も数えていた（列が長いと、列の横を抜ける人で 0.45 m 未満が 13% になった。歩く人との近さは重なりで見る、2026-11-06）。"""
    d_all = []
    total = int(run.gt["total_frames"])
    for f in range(0, total, run.fps):
        here = [(n, run.at(n, f)) for n in run.P]
        here = [(n, k) for n, k in here if k is not None]
        stand = [i for i, (n, k) in enumerate(here) if run.P[n]["state"][k] in STAND_STATES]
        if not stand or len(here) < 2:
            continue
        xy = np.array([run.P[n]["xy"][k] for n, k in here])
        grp = [run.P[n]["group"] for n, _ in here]
        sset = set(stand)
        for i in stand:
            d = np.linalg.norm(xy - xy[i], axis=1)
            for j in range(len(here)):
                if j == i or j not in sset or (grp[i] is not None and grp[i] == grp[j]):
                    d[j] = 99
            d_all.append(float(d.min()))
    d_all = [x for x in d_all if x < 99]
    if len(d_all) < 20:
        return {"n": len(d_all), **verdict(None, "立って待つ場面が少ない")}, d_all
    share = float(np.mean(np.array(d_all) < HALL_INTIMATE_M))
    return {"n": len(d_all), "median_m": round(float(np.median(d_all)), 2), "share_below_0.45m": round(share, 3),
            "literature": {"intimate_m": HALL_INTIMATE_M, "personal_m": [0.45, 1.2], "source": "hall1966"}, **verdict(share <= 0.05)}, d_all


# ---- 台帳 ----
def ledger(spec, inputs):
    """シナリオの値ごとの根拠。source: <REFS の名前> をシナリオに書けば文献として数える。"""
    rows = []
    people = spec.get("people") or {}
    prof = PROFILES.get(people.get("profile"), {})
    psrc = prof.get("sources", {})

    def add(item, value, src, status):
        s = src_of(value) if isinstance(value, dict) else None
        if isinstance(s, str) and s.startswith("data:"):  # 実データで合わせた値（twinsim calibrate）
            src, status = s, f"実データ（{s[5:]}）"
        rows.append({"item": item, "value": value, "source": src, "status": status})

    def src_of(d):
        return d.get("source") if isinstance(d, dict) else None

    sp = people.get("speed")
    add("歩く速さ", sp, src_of(sp) or ("weidmann1993" if isinstance(sp, dict) and sp.get("mean") == 1.34 and sp.get("sd") == 0.26 else None),
        "文献" if src_of(sp) or (isinstance(sp, dict) and sp.get("mean") == 1.34 and sp.get("sd") == 0.26) else "仮")
    sd = people.get("speed_density")
    add("速さと密度", sd, "weidmann1993" if sd else None, "文献" if sd else "なし")
    gs = people.get("group_speed")
    add("グループの速さ", gs, "moussaid2010" if gs and gs.get("model") == "moussaid2010" else None,
        "文献" if gs and gs.get("model") == "moussaid2010" else "仮")
    lat = people.get("group_lateral_m")
    add("グループの横の間隔", lat, "zanlungo2017" if lat in (0.72, 0.66, 0.6, 0.583) else None, "文献" if lat in (0.72, 0.66, 0.6, 0.583) else "仮")
    if people.get("group_size"):
        add("グループの人数（既定）", people["group_size"], psrc.get("group_size") or src_of(people["group_size"]),
            "文献" if psrc.get("group_size") or src_of(people["group_size"]) else "形だけ文献（coleman1961）")
    for s in spec.get("streams", []):
        name = s.get("name", s.get("origin"))
        r = s.get("rate")
        if isinstance(r, dict) and r.get("type") == "lift_demand":
            d = dict(spec.get("demand") or {})
            d.update({k: v for k, v in r.items() if k != "type"})
            share = float(r.get("share", 1.0))
            add(f"{name}: 到着の量", d, "peters2011",
                "文献（在館人数は建物の値を入れる）" if share == 1.0 else f"文献（全体の量。在館人数は建物の値・分け方 share {share:g} は仮）")
        else:
            add(f"{name}: 到着の量", r, src_of(r), "文献" if src_of(r) else "仮")
        if s.get("group_size"):
            g = s["group_size"]
            add(f"{name}: グループの人数", g, src_of(g), "文献" if src_of(g) else "形だけ文献（coleman1961）")
        if s.get("types"):
            add(f"{name}: 人の種類の割合", s["types"], src_of(s["types"]), "文献" if src_of(s["types"]) else "仮")
        ds = s.get("destinations", [])
        if len(ds) > 1:
            add(f"{name}: 行き先の割合", {str(d.get("to")): d.get("p", 1.0) for d in ds},
                None, "仮")
        for d in ds:
            if isinstance(d, dict) and d.get("dwell") is not None:
                dw = d["dwell"]
                lognormal = isinstance(dw, dict) and dw.get("type") == "lognormal"
                add(f"{name}: {d.get('to')} で止まる時間", dw, src_of(dw) or ("brown2005" if lognormal else None),
                    "文献" if src_of(dw) else "形だけ文献（類推）" if lognormal else "仮")
    ev = spec.get("elevator")
    if ev:
        sch = ev.get("schedule", {})
        add("EV の着く間隔", sch, src_of(sch), "文献" if src_of(sch) else "仮（EV の運行記録で合わせる）")
        c = (ev.get("alight") or {}).get("count")
        if c is not None:
            if isinstance(c, dict) and c.get("type") == "lift_demand":
                add("EV から降りる人", (inputs.get("elevator") or {}).get("alight", c), "peters2011", "文献")
            else:
                add("EV から降りる人", c, src_of(c), "文献" if src_of(c) else "仮")
        tp = (inputs.get("elevator") or {}).get("transfer_s")
        add("EV の乗り降り（1 人あたり）", tp, "peters_transfer", "文献")
        add("EV の扉が開くまで", (inputs.get("elevator") or {}).get("door_open_s"), None, "仮")
    for g, gi in (inputs.get("gates") or {}).items():
        add(f"ゲート {g} の 1 人あたりの時間", gi["service_s"], "fruin1987" if gi.get("source") == "fruin1987" else None,
            "文献（範囲。ばらつきの形は仮）" if gi.get("source") == "fruin1987" else "仮")
    return rows


# ---- まとめ ----
def evaluate(run_dir, figure=True):
    run = Run(run_dir)
    rows = samples(run)
    fs, fs_data = free_speed(run, rows)
    share, sizes, members, streams = group_sizes(run)
    exp_share = expected_group_share(run, streams)
    profile = (run.spec.get("people") or {}).get("profile")
    ref_key = PROFILE_GROUP_REF.get(profile)
    gsz = {"n_people": int(sum(sizes)), "n_groups": int(sum(1 for s in sizes if s > 1)), "person_share": [round(x, 3) for x in share],
           "scenario_share": [round(x, 3) for x in exp_share] if exp_share else None}
    if ref_key:
        gsz["literature"] = {"key": ref_key, "share": GROUP_SHARE[ref_key]["share"], "source": GROUP_SHARE[ref_key]["source"],
                             "note": GROUP_SHARE[ref_key]["note"]}
    if exp_share and gsz["n_people"] >= 30:
        tv = 0.5 * sum(abs(a - b) for a, b in zip(share, exp_share))
        gsz["total_variation"] = round(tv, 3)
        gsz.update(verdict(tv <= max(0.08, 1.5 / math.sqrt(gsz["n_people"]))))
    else:
        gsz.update(verdict(None, "人数が少ない、または分布がゼロ切断ポアソンでない"))
    sdn, sd_data = speed_density(run, rows)
    gsp, gsp_data = group_speed(run, rows, members)
    dy, dy_data = dyad_distance(run, members)
    gh, gh_data = gate_headways(run)
    bi, bi_data = boarding_intervals(run)
    ss, ss_data = standing_spacing(run)
    res = {
        "run": str(run.dir), "scenario": run.gt.get("scenario"), "profile": profile,
        "input_reproduction": {"free_walking_speed": fs, "group_size": gsz, "group_speed": gsp, "arrivals": arrivals(run),
                               "lift_mix": lift_mix(run), "elevator_boarding_interval": bi, "gate_headway": gh},
        "emergent": {"speed_density": sdn, "dyad_distance": dy, "standing_spacing": ss, "gridlock": gridlock(run), "waiting": waiting(run),
                     **({"bottleneck": bn} if (bn := bottleneck(run)) else {})},
        "ledger": ledger(run.spec, run.summary.get("inputs") or {}),
        "refs": {k: REFS[k]["cite"] for k in REFS},
    }
    (run.dir / "validity.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (run.dir / "validity.md").write_text(to_markdown(res), encoding="utf-8")
    if figure:
        try:
            draw(run.dir / "validity.png", res, fs_data, sd_data, share, exp_share, gsz.get("literature"), gsp_data, gh_data, ss_data)
        except ImportError as e:
            print("validity.png は描かなかった（matplotlib がない）:", e)
    return res


def _fmt(v):
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items() if k not in ("source",))
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _row(*cells):
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _md_input(ir):
    """入力の再現の表の行。"""
    rows = []
    f = ir["free_walking_speed"]
    tg = f.get("target", {"mean": 1.34, "sd": 0.26})
    lit = "1.34 ± 0.26 m/s（weidmann1993）" if (tg["mean"], tg["sd"]) == (1.34, 0.26) else f"シナリオ {tg['mean']} ± {tg['sd']} m/s（文献は 1.34 ± 0.26）"
    calc = f"{f.get('mean_m_s', '-')} ± {f.get('sd_m_s', '-')} m/s（{f.get('n_people')} 人）"
    if "given_all" in f:
        g1, g2 = f["given_same_people"], f["given_all"]
        calc += f"。その人たちに与えた速さ {g1['mean']} ± {g1['sd']}、全員に与えた速さ {g2['mean']} ± {g2['sd']}（{g2['n']} 人）"
        lit += "。歩きは与えた速さと ± 0.05、与えた速さは文献と ± 0.08"
    rows.append(_row("自由に歩く速さ（前 2.5 m に人がいない）", calc, lit, f["verdict"]))
    g = ir["group_size"]
    gl = g.get("literature")
    ref = f"入力 {_fmt(g.get('scenario_share'))}" + (f"、文献 {_fmt(gl['share'])}（{gl['source']}、{gl['note']}）" if gl else "")
    rows.append(_row("グループの人数（人の割合 1/2/3/4/5+）", f"{_fmt(g['person_share'])}（{g['n_people']} 人・{g['n_groups']} 組）", ref, g["verdict"]))
    gs = ir["group_speed"]
    rows.append(_row("グループの速さ（1 人増えるごと）", f"{gs.get('slope_m_s_per_member', '-')} m/s（{gs.get('n_groups')} 組）",
                     "−0.04〜−0.08 m/s（moussaid2010）", gs["verdict"]))
    for s, a in ir["arrivals"].items():
        calc = f"{a['observed_per_min']} 人/分（{a['persons']} 人" + (f"、うち終わりまで外で待った {a['outside_at_end']} 人）" if a.get("outside_at_end") else "）")
        if "expected_per_min" in a:
            rows.append(_row(f"到着 {s}", calc, f"{a['expected_per_min']} 人/分（{a['source']}、z = {a['z']}）", a["verdict"]))
        else:
            rows.append(_row(f"到着 {s}", calc, "シナリオの値（仮）", "-"))
    lm = ir["lift_mix"]
    if "outgoing_share" in lm:
        rows.append(_row("EV の出る側の割合", f"{lm['outgoing_share']}（乗った {lm['boarded']}・降りた {lm['alighted']}）",
                         f"{lm['literature']['outgoing_share']}（{lm['literature']['period']}、peters2011）", lm["verdict"]))
    b = ir["elevator_boarding_interval"]
    rows.append(_row("EV に続けて乗る間隔", f"{b.get('median_s', '-')} 秒（{b.get('n')} 組）", "1.0〜1.2 秒（peters_transfer）", b["verdict"]))
    gh = ir["gate_headway"]
    rows.append(_row("ゲートが混んだときの 1 人あたりの時間",
                     f"中央 {gh.get('median_s', '-')} 秒（{gh.get('n')} 回、1 レーン最大 {gh.get('max_per_min_per_lane')} 人/分）",
                     "1.5〜4.0 秒・25〜40 人/分（fruin1987、カードを読む改札）", gh["verdict"]))
    return rows


def _md_emergent(em):
    """出てくる量の表の行。"""
    rows = []
    sd = em["speed_density"]
    bins = "、".join(f"{b['rho'][0]}–{b['rho'][1]}: {b['mean_v']} m/s・比 {b['mean_ratio']}（式 {b['weidmann_v']}・{b['weidmann_ratio']}）"
                    for b in sd["bins"])
    rows.append(_row("密度ごとの速さ（人/m²: 速さ・自分の速さに対する比）", f"{bins or '-'}（最大 {sd['max_rho']} 人/m²）",
                     "Kladek の式（weidmann1993）", sd["verdict"]))
    dy = em["dyad_distance"]
    dl = dy.get("literature", {})
    rows.append(_row("2 人連れの距離・横の間隔", f"{dy.get('mean_distance_m', '-')} m・{dy.get('mean_abreast_m', '-')} m",
                     f"{dl.get('relation', '-')} {dl.get('distance_m', '-')} m・{dl.get('abreast_m', '-')} m（zanlungo2017）", dy["verdict"]))
    ss = em["standing_spacing"]
    rows.append(_row("待つ人どうしのいちばん近い距離", f"中央 {ss.get('median_m', '-')} m・0.45 m 未満 {ss.get('share_below_0.45m', '-')}",
                     "密接の距離 0.45 m 未満は少ない（hall1966）", ss["verdict"]))
    gl = em["gridlock"]
    rows.append(_row("詰まって動けなくなった人", f"{gl['n_stuck']} 人", "0 人", gl["verdict"]))
    if "bottleneck" in em:
        bn = em["bottleneck"]
        rows.append(_row("出入口を通れる量", f"1 分に最大 {bn['max_per_min']} 人 = {bn['specific_flow']} 人/(m·s)（通った {bn['passed']} 人）",
                         "幅 1.0 m の実験 1.90〜2.19 人/(m·s)（seyfried2009）。Weidmann の式の最大は 1.22", bn["verdict"]))
    w = em["waiting"]
    rows.append(_row("待った時間（参考）",
                     f"EV {_fmt(w.get('ev_wait_s', '-'))} 秒・ゲートの列 {_fmt(w.get('gate_queue_s', '-'))} 秒・"
                     f"入口の外 {_fmt(w.get('outside_wait_s', '-'))} 秒・終わりに残った {w.get('still_waiting_at_end')} 人"
                     + (f"・終わりまで外で待った {w['outside_at_end']} 人" if w.get("outside_at_end") else ""),
                     "-", "参考"))
    return rows


def to_markdown(res):
    ir, em = res["input_reproduction"], res["emergent"]
    L = [f"# 妥当性の確かめ: {res['scenario']}（{res['profile'] or 'プロファイルなし'}）", "",
         f"結果: `{res['run']}`。文献の一覧は末尾。判定の基準は twinsim/validity.py。", "",
         "## 入力の再現（文献の分布を入れた量が、計算のあとも同じか）", "", _row("項目", "計算", "文献・入力", "判定"), "|---|---|---|---|"]
    L += _md_input(ir)
    L += ["", "## 出てくる量（入れていない量が文献の範囲に入るか）", "", _row("項目", "計算", "文献", "判定"), "|---|---|---|---|"]
    L += _md_emergent(em)
    notes = [(k, v["note"]) for part in (ir, em) for k, v in part.items() if isinstance(v, dict) and v.get("note")]
    if notes:
        L += ["", "注: " + "。".join(f"{k}: {n}" for k, n in notes)]
    L += ["", "## 台帳（シナリオの値ごとの根拠）", "", _row("項目", "値", "根拠", "状態"), "|---|---|---|---|"]
    L += [_row(r["item"], _fmt(r["value"]), r["source"] or "-", r["status"]) for r in res["ledger"]]
    L += ["", "## 文献", ""] + [f"- **{k}**: {c}" for k, c in res["refs"].items()]
    return "\n".join(L) + "\n"


INK, MUTED, SIM, INPUT, LIT, BAND = "#222222", "#666666", "#2f6690", "#d1863a", "#444444", "#e6e6e6"


def draw(path, res, fs, sd_data, share, exp_share, lit, gsp, gh, ss):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",):
        if Path(f).exists():
            font_manager.fontManager.addfont(f)
            plt.rcParams["font.family"] = "Noto Sans CJK JP"
    plt.rcParams.update({"axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#eeeeee",
                         "font.size": 10, "legend.frameon": False})
    fig, ax = plt.subplots(2, 3, figsize=(15, 8.5))
    ax = ax.ravel()

    def empty(a, title, msg):
        a.set_title(title, loc="left", color=INK)
        a.text(0.5, 0.5, msg, ha="center", va="center", color=MUTED, transform=a.transAxes)
        a.set_xticks([]), a.set_yticks([])

    # (1) 自由に歩く速さ
    t = "1. 自由に歩く速さ（入力の再現）"
    if len(fs) >= 10:
        a = ax[0]
        a.hist(fs, bins=np.arange(0.6, 2.05, 0.1), density=True, color=SIM, alpha=0.85, edgecolor="white", linewidth=2, label=f"計算（{len(fs)} 人）")
        x = np.linspace(0.6, 2.0, 200)
        tg = res["input_reproduction"]["free_walking_speed"].get("target", {"mean": 1.34, "sd": 0.26})
        mu, sd = tg["mean"], max(tg["sd"], 0.02)
        lab = "Weidmann 1993: 1.34 ± 0.26" if (tg["mean"], tg["sd"]) == (1.34, 0.26) else f"シナリオ: {mu:g} ± {tg['sd']:g}（文献ではない）"
        a.plot(x, np.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi)), color=LIT, lw=2, ls="--", label=lab)
        a.set_xlabel("速さ（m/s）"), a.set_ylabel("確率密度"), a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    else:
        empty(ax[0], t, "データが少ない")
    # (2) 速さと密度
    t = "2. 密度ごとの速さ（自分の速さに対する比）"
    rho, v = sd_data
    a = ax[1]
    if len(rho):
        k = np.random.default_rng(0).choice(len(rho), min(len(rho), 3000), replace=False)
        a.scatter(rho[k], v[k], s=6, color=SIM, alpha=0.15, linewidths=0, label="計算（0.5 秒ごと）")
        bins = res["emergent"]["speed_density"]["bins"]
        if bins:
            a.plot([(b["rho"][0] + b["rho"][1]) / 2 for b in bins], [b["mean_ratio"] for b in bins], "o-", color=SIM, ms=8, lw=2, label="計算の平均")
        x = np.linspace(0.05, 4.0, 200)
        a.plot(x, [weidmann_speed(r) / 1.34 for r in x], color=LIT, lw=2, ls="--", label="Weidmann 1993（Kladek の式、v/v0）")
        a.set_xlim(0, 4.0), a.set_ylim(0, 1.3)
        a.set_xlabel("前の半円の密度（人/m²）"), a.set_ylabel("速さ ÷ その人の思う速さ"), a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    else:
        empty(a, t, "データなし")
    # (3) グループの人数
    t = "3. グループの人数（人の割合）"
    a = ax[2]
    xs = np.arange(5)
    series = [("計算", share, SIM)] + ([("入力の分布", exp_share, INPUT)] if exp_share else []) + \
             ([(f"文献（{lit['source']}）", lit["share"], LIT)] if lit else [])
    w = 0.8 / len(series)
    for i, (lab, sh, col) in enumerate(series):
        a.bar(xs + (i - (len(series) - 1) / 2) * w, sh, width=w - 0.03, color=col, label=lab)
    a.set_xticks(xs, ["1", "2", "3", "4", "5+"]), a.set_xlabel("グループの人数"), a.set_ylabel("人の割合"), a.set_ylim(0, 1)
    a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    # (4) グループの速さ
    t = "4. グループの速さ（入力の再現）"
    a = ax[3]
    if gsp and len({s for s, _ in gsp}) >= 2:
        sizes = sorted({s for s, _ in gsp})
        m = [np.mean([v for k, v in gsp if k == s]) for s in sizes]
        se = [np.std([v for k, v in gsp if k == s]) / math.sqrt(max(1, sum(1 for k, _ in gsp if k == s))) for s in sizes]
        a.errorbar(sizes, m, yerr=se, fmt="o", color=SIM, ms=8, lw=2, capsize=3, label="計算の平均 ± 標準誤差")
        x = np.array([1, max(sizes)])
        for sl, ls in ((-0.04, "--"), (-0.08, ":")):
            a.plot(x, m[0] + sl * (x - 1), color=LIT, lw=2, ls=ls, label=f"Moussaïd 2010: {sl} m/s/人")
        a.set_xticks(sizes), a.set_xlabel("グループの人数"), a.set_ylabel("速さ（m/s）"), a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    else:
        empty(a, t, "グループが少ない")
    # (5) ゲート
    t = "5. ゲートが混んだときの 1 人あたりの時間"
    a = ax[4]
    if len(gh) >= 10:
        a.axvspan(1.5, 4.0, color=BAND, label="Fruin 1987: カードの改札 1.5〜4.0 秒")
        a.hist(gh, bins=np.arange(0, 6.01, 0.25), color=SIM, edgecolor="white", linewidth=2, label=f"計算（列ができた {len(gh)} 回）")
        a.set_xlabel("前の人との間隔（秒）"), a.set_ylabel("回数"), a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    else:
        empty(a, t, "列ができた場面が少ない")
    # (6) 待つ人の距離
    t = "6. 待つ人どうしのいちばん近い距離（出てくる量）"
    a = ax[5]
    if len(ss) >= 20:
        a.hist(ss, bins=np.arange(0, 2.51, 0.1), color=SIM, edgecolor="white", linewidth=2, label=f"計算（{len(ss)}）")
        a.axvline(HALL_INTIMATE_M, color=LIT, lw=2, ls="--", label="Hall 1966: 密接の距離 0.45 m")
        a.set_xlabel("距離（m）"), a.set_ylabel("回数"), a.set_title(t, loc="left", color=INK), a.legend(loc="upper right")
    else:
        empty(a, t, "立って待つ場面が少ない")
    fig.suptitle(f"妥当性の確かめ: {res['scenario']}（{res['profile'] or 'プロファイルなし'}）", x=0.01, ha="left", color=INK, fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
