"""空間の確かめ・意味の地図を描くための図: 真上の図に、歩ける所（青）・座標の目盛り（2 m・10 m）・候補の prim（candidates.json）・
いまの場所（pois）とゾーンを重ねる。真上の図のない空間（多角形から作った空間・合成の廊下）は、歩ける所の格子から平面図を描いて重ねる。
使い方: python -m twinsim show-space <名前・フォルダ・ファイル> → 空間のフォルダの annotate.png（書けなければ今のフォルダの <名前>_annotate.png）
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import config
from .camera import Camera, camera_dict
from .space import load_space

PLAN_MAX_PX, PLAN_PPM, PLAN_PAD = 1600, 40.0, 40  # 平面図の長い辺の上限（画素）・1 m の画素の上限・まわりの余白


def _plan(sp):
    """真上の図のない空間の平面図: (図, 世界の座標 → 図の画素)。歩ける所は明るい灰色、歩けない所は暗い灰色。"""
    x0, y0 = sp.x0 - sp.res / 2, sp.y0 - sp.res / 2  # 格子の左下の角
    w_m, h_m = sp.nx * sp.res, sp.ny * sp.res
    ppm = min(PLAN_PPM, (PLAN_MAX_PX - 2 * PLAN_PAD) / max(w_m, h_m))
    W, H = int(round(w_m * ppm)), int(round(h_m * ppm))
    cells = np.where(sp.grid[::-1], 232, 80).astype(np.uint8)  # 行 0 が y の最大
    img = Image.new("RGB", (W + 2 * PLAN_PAD, H + 2 * PLAN_PAD), (255, 255, 255))
    img.paste(Image.fromarray(cells).convert("RGB").resize((W, H), Image.NEAREST), (PLAN_PAD, PLAN_PAD))

    def P(x, y):
        return PLAN_PAD + (x - x0) * ppm, PLAN_PAD + (y0 + h_m - y) * ppm
    return img, P


def draw(name, scale=1.0, out=None):
    """name は load_space に渡せるもの（名前・フォルダ・ファイルの場所・dict）。out を省くと空間のフォルダの annotate.png。"""
    sp = load_space(name)
    lv = sp.spec["levels"][0]
    plan = "top_view" not in lv or not lv.get("top_image")
    if plan:
        img, P = _plan(sp)
        W, H = img.size
        ink = {"grid": (205, 205, 205), "major": (150, 150, 150), "label": (60, 60, 60), "zone": (200, 40, 40),
               "poi": (0, 130, 60), "cand": (220, 120, 0), "cand_text": (170, 90, 0)}
    else:
        tv = lv["top_view"]
        img = Image.open(sp.folder / lv["top_image"]).convert("RGB")
        W, H = img.size
        top = Camera(camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"]))
        sx, sy = W / tv["width"], H / tv["height"]

        def P(x, y):
            uv, _ = top.project([(x, y, sp.z)])
            return float(uv[0][0]) * sx, float(uv[0][1]) * sy

        over = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(over)
        half = sp.res / 2
        for i, j in zip(*np.nonzero(sp.grid)):
            x, y = sp.center(i, j)
            a, b = P(x - half, y - half), P(x + half, y + half)
            d.rectangle([min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])], fill=(40, 110, 230, 70))
        img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
        ink = {"grid": (200, 200, 200), "major": (255, 255, 255), "label": (255, 255, 0), "zone": (255, 80, 80),
               "poi": (0, 255, 120), "cand": (255, 140, 0), "cand_text": (255, 200, 120)}
    d = ImageDraw.Draw(img)
    f = config.font(11)
    fb = config.font(13)
    x0, x1, y0, y1 = sp.bounds()
    for gx in np.arange(math.ceil(x0 / 2) * 2, x1 + 0.01, 2):
        major = int(round(gx)) % 10 == 0
        d.line([P(gx, y0), P(gx, y1)], fill=ink["major"] if major else ink["grid"], width=1)
        if major:
            d.text((P(gx, y0)[0], H - 16), f"x={int(gx)}", font=f, fill=ink["label"], anchor="mt")  # 範囲の端は図の外のことがある
    for gy in np.arange(math.ceil(y0 / 2) * 2, y1 + 0.01, 2):
        major = int(round(gy)) % 10 == 0
        d.line([P(x0, gy), P(x1, gy)], fill=ink["major"] if major else ink["grid"], width=1)
        if major:
            d.text((PLAN_PAD - 4, P(x0, gy)[1]) if plan else P(x0, gy), f"y={int(gy)}", font=f, fill=ink["label"], anchor="rm")  # 平面図は余白に
    cand = sp.folder / "candidates.json"
    if cand.exists():
        for c in json.loads(cand.read_text()):
            if any(k in c["name"].lower() for k in ("elevator", "door", "stair", "gate", "reception", "entrance", "escalator", "turnstile")):
                cx, cy = (c["min"][0] + c["max"][0]) / 2, (c["min"][1] + c["max"][1]) / 2
                u, v = P(cx, cy)
                d.ellipse([u - 3, v - 3, u + 3, v + 3], fill=ink["cand"])
                d.text((u + 4, v), c["name"][:24], font=f, fill=ink["cand_text"], anchor="lm")
    for z, poly in sp.zones.items():
        pts = [P(*q) for q in poly]
        d.line(pts + [pts[0]], fill=ink["zone"], width=2)
        d.text((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)), z, font=fb, fill=ink["zone"], anchor="mm")
    for k, p in sp.pois.items():
        try:
            u, v = P(*sp.poi_xy(k))
        except Exception:
            continue
        if isinstance(p.get("line"), list) and len(p["line"]) == 2:  # 線の場所（入口の幅・ゲート）
            d.line([P(*p["line"][0]), P(*p["line"][1])], fill=ink["poi"], width=3)
        if p.get("hidden"):  # 扉の向こうの点（人が現れる・消える）
            d.line([(u, v), P(*p["hidden"])], fill=ink["poi"], width=1)
        d.ellipse([u - 5, v - 5, u + 5, v + 5], outline=ink["poi"], width=2)
        d.text((u + 7, v), k, font=fb, fill=ink["poi"], anchor="lm")
    if plan:
        d.text((PLAN_PAD, 8), f"{sp.name}（格子 {sp.res} m、明るい所が歩ける所）", font=fb, fill=ink["label"], anchor="lt")
    if scale != 1.0:
        img = img.resize((int(W * scale), int(H * scale)))
    if out is not None:
        out = Path(out).expanduser()
        img.save(out)
        return out
    out = sp.folder / "annotate.png" if (sp.folder / "space.yaml").exists() or (sp.folder / "space.json").exists() else None
    try:
        if out is None:  # dict・ファイルで渡した空間は、今のフォルダに名前をつけて書く（ほかの空間の図を上書きしないように）
            raise OSError
        img.save(out)
    except OSError:  # pip で入れた空間のフォルダには書けないことがある
        out = Path.cwd() / f"{sp.name}_annotate.png"
        img.save(out)
    return out
