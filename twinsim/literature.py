"""文献に基づく人の分布（出典つき）。シナリオの people.profile・rate の lift_demand・確かめ（validity.py）が使う。

値ごとに「どの文献の、どの条件の値か」を書いておく。当てはまる条件が違う所（国・時間帯・建物の種類）は note に書き、
文献のない値は使わない（テンプレートで「仮」と書く）。一覧と使い方は docs/validity.md。
"""

import math

REFS = {
    "weidmann1993": {
        "cite": "Weidmann, U. (1993). Transporttechnik der Fussgänger. Schriftenreihe des IVT Nr. 90, ETH Zürich.",
        "use": "自由に歩く速さ 1.34 ± 0.26 m/s（平均 ± 標準偏差）、速さと密度の関係（Kladek の式）v0 = 1.34 m/s, γ = 1.913 /m², ρmax = 5.4 /m²",
        "check": "式と値は arXiv:1512.01426（The Social Force Model and its Relation to the Kladek Formula）の式 (1)・(7)–(9) で確認"},
    "moussaid2010": {
        "cite": "Moussaïd, M., Perozo, N., Garnier, S., Helbing, D., Theraulaz, G. (2010). The walking behaviour of pedestrian social groups "
                "and its impact on crowd dynamics. PLoS ONE 5(4): e10047.",
        "use": "グループの人数が 1 人増えるごとに速さが落ちる: 低密度（0.03 人/m²、平日の午後）で 0.04 m/s、中密度（0.25 人/m²、土曜の商店街）で 0.08 m/s。"
               "人数の分布は低密度ではゼロ切断ポアソンに合う。低密度では横一列、中密度では 3 人が V 字",
        "where": "フランス（トゥールーズ）の商店街"},
    "seyfried2005": {
        "cite": "Seyfried, A., Steffen, B., Klingsch, W., Boltes, M. (2005). The fundamental diagram of pedestrian movement revisited. "
                "Journal of Statistical Mechanics: Theory and Experiment, P10002.",
        "use": "1 列で歩くとき、速さ v で歩くのに要る前の人までの距離 d = 0.36 + 1.06 v（m）。エンジンの「前の人についていく」規則"},
    "seyfried2009": {
        "cite": "Seyfried, A., Passon, O., Steffen, B., Boltes, M., Rupprecht, T., Klingsch, W. (2009). New insights into pedestrian flow through "
                "bottlenecks. Transportation Science 43(3): 395–406.",
        "use": "幅 1.0 m のボトルネック（長さ 2.8 m）を通る流れ: 1.90〜2.19 人/(m·s)（実験の人数 60〜20 人）。基準の式（SFPE・Weidmann）の 1.2〜1.6 より多い",
        "check": "arXiv:physics/0702004 の表 2"},
    "coleman1961": {
        "cite": "Coleman, J. S., James, J. (1961). The equilibrium size distribution of freely-forming groups. Sociometry 24(1): 36–45.",
        "use": "自然にできる小さな集まりの人数はゼロ切断ポアソン分布に従う（分布の形）"},
    "zanlungo2014": {
        "cite": "Zanlungo, F., Ikeda, T., Kanda, T. (2014). Potential for the dynamics of pedestrians in a socially interacting group. "
                "Physical Review E 89: 012811.",
        "use": "大阪の地下の歩行者空間で、人数の割合が 1 人 82%・2 人 15%・3 人 3%・4 人以上 1% 未満",
        "check": "Nicolas & Hassan (2021) arXiv:2107.13293 の表 1 から（人の数の割合）"},
    "zanlungo2017": {
        "cite": "Zanlungo, F., Yücel, Z., Brščić, D., Kanda, T., Hagita, N. (2017). Intrinsic group behaviour: dependence of pedestrian dyad "
                "dynamics on principal social and personal features. PLoS ONE 12(11): e0187253.",
        "use": "大阪 ATC の 2 人連れ（1018 組）: 速さは同僚 1.274・友人 1.138・夫婦 1.099・家族 1.094 m/s、仕事の目的 1.271・余暇 1.118 m/s。"
               "2 人の距離 r は同僚 0.851 m（横 0.718 m）、友人 0.792 m（横 0.662 m）、夫婦 0.714 m（横 0.600 m）、家族 0.863 m（横 0.583 m）",
        "where": "日本（大阪 ATC）、低〜中密度"},
    "nicolas2021": {
        "cite": "Nicolas, A., Hassan, F. H. (2021). Social groups in pedestrian crowds: review of their influence on the dynamics and their "
                "modelling. arXiv:2107.13293.",
        "use": "グループの割合は場所で大きく違う（1 人の割合が数 % から 80% 超まで）。平日やラッシュは少ない。1 人の速さは研究で 1.0〜1.4 m/s"},
    "peters2011": {
        "cite": "Peters, R., Smith, R., Evans, E. (2011). The appraisal of lift passenger demand in modern office buildings. "
                "Building Services Engineering Research and Technology 32(2).",
        "use": "今のオフィスの EV の利用: 朝の山は入る 85%・出る 10%・階の間 5%、昼の山は入る 45%・出る 45%・階の間 10%。"
               "いちばん混む 5 分の利用者は観測した在館人数の 12〜13% ほど（図 11 の最大）。昔の設計の目安は 5 分で 15%",
        "where": "ヨーロッパ・北米・UAE のオフィス"},
    "fruin1987": {
        "cite": "Fruin, J. J. (1987). Pedestrian Planning and Design, rev. ed. (改札の表は TCRP Report 90 Vol. 2, 2003 に再掲)",
        "use": "改札の 1 人あたりの間隔（観測の平均）: カードを読む改札 1.5〜4.0 s（25〜40 人/分）、自由に通れる入口 1.0〜1.5 s（40〜60 人/分）",
        "check": "TCRP の再掲の表から。列の対応は人/分と秒の整合で確かめた"},
    "peters_transfer": {
        "cite": "Peters Research (Elevate の既定値) / CIBSE Guide D の計算例",
        "use": "EV の乗り降りは 1 人あたり 1.0 s（行き先階の予約式では 0.8 s）。CIBSE Guide D の計算例は 1.2 s"},
    "hall1966": {
        "cite": "Hall, E. T. (1966). The Hidden Dimension. Doubleday.",
        "use": "人と人の距離の帯: 密接 0〜0.45 m、個体 0.45〜1.2 m、社会 1.2〜3.6 m"},
    "brown2005": {
        "cite": "Brown, L., Gans, N., Mandelbaum, A., Sakov, A., Shen, H., Zeltyn, S., Zhao, L. (2005). Statistical analysis of a telephone "
                "call center: a queueing-science perspective. JASA 100(469): 36–50.",
        "use": "人が応対する時間（サービス時間）は対数正規分布に近い（形の根拠。受付の時間への当てはめは類推）"},
}

# 速さと密度の関係（Weidmann 1993 の Kladek の式）
WEIDMANN_FD = {"v0": 1.34, "gamma": 1.913, "rho_max": 5.4, "source": "weidmann1993"}


def weidmann_speed(rho, v0=1.34, gamma=1.913, rho_max=5.4):
    """密度 rho（人/m²）での歩く速さ（m/s）。v = v0 (1 − exp(−γ (1/ρ − 1/ρmax)))。"""
    if rho <= 1e-9:
        return v0
    if rho >= rho_max:
        return 0.0
    return v0 * (1.0 - math.exp(-gamma * (1.0 / rho - 1.0 / rho_max)))


def ztp_lambda_for_mean(mean):
    """平均の人数がその値になるゼロ切断ポアソンの λ（λ / (1 − e^−λ) = mean を二分法で解く）。"""
    lo, hi = 1e-6, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if mid / (1 - math.exp(-mid)) < mean:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def ztp_person_share(lam, nmax=5):
    """ゼロ切断ポアソン（グループの数の分布）から、グループの人数ごとの「人の数の割合」[1 人, 2 人, ...]。"""
    pg = [lam ** n / math.factorial(n) for n in range(1, nmax + 1)]
    pp = [n * p for n, p in zip(range(1, nmax + 1), pg)]
    s = sum(pp)
    return [p / s for p in pp]


def person_share_to_group_mean(share):
    """人の数の割合 [1 人, 2 人, ...] → グループの平均の人数。"""
    groups = [s / n for n, s in enumerate(share, start=1)]
    return sum(share) / sum(groups)


# 観察された人数の割合（人の数の割合、[1, 2, 3, 4, 5+]）
GROUP_SHARE = {
    "osaka_underground": {"share": [0.82, 0.15, 0.03, 0.0, 0.0], "source": "zanlungo2014", "note": "日本・地下の歩行者空間（通勤を含む）"},
    "toulouse_low": {"share": [0.46, 0.37, 0.10, 0.04, 0.03], "source": "moussaid2010", "note": "商店街・平日の午後・低密度（Nicolas & Hassan 2021 の表 1）"},
    "toulouse_moderate": {"share": [0.29, 0.51, 0.12, 0.05, 0.03], "source": "moussaid2010", "note": "商店街・土曜の午後・中密度"},
    "nottingham_station": {"share": [0.44, 0.36, 0.10, 0.05, 0.04], "source": "nicolas2021", "note": "英国の駅（Singh & Drury 2009、時間帯の区別なし）"},
}

# EV の利用の内訳（Peters ら 2011）
LIFT_MIX = {"morning": {"incoming": 0.85, "outgoing": 0.10, "interfloor": 0.05},
            "lunch": {"incoming": 0.45, "outgoing": 0.45, "interfloor": 0.10}}


def _ztp_from_share(key):
    return round(ztp_lambda_for_mean(person_share_to_group_mean(GROUP_SHARE[key]["share"])), 3)


# people.profile の中身（シナリオに書いた値が優先）
PROFILES = {
    "office_commute_jp": {
        "title": "日本のオフィスの朝の出勤",
        "people": {
            "speed": {"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9},
            "group_size": {"type": "zero_truncated_poisson", "lam": _ztp_from_share("osaka_underground")},
            "group_speed": {"model": "moussaid2010", "slope_m_s": 0.04},
            "group_lateral_m": 0.72,
            "speed_density": dict(WEIDMANN_FD),
        },
        "gate_service_s": {"type": "lognormal", "median": 2.0, "sigma": 0.25, "min": 1.2, "max": 4.0},
        "elevator": {"transfer_s": 1.0},
        "sources": {"speed": "weidmann1993", "group_size": "zanlungo2014", "group_speed": "moussaid2010",
                    "group_lateral_m": "zanlungo2017", "speed_density": "weidmann1993", "gate_service_s": "fruin1987",
                    "transfer_s": "peters_transfer", "demand": "peters2011"},
        "notes": ["グループの割合は大阪の地下の歩行者空間の値（オフィスのロビーそのものの値ではない）",
                  "グループの横の間隔は大阪 ATC の同僚の 2 人連れの値",
                  "ゲートは 1987 年のカードを読む改札の範囲の中ほど（1 人ごとのばらつきの形は仮）。今の IC カードのゲートはもっと速い可能性がある"],
        "title_en": "Morning commute to a Japanese office",
        "notes_en": ["The group share is from an underground pedestrian space in Osaka (not from an office lobby itself)",
                     "The lateral spacing of groups is that of colleague dyads at Osaka ATC",
                     "The gate value is the middle of the range for 1987 card-reading turnstiles (the per-person spread is provisional); "
                     "today's IC-card gates may be faster"],
    },
    "leisure_low_density": {
        "title": "余暇の人出（昼・商業、低密度）",
        "people": {
            "speed": {"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9},
            "group_size": {"type": "zero_truncated_poisson", "lam": _ztp_from_share("toulouse_low")},
            "group_speed": {"model": "moussaid2010", "slope_m_s": 0.04},
            "group_lateral_m": 0.66,
            "speed_density": dict(WEIDMANN_FD),
        },
        "sources": {"speed": "weidmann1993", "group_size": "moussaid2010", "group_speed": "moussaid2010",
                    "group_lateral_m": "zanlungo2017", "speed_density": "weidmann1993"},
        "notes": ["グループの割合はトゥールーズの商店街（平日の午後）の値", "横の間隔は大阪 ATC の友人の 2 人連れ"],
        "title_en": "Leisure crowd (midday, commercial, low density)",
        "notes_en": ["The group share is from a shopping street in Toulouse (weekday afternoon)", "The lateral spacing is that of friend dyads at Osaka ATC"],
    },
}


def lift_demand_per_min(d, flow):
    """建物の人数と混む 5 分の割合から、EV を使う人の流れ（人/分）。d: {population, peak_pct_5min, period, level}。"""
    period = d.get("period", "morning")
    if period not in LIFT_MIX:
        raise ValueError(f"demand.period は {sorted(LIFT_MIX)} のどれか（{period}）")
    if "population" not in d:
        raise ValueError("lift_demand には demand.population（建物にいる人数）が要る")
    total = float(d["population"]) * float(d.get("peak_pct_5min", 12.0)) / 100.0 / 5.0
    return total * LIFT_MIX[period][flow] * float(d.get("level", 1.0))
