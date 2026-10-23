"""複数のカメラを時刻でそろえて、同じ人が各カメラで MOPF のどの ID で検知されたかを見る。

  identities   正解の人ごとに、カメラごとの MOPF の ID と時間帯、カメラの間の移動時間 → mopf_eval/identities.json・identities.csv
               MOPF の ID ごとに、どの人を追っていたか（1 つの ID が何人にまたがったか = 取り違え）も書く
  sync_video   カメラを横に並べ、同じ時刻のコマを並べた動画（mopf_eval/sync.mp4）。同じ人は全カメラで同じ色、
               枠に「人 / MOPF の ID」。別のカメラに現れたときに「前のカメラでは ID a → このカメラでは ID b、移動 x 秒」を出す
対応づけ: コマごとに、見えている正解の枠（見えている割合 0.4 以上）と MOPF の枠を IoU 0.3 以上で 1 対 1 に（ハンガリー法）。
MOPF はカメラごとに ID を付ける（カメラをまたいで同じ ID にはならない）。ここでの「同じ人」は正解（シミュレータ）による。
"""

import colorsys
import csv
import json
from collections import Counter, defaultdict

import numpy as np

from .. import config
from .io import IOU_MIN, VIS_MIN, ensure_ids, iou_matrix, load_mot_gt, load_tracks, open_run, tracks_dir_and_offset

GAP_FRAMES = 15  # 同じ ID のひと続きとみなす途切れ（0.5 秒）


def match_frames(run, gt, camera, tracks_dir=None, f0=0):
    """{シミュレータのコマ: {"pairs": {人: MOPF の ID}, "missed": [人], "extra": [ID], "boxes": {...}}}"""
    from scipy.optimize import linear_sum_assignment
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    T = load_tracks(tdir / f"{camera}.jsonl")
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    name_of = {v: k for k, v in ensure_ids(run, gt).items()}
    out = {}
    for k, tr in T.items():
        f = f0 + k
        gv = [x for x in G.get(f, []) if x[5] >= VIS_MIN and x[0] in name_of]
        pairs, used = {}, set()
        if gv and tr:
            m = iou_matrix([x[1:5] for x in gv], [x[1:5] for x in tr])
            r, c = linear_sum_assignment(-m)
            for i, j in zip(r, c):
                if m[i, j] >= IOU_MIN:
                    pairs[name_of[gv[i][0]]] = tr[j][0]
                    used.add(j)
        out[f] = {"pairs": pairs, "missed": [name_of[x[0]] for x in gv if name_of[x[0]] not in pairs],
                  "extra": [tr[j][0] for j in range(len(tr)) if j not in used],
                  "gt_boxes": {name_of[x[0]]: x[1:5] for x in gv}, "mopf_boxes": {t[0]: t[1:5] for t in tr}}
    # 動画のコマで追跡がない所も、正解の見逃しとして入れる
    nf = (max(T) + 1) if T else 0
    for k in range(nf):
        f = f0 + k
        if f not in out:
            gv = [x for x in G.get(f, []) if x[5] >= VIS_MIN and x[0] in name_of]
            out[f] = {"pairs": {}, "missed": [name_of[x[0]] for x in gv], "extra": [], "gt_boxes": {name_of[x[0]]: x[1:5] for x in gv},
                      "mopf_boxes": {}}
    return out


def _segments(items, fps):
    """[(コマ, キー)] → キーごとのひと続き [{key, t0, t1, frames}]（GAP_FRAMES までの途切れはつなぐ）"""
    by = defaultdict(list)
    for f, key in items:
        by[key].append(f)
    segs = []
    for key, fs in by.items():
        fs.sort()
        s = fs[0]
        prev = fs[0]
        n = 1
        for f in fs[1:]:
            if f - prev > GAP_FRAMES:
                segs.append({"key": key, "t0": round(s / fps, 2), "t1": round(prev / fps, 2), "frames": n})
                s, n = f, 0
            prev = f
            n += 1
        segs.append({"key": key, "t0": round(s / fps, 2), "t1": round(prev / fps, 2), "frames": n})
    return sorted(segs, key=lambda x: x["t0"])


def identities(run_dir, cameras=None, tracks_dir=None):
    run, gt, f0 = open_run(run_dir)
    tdir, _ = tracks_dir_and_offset(run, tracks_dir, f0)
    cams = cameras or [c for c in gt["cameras"] if (tdir / f"{c}.jsonl").exists()]  # シナリオのカメラの順（ゲート → EV 前）
    fps = gt["fps"]
    M = {c: match_frames(run, gt, c, tracks_dir, f0) for c in cams}
    persons = defaultdict(lambda: {"cams": {}, "visible": {}})
    ids = {}
    for c in cams:
        per_person = defaultdict(list)
        vis = defaultdict(list)
        per_id = defaultdict(list)
        for f, r in M[c].items():
            for n, tid in r["pairs"].items():
                per_person[n].append((f, tid))
                per_id[tid].append((f, n))
            for n in list(r["pairs"]) + r["missed"]:
                vis[n].append((f, "v"))
        for n, items in per_person.items():
            persons[n]["cams"][c] = [{"mopf_id": s["key"], "t0": s["t0"], "t1": s["t1"], "frames": s["frames"]} for s in _segments(items, fps)]
        for n, items in vis.items():
            sv = _segments(items, fps)
            persons[n]["visible"][c] = [[s["t0"], s["t1"]] for s in sv]
        ids[c] = {str(tid): [{"person": s["key"], "t0": s["t0"], "t1": s["t1"], "frames": s["frames"]} for s in _segments(items, fps)]
                  for tid, items in sorted(per_id.items())}
    # カメラの間の移動: 前のカメラで最後に見えた時刻 → 次のカメラで最初に見えた時刻
    for n, p in persons.items():
        info = gt["people"].get(n, {})
        p["type"], p["stream"] = info.get("type"), info.get("stream")
        seen = sorted((v[0][0], v[-1][1], c) for c, v in p["visible"].items() if v)
        p["handovers"] = []
        for (_, a1, ca), (b0, _, cb) in zip(seen, seen[1:]):
            ia = [s["mopf_id"] for s in p["cams"].get(ca, [])]
            ib = [s["mopf_id"] for s in p["cams"].get(cb, [])]
            p["handovers"].append({"from": ca, "to": cb, "t_from": a1, "t_to": b0, "dt": round(b0 - a1, 2),
                                   "id_from": ia[-1] if ia else None, "id_to": ib[0] if ib else None})
    persons = dict(sorted(persons.items(), key=lambda kv: min((v[0][0] for v in kv[1]["visible"].values() if v), default=1e9)))
    res = {"cameras": cams, "persons": persons, "mopf_ids": ids,
           "note": "MOPF の ID はカメラごと。同じ人（正解）が各カメラでどの ID だったか。1 つの ID が何人にまたがったかは mopf_ids"}
    out = run / "mopf_eval"
    out.mkdir(exist_ok=True)
    (out / "identities.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    with open(out / "identities.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["person", "type", *[f"{c} の MOPF の ID（秒）" for c in cams], "カメラの間（秒）"])
        for n, p in persons.items():
            cells = ["・".join(f"{s['mopf_id']}（{s['t0']}〜{s['t1']}）" for s in p["cams"].get(c, [])) or "-" for c in cams]
            ho = "・".join(f"{h['from']} ID {h['id_from']} → {h['to']} ID {h['id_to']}（{h['dt']}）" for h in p["handovers"]) or "-"
            w.writerow([n, p["type"], *cells, ho])
    return res, M


def _pcolor(name):
    h = (sum(ord(c) * 31 ** i for i, c in enumerate(name)) % 997) / 997
    r, g, b = colorsys.hsv_to_rgb(h, 0.8, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)  # OpenCV は BGR


def _pred_lookup(pred, fps):
    """links.json → (カメラ, MOPF の ID) ごとの [(始まりのコマ, 終わりのコマ, 予測の番号)] と、予測の番号ごとの多い人（採点の表示用）"""
    spans = defaultdict(list)
    votes = defaultdict(Counter)
    for t in pred["tracklets"]:
        spans[(t["camera"], t["mopf_id"])].append((round(t["t0"] * fps), round(t["t1"] * fps), t["global_id"]))
        if t.get("person"):
            votes[t["global_id"]][t["person"]] += round((t["t1"] - t["t0"]) * fps)
    return spans, {g: v.most_common(1)[0][0] for g, v in votes.items()}


def sync_video(run_dir, cameras=None, tracks_dir=None, width=800, pred=None):
    """カメラを横に並べ、同じ時刻のコマを並べた動画。pred なし: mopf_eval/sync.mp4（正解の人の名前 / MOPF の ID）。
    pred（links.json の中身）あり: mopf_eval/sync_pred.mp4（予測の番号 / MOPF の ID。正解の人と合っているかを ○・× で、予測したカメラの間の組を下に）。"""
    import subprocess

    import cv2
    from PIL import Image, ImageDraw, ImageFont
    run, gt, f0 = open_run(run_dir)
    res, M = identities(run, cameras, tracks_dir)
    cams = res["cameras"]
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    fps = gt["fps"]
    caps = {c: cv2.VideoCapture(str(run / "video" / f"{c}.mp4")) for c in cams}
    W0 = {c: int(caps[c].get(cv2.CAP_PROP_FRAME_WIDTH)) for c in cams}
    H0 = {c: int(caps[c].get(cv2.CAP_PROP_FRAME_HEIGHT)) for c in cams}
    h = int(width * H0[cams[0]] / W0[cams[0]]) // 2 * 2
    head, foot = 40, 150
    WW, HH = width * len(cams), h + head + foot
    out = run / "mopf_eval" / ("sync_pred.mp4" if pred else "sync.mp4")
    spans, gperson = _pred_lookup(pred, fps) if pred else ({}, {})

    def gid_at(c, tid, f):
        for a, b, g in spans.get((c, tid), ()):
            if a <= f <= b:
                return g
        return None
    ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WW}x{HH}", "-r", str(fps), "-i", "-",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", str(out)], stdin=subprocess.PIPE)
    try:
        font = ImageFont.truetype(config.FONT_CJK, 20)
        small = ImageFont.truetype(config.FONT_CJK, 15)
    except OSError:
        font = small = ImageFont.load_default()
    # 別のカメラに現れたときの知らせ（3 秒）
    notices = []
    if pred:
        for c in pred["cross_links"]:
            tail = "○ 正解と同じ人" if c["correct"] else f"× 正解は {c['person_from']} → {c['person_to']}"
            cz = f"・色の z {c['color_z']}" if c.get("color_z") is not None else ""
            notices.append((c["t_to"], f"予測 {c['global_id']}: {c['from_camera']} ID {c['mopf_id_from']} → {c['to_camera']} ID {c['mopf_id_to']}"
                                       f"（間 {c['gap']} 秒{cz}）{tail}", (30, 140, 60) if c["correct"] else (200, 40, 40)))
    else:
        for n, p in res["persons"].items():
            for ho in p["handovers"]:
                notices.append((ho["t_to"], f"{n}: {ho['from']} では ID {ho['id_from'] if ho['id_from'] is not None else 'なし'} → "
                                             f"{ho['to']} では ID {ho['id_to'] if ho['id_to'] is not None else 'なし'}（移動 {ho['dt']} 秒）", (200, 60, 0)))
    nf = int(min(c.get(cv2.CAP_PROP_FRAME_COUNT) for c in caps.values()))
    for k in range(nf):
        f = f0 + k
        canvas = np.full((HH, WW, 3), 245, np.uint8)
        labels = []
        for ci, c in enumerate(cams):
            ok, img = caps[c].read()
            if not ok:
                img = np.zeros((H0[c], W0[c], 3), np.uint8)
            img = cv2.resize(img, (width, h))
            s = width / W0[c]
            r = M[c].get(f, {"pairs": {}, "missed": [], "extra": [], "gt_boxes": {}, "mopf_boxes": {}})
            for n, b in r["gt_boxes"].items():  # 正解: 細い枠（予測の動画では灰色）
                col = (170, 170, 170) if pred else _pcolor(n)
                cv2.rectangle(img, (int(b[0] * s), int(b[1] * s)), (int(b[2] * s), int(b[3] * s)), col, 1)
            for n, tid in r["pairs"].items():  # 対応した MOPF の枠: 太い枠
                b = r["mopf_boxes"][tid]
                if pred:  # 予測の番号の色。正解の人と、その番号の多い人が同じなら ○
                    g = gid_at(c, tid, f)
                    col = _pcolor(g or f"{c}{tid}")
                    mark = "" if g is None else ("○" if gperson.get(g) == n else "×")
                    text = f"{g or '-'} / ID {tid} {mark}"
                else:
                    col, text = _pcolor(n), f"{n} / ID {tid}"
                cv2.rectangle(img, (int(b[0] * s), int(b[1] * s)), (int(b[2] * s), int(b[3] * s)), col, 3)
                labels.append((ci * width + int(b[0] * s), head + max(0, int(b[1] * s) - 20), text, col))
            for n in r["missed"]:
                b = r["gt_boxes"][n]
                cv2.rectangle(img, (int(b[0] * s), int(b[1] * s)), (int(b[2] * s), int(b[3] * s)), (40, 40, 230), 2)
                labels.append((ci * width + int(b[0] * s), head + max(0, int(b[1] * s) - 20), f"{n} / 見逃し", (40, 40, 230)))
            for tid in r["extra"]:
                b = r["mopf_boxes"][tid]
                cv2.rectangle(img, (int(b[0] * s), int(b[1] * s)), (int(b[2] * s), int(b[3] * s)), (200, 200, 200), 1)
                g = gid_at(c, tid, f) if pred else None
                labels.append((ci * width + int(b[0] * s), head + max(0, int(b[1] * s) - 20), f"{g + ' / ' if g else ''}ID {tid}?", (200, 200, 200)))
            canvas[head:head + h, ci * width:(ci + 1) * width] = img
        pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        d.rectangle([0, 0, WW, head], fill=(30, 30, 30))
        d.text((10, 8), f"{f / fps:6.1f} 秒", font=font, fill=(255, 255, 255))
        for ci, c in enumerate(cams):
            d.text((ci * width + 120, 8), c, font=font, fill=(255, 255, 255))
        for x, y, t, col in labels:
            tw = d.textlength(t, font=small)
            d.rectangle([x, y, x + tw + 6, y + 18], fill=(0, 0, 0))
            d.text((x + 3, y), t, font=small, fill=(col[2], col[1], col[0]))
        y = head + h + 6
        now = f / fps
        for _, msg, col in [n for n in notices if 0 <= now - n[0] <= 3.0][:3]:
            d.text((10, y), msg, font=font, fill=col)
            y += 26
        # 今どちらかのカメラにいる人の ID の一覧
        cur = []
        for n in sorted({n for c in cams for n in M[c].get(f, {}).get("pairs", {})} | {n for c in cams for n in M[c].get(f, {}).get("missed", [])}):
            parts = []
            for c in cams:
                r = M[c].get(f, {})
                if n in r.get("pairs", {}):
                    parts.append(f"{c} ID {r['pairs'][n]}")
                elif n in r.get("missed", []):
                    parts.append(f"{c} 見逃し")
            cur.append(f"{n}（{'・'.join(parts)}）")
        if not pred:
            d.text((10, y), "今: " + "  ".join(cur[:8]) + (" …" if len(cur) > 8 else ""), font=small, fill=(40, 40, 40))
        legend = ("太い枠 = MOPF（予測の番号の色。2 台で同じ番号なら同じ色）・「G… / ID …」= 予測の番号 / MOPF の ID・○ = 正解の人と合う・× = 違う人・"
                  "細い灰色の枠 = 正解・赤 = 見逃し" if pred else
                  "細い枠 = 正解（人ごとの色、2 台で同じ色）・太い枠 = MOPF（対応した人の色）・赤 = 見逃し・灰 = 対応する人のいない MOPF の枠")
        d.text((10, HH - 22), legend, font=small, fill=(90, 90, 90))
        ff.stdin.write(cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR).tobytes())
    ff.stdin.close()
    ff.wait()
    for c in caps.values():
        c.release()
    return {"file": str(out), "frames": nf, "persons": len(res["persons"]),
            "handovers": sum(len(p["handovers"]) for p in res["persons"].values())}
