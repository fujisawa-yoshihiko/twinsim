"""MOPF の追跡を床に写した図（マッピングの結果）: 真上の図の上に、左は正解の軌跡（カメラに見えていた人）、右は MOPF の足元を床に移した軌跡（ID ごとの色）。
mopf_eval/<カメラ>_floor.png。カメラの映る範囲（床）を点線で、ゾーンを灰色で描く。足元は枠の下の真ん中なので、体の手前の端に当たる（0.2〜0.3 m ずれる）。"""

import colorsys
import json

import numpy as np

from .. import config
from ..camera import Camera, camera_dict
from ..space import load_space
from .graph import floor_tracks
from .io import VIS_MIN, ensure_ids, load_mot_gt, load_tracks, open_run, tracks_dir_and_offset


def _color(i):
    r, g, b = colorsys.hsv_to_rgb((i * 0.137) % 1.0, 0.85, 0.9)
    return int(r * 255), int(g * 255), int(b * 255)


def floormap(run_dir, camera, tracks_dir=None):
    from PIL import Image, ImageDraw, ImageFont
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    sp = load_space(gt["space"])
    lv = sp.spec["levels"][0]
    tv = lv.get("top_view")
    if not (tv and lv.get("top_image")):
        raise ValueError(f"空間 {sp.name} に真上の図がない")
    top = Camera(camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"]))
    base = Image.open(sp.folder / lv["top_image"]).convert("RGB")
    base = Image.blend(base, Image.new("RGB", base.size, "white"), 0.45)

    def P(pts):
        uv, _ = top.project([(x, y, 0.0) for x, y in pts])
        return [tuple(map(float, p)) for p in uv]

    T = load_tracks(tdir / f"{camera}.jsonl")
    F = floor_tracks(gt, camera, T, f0)
    nf = (max(T) + 1) if T else 0
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    ids = ensure_ids(run, gt)
    name_of = {v: k for k, v in ids.items()}
    cam = Camera(gt["cameras"][camera])
    # 正解: カメラに見えていたコマの位置
    gt_paths = {}
    for f in range(f0, f0 + nf):
        for pid, *_, vis in G.get(f, []):
            n = name_of.get(pid)
            if n is None or vis < VIS_MIN:
                continue
            p = gt["people"][n]
            k = f - p["start_frame"]
            tr = gt["tracks"][n]
            if 0 <= k < len(tr):
                gt_paths.setdefault(n, []).append((f, tr[k][0], tr[k][1]))
    mopf_paths = {}
    for f in sorted(F):
        for tid, x, y in F[f]:
            mopf_paths.setdefault(tid, []).append((f, x, y))
    # カメラの映る範囲（歩ける所の格子点のうち、カメラに映るもの）
    x0, x1, y0, y1 = sp.bounds()
    seen = [(x, y) for x in np.arange(x0, x1, 0.5) for y in np.arange(y0, y1, 0.5) if sp.walkable(x, y) and cam.sees_floor(sp, x, y)]
    try:
        font = ImageFont.truetype(config.FONT_CJK, 22)
        small = ImageFont.truetype(config.FONT_CJK, 16)
    except OSError:
        font = small = ImageFont.load_default()

    def panel(paths, title, by_id):
        img = base.copy()
        d = ImageDraw.Draw(img, "RGBA")
        for poly in sp.zones.values():
            q = P(poly)
            d.line(q + [q[0]], fill=(120, 120, 120, 160), width=1)
        for x, y in seen:
            (u, v), = P([(x, y)])
            d.ellipse([u - 1.5, v - 1.5, u + 1.5, v + 1.5], fill=(40, 120, 220, 90))
        for i, (key, pts) in enumerate(sorted(paths.items(), key=lambda kv: str(kv[0]))):
            pts = pts[::5]
            if len(pts) < 2:
                continue
            q = P([(x, y) for _, x, y in pts])
            col = _color(key if by_id else i) + (210,)
            d.line(q, fill=col, width=2)
            d.ellipse([q[-1][0] - 3, q[-1][1] - 3, q[-1][0] + 3, q[-1][1] + 3], fill=col)
        ex, ey = P([tuple(gt["cameras"][camera]["eye"][:2])])[0]
        d.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=(220, 30, 30, 255))
        d.rectangle([0, 0, img.width, 34], fill=(255, 255, 255, 230))
        d.text((10, 5), title, font=font, fill=(20, 20, 20))
        return img

    left = panel(gt_paths, f"正解の軌跡（{camera} に見えていた {len(gt_paths)} 人）", False)
    right = panel(mopf_paths, f"MOPF の足元を床に写した軌跡（ID {len(mopf_paths)} 本）", True)
    # カメラと軌跡のまわりだけを切り出して拡大する（建物全体だと小さくて見えない）
    allp = P([(x, y) for paths in (gt_paths, mopf_paths) for pts in paths.values() for _, x, y in pts[::10]]
             + [tuple(gt["cameras"][camera]["eye"][:2])])
    us, vs = [u for u, _ in allp], [v for _, v in allp]
    m = 60
    box = (max(0, int(np.percentile(us, 1)) - m), max(0, int(np.percentile(vs, 1)) - m - 34),
           min(left.width, int(np.percentile(us, 99)) + m), min(left.height, int(np.percentile(vs, 99)) + m))
    sc = min(3.0, 1000 / max(1, box[2] - box[0]))

    def crop(img, title):
        c = img.crop(box).resize((int((box[2] - box[0]) * sc), int((box[3] - box[1]) * sc)))
        d = ImageDraw.Draw(c)
        d.rectangle([0, 0, c.width, 34], fill=(255, 255, 255))
        d.text((10, 5), title, font=font, fill=(20, 20, 20))
        return c
    left = crop(left, f"正解の軌跡（{camera} に見えていた {len(gt_paths)} 人）")
    right = crop(right, f"MOPF の足元を床に写した軌跡（ID {len(mopf_paths)} 本）")
    out = Image.new("RGB", (left.width * 2 + 10, left.height + 30), "white")
    out.paste(left, (0, 0))
    out.paste(right, (left.width + 10, 0))
    d = ImageDraw.Draw(out)
    ev = run / "mopf_eval" / "summary.json"
    note = ""
    if ev.exists():
        r = json.loads(ev.read_text())["cameras"].get(camera, {})
        note = f"足元のずれ 中央 {r.get('foot_error_m_median')} m・90% {r.get('foot_error_m_p90')} m、ID の切り替わり {r.get('num_switches')}"
    d.text((10, left.height + 5), f"点 = カメラに映る床、赤い丸 = カメラ、線の色 = 人（右は MOPF の ID）。{note}", font=small, fill=(40, 40, 40))
    path = run / "mopf_eval" / f"{camera}_floor.png"
    path.parent.mkdir(exist_ok=True)
    out.save(path)
    return {"file": str(path), "gt_people": len(gt_paths), "mopf_ids": len(mopf_paths)}
