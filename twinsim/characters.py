"""人物モデル（Isaac Sim 6.1 の Isaac/People/Characters）。背の高さは Isaac Sim の中で測った値（hospital-sim の s80 の記録）。
服の色は描画のときに人ごとに変える（golden ratio で色相をずらす。digitaltwin の s86 と同じ方法）。
"""

import colorsys

MODELS = {  # 名前: (性別, 背の高さ m)
    "F_Business_02": ("F", 1.607),
    "F_Medical_01": ("F", 1.684),
    "M_Medical_01": ("M", 1.788),
    "female_adult_police_01_new": ("F", 1.687),
    "female_adult_police_02": ("F", 1.688),
    "female_adult_police_03_new": ("F", 1.671),
    "male_adult_construction_01_new": ("M", 1.797),
    "male_adult_construction_03": ("M", 1.781),
    "male_adult_construction_05_new": ("M", 1.773),
    "male_adult_police_04": ("M", 1.771),
}
CLOTH = ("opaque__fabric", "opaque__leather", "retro__reflective", "opaque__plastic")  # 色を変える素材の名前の頭（肌・髪は変えない）
GOLDEN = 0.618033988749895


def tint(k, part):
    """k 番目の人の、part 番目の服の素材の色合い（RGB 0〜1）。"""
    h = (k * GOLDEN + part * 0.37) % 1.0
    s = 0.45 + 0.4 * ((k * 7 + part * 3) % 5) / 4
    v = 0.6 + 0.4 * ((k * 3 + part) % 3) / 2
    return tuple(round(c, 3) for c in colorsys.hsv_to_rgb(h, s, v))
