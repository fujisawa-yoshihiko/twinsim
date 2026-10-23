"""実データ（ゲートの通過記録・EV の運行記録）でシナリオの値を合わせる。合わせた値には出典（ファイル・ハッシュ・日時）を残す。

記録の形（CSV、1 行目は列の名前。時刻は秒、記録の始まりを 0 にしなくてよい）:
  gate_log.csv  time_s, gate, lane, direction（in / out）[, person]     ゲートを 1 人が通るごとに 1 行
  ev_log.csv    time_s, car, boarded, alighted                          EV が基準の階（ロビー）に着くごとに 1 行。乗った・降りた人数は分かれば
シミュレータの結果から同じ形の記録を作れる（export_logs）。往復（書き出す → 合わせる）で、合わせ方が元の値に戻るかを確かめられる。

合わせるもの:
  到着の量     ゲートの入る向きの 1 分ごとの人数 → ゲートを通って入る流れの rate（piecewise、人/分）。流れどうしの割合は元のシナリオのまま
  ゲートの時間  同じレーン・同じ向きで、前の人との間隔が 4 秒以下のもの（列ができていた見込みが高い）に対数正規を当てる。30 回未満なら元のまま
  EV           号機ごとの着く間隔に対数正規を当てる（または replay で時刻をそのまま使う）。降りる人の平均（ポアソン）
実データ（竹芝の記録は NDA の対象）から作ったシナリオは git の外（既定は ~/dt-data/twinsim/calibration/<id>/）に置く。
"""

import copy
import csv
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml

from . import config
from .scenario import load_scenario, resolve_rate

OUT_ROOT = config.CALIBRATION
SATURATED_S = 4.0  # これ以下の間隔は、列ができていた（ゲートの時間で決まった）とみなす（Fruin のカードの改札の上限）


# ---- シミュレータの結果 → 記録の形 ----
def export_logs(run_dir, out=None):
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    out = Path(out) if out else run / "logs"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "gate_log.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "gate", "lane", "direction", "person"])
        for e in sorted(gt.get("gate_events", []), key=lambda e: e["t"]):
            w.writerow([e["t"], e["gate"], e["lane"], e["dir"], e["person"]])
    with open(out / "ev_log.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "car", "boarded", "alighted"])
        for e in sorted(gt.get("elevator_events", []), key=lambda e: e["t"]):
            w.writerow([e["t"], e["car"], len(e["boarded"]), len(e["alighted"])])
    return out


# ---- 読む・当てる ----
def _read(path):
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    if not rows:
        raise ValueError(f"{path}: 行がない")
    return rows


def _file_info(path, rows, tcol="time_s"):
    ts = [float(r[tcol]) for r in rows]
    return {"path": str(Path(path).resolve()), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16],
            "rows": len(rows), "time_span_s": [min(ts), max(ts)]}


def fit_lognormal(x, lo=None, hi=None):
    x = np.asarray(x, float)
    x = x[x > 0]
    lg = np.log(x)
    out = {"type": "lognormal", "median": round(float(np.exp(lg.mean())), 3), "sigma": round(float(lg.std(ddof=1)) if len(x) > 1 else 0.0, 3)}
    if lo is not None:
        out["min"] = lo
    if hi is not None:
        out["max"] = hi
    return out


def gate_rates(rows, t0, bin_s=60.0):
    """入る向きの人数を bin_s ごとに数える → [[区間の真ん中の秒, 人/分], ...]（t0 からの秒）。"""
    ts = sorted(float(r["time_s"]) - t0 for r in rows if r["direction"] == "in")
    if not ts:
        return []
    nb = int(math.ceil((max(ts) + 1e-6) / bin_s))
    c = Counter(int(t // bin_s) for t in ts)
    return [[round((k + 0.5) * bin_s, 1), round(c.get(k, 0) * 60.0 / bin_s, 3)] for k in range(nb)]


def gate_service(rows):
    lanes = defaultdict(list)
    for r in rows:
        lanes[(r["gate"], r["lane"], r["direction"])].append(float(r["time_s"]))
    hw = []
    for ts in lanes.values():
        ts.sort()
        hw += [b - a for a, b in zip(ts, ts[1:]) if 0 < b - a <= SATURATED_S]
    return hw


# ---- シナリオを合わせる ----
def calibrate(base, gate_log=None, ev_log=None, out_dir=None, ev_mode="fit", bin_s=60.0, cid=None):
    """base（テンプレートの名前・ファイル）を記録で合わせたシナリオを書く。返り値: (シナリオの場所, 報告)"""
    spec = load_scenario(base)
    raw = yaml.safe_load(Path(base).read_text(encoding="utf-8")) if Path(base).exists() else \
        yaml.safe_load((Path(__file__).resolve().parent.parent / "templates" / f"{base}.yaml").read_text(encoding="utf-8"))
    new = copy.deepcopy(raw)
    cid = cid or time.strftime("cal-%Y%m%d-%H%M%S")
    src = f"data:{cid}"
    rep = {"id": cid, "date": time.strftime("%Y-%m-%d %H:%M:%S"), "base": str(base), "files": [], "changes": [], "kept": []}
    t0 = None
    if gate_log:
        g = _read(gate_log)
        rep["files"].append({"kind": "gate_log", **_file_info(gate_log, g)})
        t0 = min(float(r["time_s"]) for r in g)
        rates = gate_rates(g, t0, bin_s)
        # ゲートを通って入る流れ（行き先に via があり、出どころがゲートの外＝入館の向きの手前の流れ）と、元のシナリオでの人/分の割合
        size_default = spec["people"].get("group_size")
        pois = spec_space_pois(spec)
        streams = []
        for i, s in enumerate(spec["streams"]):
            vias = {g for d in s.get("destinations", []) if isinstance(d, dict) for g in d.get("via", [])}
            if any(entering(pois, g, pois[s["origin"]]["xy"]) for g in vias if g in pois):
                _, note = resolve_rate(spec, s["rate"], s.get("group_size") or size_default)
                pm = note.get("persons_per_min")
                if pm is None:  # piecewise・constant（まとまり/分）を人/分に
                    r = s["rate"]
                    per = r["per_min"] if isinstance(r, dict) and r.get("type", "constant") == "constant" else \
                        float(np.mean([v for _, v in r["per_min"]])) if isinstance(r, dict) else float(r)
                    pm = per if (isinstance(r, dict) and r.get("unit") == "persons") else per * note["mean_group_size"]
                streams.append((i, pm))
        tot = sum(pm for _, pm in streams)
        for i, pm in streams:
            share = pm / tot if tot else 0.0
            new["streams"][i]["rate"] = {"type": "piecewise", "unit": "persons", "source": src,
                                         "per_min": [[t, round(v * share, 3)] for t, v in rates]}
            rep["changes"].append({"item": f"{new['streams'][i].get('name')}: 到着の量", "share_of_gate_in": round(share, 3),
                                   "mean_per_min": round(float(np.mean([v for _, v in rates])) * share, 3)})
        out_n = sum(1 for r in g if r["direction"] == "out")
        rep["gate"] = {"in": sum(1 for r in g if r["direction"] == "in"), "out": out_n, "per_min_in": rates}
        hw = gate_service(g)
        if len(hw) >= 30:
            fit = fit_lognormal(hw, lo=round(float(np.percentile(hw, 2)), 2), hi=SATURATED_S)
            fit["source"] = src
            for k in [k for k, p in (spec_space_pois(spec)).items() if p.get("kind") == "gate"]:
                new.setdefault("gates", {})[k] = {"service_s": fit}
            rep["changes"].append({"item": "ゲートの 1 人あたりの時間", "fit": fit, "n": len(hw)})
        else:
            rep["kept"].append({"item": "ゲートの 1 人あたりの時間", "reason": f"列ができていた見込みの間隔が {len(hw)} 回（30 回未満）"})
    if ev_log and spec.get("elevator"):
        e = _read(ev_log)
        rep["files"].append({"kind": "ev_log", **_file_info(ev_log, e)})
        t0 = t0 if t0 is not None else min(float(r["time_s"]) for r in e)
        by = defaultdict(list)
        for r in e:
            by[r["car"]].append(float(r["time_s"]) - t0)
        ev = new.setdefault("elevator", {})
        if ev_mode == "replay":
            ev["schedule"] = {"type": "times", "times": {c: sorted(round(x, 2) for x in v) for c, v in by.items()}, "source": src}
            rep["changes"].append({"item": "EV の着く時刻", "mode": "replay", "arrivals": {c: len(v) for c, v in by.items()}})
        else:
            iv = [b - a for v in by.values() for a, b in zip(sorted(v), sorted(v)[1:])]
            if len(iv) >= 5:
                fit = fit_lognormal(iv, lo=round(float(min(iv)), 1), hi=round(float(max(iv)), 1))
                first = [min(v) for v in by.values()]
                ev["schedule"] = {"type": "interval", "offset": {"type": "uniform", "min": 0.0, "max": round(float(np.median(iv)), 1)},
                                  "interval": fit, "source": src}
                rep["changes"].append({"item": "EV の着く間隔", "fit": fit, "n": len(iv), "first_arrival_s": [round(x, 1) for x in first]})
            else:
                rep["kept"].append({"item": "EV の着く間隔", "reason": f"間隔が {len(iv)} 個（5 個未満）"})
        al = [int(r["alighted"]) for r in e if r.get("alighted", "") != ""]
        if al and ev.get("alight") is not None:
            lam = round(float(np.mean(al)), 3)
            ev["alight"]["count"] = {"type": "poisson", "lam": lam, "source": src}
            rep["changes"].append({"item": "EV から降りる人（1 回あたり）", "lam": lam, "n": len(al)})
        bo = [int(r["boarded"]) for r in e if r.get("boarded", "") != ""]
        if bo:
            rep["ev"] = {"arrivals": len(e), "boarded_mean": round(float(np.mean(bo)), 2), "alighted_mean": round(float(np.mean(al)), 2) if al else None}
    new["name"] = f"{spec.get('name')}_{cid}"
    new["title"] = f"{spec.get('title', spec.get('name'))}（{cid} で合わせた）"
    new["calibration"] = {k: rep[k] for k in ("id", "date", "base", "files")}
    out = Path(out_dir).expanduser() if out_dir else OUT_ROOT / cid
    out.mkdir(parents=True, exist_ok=True)
    path = out / "scenario.yaml"
    head = (f"# {rep['date']} に記録で合わせたシナリオ（twinsim calibrate）。元: {base}。\n"
            f"# 値の出典は source: {src}（calibration の欄に記録のファイルとハッシュ）。\n"
            "# 竹芝の実データから作ったものは NDA の対象になりうる。git や共有の場所に置かない。\n")
    path.write_text(head + yaml.safe_dump(new, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    return path, rep


def entering(pois, gate, xy):
    """xy から gate を通ると入館の向きか（ゲートの線の真ん中から見て、in_dir の逆の側にいるか）。"""
    g = pois[gate]
    c = np.mean(np.asarray(g["line"], float), axis=0)
    return float((c - np.asarray(xy, float)) @ np.asarray(g.get("in_dir", [0.0, -1.0]), float)) > 0


def spec_space_pois(spec):
    from .space import load_space
    return load_space(spec["space"]).pois
