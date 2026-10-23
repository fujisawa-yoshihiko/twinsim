"""見て確かめる: 正解と MOPF の枠を重ねた動画、数えもらした場面の一覧の画像。"""

import json

import numpy as np

from .. import config
from .crossings import compare_crossings, expect, track_crossings
from .io import VIS_MIN, ensure_ids, load_mot_gt, load_tracks, open_run, tracks_dir_and_offset


def overlay(run_dir, camera, tracks_dir=None, scale=0.75, sheet_max=24):
    """mopf_eval/<カメラ>_overlay.mp4（緑の枠 = 正解（見えている人）、灰色 = ほとんど隠れた正解、色つき = MOPF の ID、黄色の線 = 通過線）と
    mopf_eval/<カメラ>_missed.png（線の数えもらしの場面）。数えもらしの前後は赤、ID の切り替わりは黄色の文字で示す。"""
    import subprocess

    import cv2
    from PIL import Image, ImageDraw, ImageFont
    run, gt, f0 = open_run(run_dir)
    tdir, f0 = tracks_dir_and_offset(run, tracks_dir, f0)
    fps = gt["fps"]
    G = load_mot_gt(run / "mot" / f"{camera}.txt")
    T = load_tracks(tdir / f"{camera}.jsonl")
    ids = ensure_ids(run, gt)
    name_of = {v: k for k, v in ids.items()}
    cfgp = run / "mopf" / camera / "config.json"
    lines = json.loads(cfgp.read_text())["lines"] if cfgp.exists() else []
    cmp_ = compare_crossings(run, camera, tracks_dir) if lines else {"missed": [], "extra": []}
    exp_ev = expect(run, camera)["events"] if lines else []
    got_ev = track_crossings(run, camera, tracks_dir) if lines else []
    ev = json.loads((run / "mopf_eval/summary.json").read_text())["cameras"].get(camera, {}) if (run / "mopf_eval/summary.json").exists() else {}
    switches = ev.get("switches", [])
    missed = cmp_["missed"]
    font = ImageFont.truetype(config.FONT_CJK, 20)
    small = ImageFont.truetype(config.FONT_CJK, 15)
    cap = cv2.VideoCapture(str(run / "video" / f"{camera}.mp4"))
    W0, H0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    W, H = int(W0 * scale) // 2 * 2, int(H0 * scale) // 2 * 2
    out = run / "mopf_eval" / f"{camera}_overlay.mp4"
    ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", str(out)], stdin=subprocess.PIPE)
    color = lambda i: tuple(int(c) for c in cv2.cvtColor(np.uint8([[[(i * 47) % 180, 200, 255]]]), cv2.COLOR_HSV2BGR)[0, 0])
    miss_at = {m["frame"]: m for m in missed[:sheet_max]}
    crops = []
    k = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        f = f0 + k
        img = cv2.resize(img, (W, H))
        sx, sy = W / W0, H / H0
        hot = {m["person"] for m in missed if -0.5 * fps <= f - m["frame"] <= 1.5 * fps}
        swp = [x for x in switches if -0.5 * fps <= f - x["frame"] <= 1.0 * fps]
        for pid, x0, y0, x1, y1, vis in G.get(f, []):
            n = name_of.get(pid)
            c, t = ((0, 0, 230), 3) if n in hot else (((60, 200, 60), 2) if vis >= VIS_MIN else ((150, 150, 150), 1))
            cv2.rectangle(img, (int(x0 * sx), int(y0 * sy)), (int(x1 * sx), int(y1 * sy)), c, t)
        for tid, x0, y0, x1, y1 in T.get(k, []):
            c = color(tid)
            cv2.rectangle(img, (int(x0 * sx) + 2, int(y0 * sy) + 2), (int(x1 * sx) - 2, int(y1 * sy) - 2), c, 1)
            cv2.putText(img, f"ID {tid}", (int(x0 * sx), max(12, int(y0 * sy) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
        for ln in lines:
            cv2.line(img, (int(ln["a"][0] * W), int(ln["a"][1] * H)), (int(ln["b"][0] * W), int(ln["b"][1] * H)), (0, 220, 255), 2)
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(pil)
        head = f"{f / fps:6.1f} 秒  {camera}"
        if lines:
            e_in = sum(1 for e in exp_ev if e["frame"] <= f and e["dir"] == "to_pos")
            e_out = sum(1 for e in exp_ev if e["frame"] <= f and e["dir"] == "to_neg")
            g_in = sum(1 for e in got_ev if e["frame"] <= f and e["dir"] == "to_pos")
            g_out = sum(1 for e in got_ev if e["frame"] <= f and e["dir"] == "to_neg")
            head += f"   正解なら 入館 {e_in}・退館 {e_out}   MOPF 入館 {g_in}・退館 {g_out}"
        d.rectangle([0, 0, W, 30], fill=(0, 0, 0))
        d.text((8, 3), head, font=font, fill=(255, 255, 255))
        y = 36
        for n in sorted(hot):
            d.text((8, y), f"数えもらし（{n}）", font=font, fill=(255, 60, 60))
            y += 26
        for x in swp[:3]:
            d.text((8, y), f"ID の切り替わり（{x['person']}、MOPF の ID {x['mopf_id']}）", font=font, fill=(255, 220, 0))
            y += 26
        d.text((8, H - 22), "緑 = 正解（見えている）・灰 = ほとんど隠れた正解・赤 = 線を数えもらした人・色つきの細い枠 = MOPF（ID）・黄色の線 = 通過線",
               font=small, fill=(255, 255, 255))
        img = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        if f in miss_at and lines:  # 線のまわりを切り出す
            ax = [ln["a"][0] * W for ln in lines] + [ln["b"][0] * W for ln in lines]
            ay = [ln["a"][1] * H for ln in lines] + [ln["b"][1] * H for ln in lines]
            cx0, cx1 = max(0, int(min(ax)) - 160), min(W, int(max(ax)) + 160)
            cy0, cy1 = max(0, int(min(ay)) - 200), min(H, int(max(ay)) + 120)
            crops.append((miss_at[f], img[cy0:cy1, cx0:cx1].copy()))
        ff.stdin.write(img.tobytes())
        k += 1
    ff.stdin.close()
    ff.wait()
    cap.release()
    files = [str(out)]
    if crops:
        ch, cw = max(c.shape[0] for _, c in crops), max(c.shape[1] for _, c in crops)
        cols = 4
        rows = (len(crops) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * cw, rows * (ch + 28)), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, (m, c) in enumerate(crops):
            x, y = (i % cols) * cw, (i // cols) * (ch + 28)
            sheet.paste(Image.fromarray(cv2.cvtColor(c, cv2.COLOR_BGR2RGB)), (x, y + 28))
            d.text((x + 6, y + 4), f"{m['t_s']} 秒 {m['person']}（{'入館' if m['dir'] == 'to_pos' else '退館'}）", font=small, fill=(0, 0, 0))
        sp = run / "mopf_eval" / f"{camera}_missed.png"
        sheet.save(sp)
        files.append(str(sp))
    return {"files": files, "frames": k, "missed": len(missed), "switches": len(switches)}
