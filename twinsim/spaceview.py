"""空間の確かめ・意味の地図を描くための図: 真上の図に、歩ける所（青）・座標の目盛り（2 m・10 m）・候補の prim（candidates.json）・
いまの場所（pois）とゾーンを重ねる。使い方: python -m twinsim show-space <名前> → spaces/<名前>/annotate.png
"""

import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .camera import Camera, camera_dict
from .space import load_space

FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def draw(name, scale=1.0):
    sp = load_space(name)
    lv = sp.spec["levels"][0]
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
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 11)
    fb = ImageFont.truetype(FONT, 13)
    x0, x1, y0, y1 = sp.bounds()
    for gx in np.arange(math.ceil(x0 / 2) * 2, x1 + 0.01, 2):
        major = int(round(gx)) % 10 == 0
        d.line([P(gx, y0), P(gx, y1)], fill=(255, 255, 255) if major else (200, 200, 200), width=1)
        if major:
            d.text(P(gx, y0), f"x={int(gx)}", font=f, fill=(255, 255, 0), anchor="mt")
    for gy in np.arange(math.ceil(y0 / 2) * 2, y1 + 0.01, 2):
        major = int(round(gy)) % 10 == 0
        d.line([P(x0, gy), P(x1, gy)], fill=(255, 255, 255) if major else (200, 200, 200), width=1)
        if major:
            d.text(P(x0, gy), f"y={int(gy)}", font=f, fill=(255, 255, 0), anchor="rm")
    cand = sp.folder / "candidates.json"
    if cand.exists():
        for c in json.loads(cand.read_text()):
            if any(k in c["name"].lower() for k in ("elevator", "door", "stair", "gate", "reception", "entrance", "escalator", "turnstile")):
                cx, cy = (c["min"][0] + c["max"][0]) / 2, (c["min"][1] + c["max"][1]) / 2
                u, v = P(cx, cy)
                d.ellipse([u - 3, v - 3, u + 3, v + 3], fill=(255, 140, 0))
                d.text((u + 4, v), c["name"][:24], font=f, fill=(255, 200, 120), anchor="lm")
    for z, poly in sp.zones.items():
        pts = [P(*q) for q in poly]
        d.line(pts + [pts[0]], fill=(255, 80, 80), width=2)
        d.text((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)), z, font=fb, fill=(255, 80, 80), anchor="mm")
    for k in sp.pois:
        try:
            u, v = P(*sp.poi_xy(k))
        except Exception:
            continue
        d.ellipse([u - 5, v - 5, u + 5, v + 5], outline=(0, 255, 120), width=2)
        d.text((u + 7, v), k, font=fb, fill=(0, 255, 120), anchor="lm")
    if scale != 1.0:
        img = img.resize((int(W * scale), int(H * scale)))
    out = sp.folder / "annotate.png"
    img.save(out)
    return out
