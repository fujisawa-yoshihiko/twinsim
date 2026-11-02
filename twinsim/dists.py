"""シナリオに書く分布（docs/spec.md の「分布の書き方」）から値を引く。どれも random.Random（乱数の種でそろう）を使う。

書き方の例:
  1.34                                        定数
  {type: normal, mean: 1.34, sd: 0.26, min: 0.8, max: 1.9}
  {type: uniform, min: 30, max: 50}
  {type: lognormal, median: 20, sigma: 0.5, min: 3, max: 120}
  {type: poisson, lam: 1.5}
  {type: zero_truncated_poisson, lam: 0.6}     0 を除いたポアソン（まとまりの人数。Coleman & James 1961）
  {type: choice, values: {staff: 0.7, visitor: 0.3}}
人の量（到着の率）は rate として別に書く（arrival_times）。per_min はグループ（まとまり）の数/分:
  {type: constant, per_min: 8}
  {type: piecewise, per_min: [[0, 4], [120, 12], [300, 6]]}   時刻（秒）と率の折れ線（時間帯で変わるポアソン過程）
  {type: constant, per_min: 8, unit: persons}                 人/分（グループの平均の人数で割って使う。scenario.resolve_rate）
  {type: lift_demand, flow: incoming}                          建物の人数から（Peters ら 2011。scenario.resolve_rate）
"""

import math
import random


def sample(spec, rng):
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return spec
    if isinstance(spec, str):
        return spec
    t = spec.get("type", "constant")
    if t == "constant":
        v = spec["value"]
    elif t == "uniform":
        v = rng.uniform(spec["min"], spec["max"])
    elif t == "normal":
        v = rng.gauss(spec["mean"], spec["sd"])
    elif t == "lognormal":
        v = spec["median"] * math.exp(rng.gauss(0.0, spec["sigma"]))
    elif t == "poisson":
        v = poisson(spec["lam"], rng)
    elif t == "zero_truncated_poisson":
        v = 1 + poisson_ge1_minus1(spec["lam"], rng)
    elif t == "choice":
        v = choice(spec["values"], rng)
    else:
        raise ValueError(f"分布の種類 {t} は使えない（constant・uniform・normal・lognormal・poisson・zero_truncated_poisson・choice）")
    if isinstance(v, (int, float)):
        if "min" in spec and t not in ("uniform",):
            v = max(v, spec["min"])
        if "max" in spec and t not in ("uniform",):
            v = min(v, spec["max"])
    return v


def mean(spec):
    """分布の平均（人/分をグループ/分に直す・EV の間隔の平均などに使う）。式で出せない形は乱数で 4000 回引いて平均する。"""
    if isinstance(spec, (int, float)):
        return float(spec)
    t = spec.get("type", "constant")
    clipped = "min" in spec or "max" in spec
    if t == "constant":
        return float(spec["value"])
    if t == "uniform":
        return (spec["min"] + spec["max"]) / 2.0
    if t == "zero_truncated_poisson":
        lam = spec["lam"]
        return lam / (1.0 - math.exp(-lam)) if lam > 0 else 1.0
    if t == "poisson" and not clipped:
        return float(spec["lam"])
    rng = random.Random(0)
    return sum(float(sample(spec, rng)) for _ in range(4000)) / 4000.0


def poisson(lam, rng):
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def poisson_ge1_minus1(lam, rng):
    """0 を除いたポアソン分布から引いた値 − 1。lam が 0 以下なら 0（mean と同じ扱い）。"""
    if lam <= 0:
        return 0
    while True:
        k = poisson(lam, rng)
        if k >= 1:
            return k - 1


def choice(values, rng):
    """{名前: 重み} か [名前, ...]（同じ重み）から 1 つ。"""
    if isinstance(values, dict):
        items = list(values.items())
    else:
        items = [(v, 1.0) for v in values]
    total = sum(w for _, w in items)
    r = rng.random() * total
    for k, w in items:
        r -= w
        if r <= 0:
            return k
    return items[-1][0]


def rate_at(spec, t):
    """到着の率（人/秒）。"""
    if isinstance(spec, (int, float)):
        return spec / 60.0
    if spec.get("type", "constant") == "constant":
        return spec["per_min"] / 60.0
    pts = spec["per_min"]
    if t <= pts[0][0]:
        return pts[0][1] / 60.0
    for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return (r0 + (r1 - r0) * (t - t0) / max(t1 - t0, 1e-9)) / 60.0
    return pts[-1][1] / 60.0


def arrival_times(spec, t_end, rng, t_start=0.0):
    """率が時刻で変わるポアソン過程の到着の時刻（間引き法）。{type: times, times: [秒, ...]} なら決めた時刻（確かめ用）。"""
    if isinstance(spec, dict) and spec.get("type") == "times":
        return [float(t) for t in spec["times"] if t_start <= float(t) < t_end]
    if isinstance(spec, dict) and spec.get("type") == "piecewise":
        rmax = max(r for _, r in spec["per_min"]) / 60.0
    else:
        rmax = rate_at(spec, 0.0)
    if rmax <= 0:
        return []
    out, t = [], t_start
    while True:
        t += rng.expovariate(rmax)
        if t >= t_end:
            return out
        if rng.random() <= rate_at(spec, t) / rmax:
            out.append(t)
