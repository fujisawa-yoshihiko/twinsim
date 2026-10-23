"""MOPF（~/MOPF_ALL_video）の人流モニターの設定を、シミュレータのカメラと空間から自動で作る。

シミュレータはカメラの行列と床の座標を正確に知っているので、手で 4 点を合わせる代わりに、
床の上の格子点を「カメラの映像の上（0〜1）」と「真上の図の上（0〜1）」の両方に映して対応を作る。
作るもの（MOPF の outputs/live_monitor/config.json と同じ形）:
  lines   ゲートの線（入館の向きに横切ると pos_label）
  zones   カメラに 6 割以上映るゾーン（MOPF のエリア）
  floor   床の図（空間の真上の図）と、射影変換 H・対応の点
使い方: twinsim mopf <結果の場所> --camera CamEV [--apply]（--apply は動いている MOPF の API に送る）
"""

import json
import shutil
import urllib.request
import uuid
from pathlib import Path

import numpy as np

from .. import config
from ..camera import Camera, camera_dict
from ..space import load_space


def homography(src, dst):
    """src・dst（N×2、4 点以上）の射影変換（DLT の最小二乗）。"""
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(A, float))
    H = vt[-1].reshape(3, 3)
    H /= H[2, 2]
    if (H @ np.array([src[0][0], src[0][1], 1.0]))[2] < 0:
        H = -H
    return H


LINE_OFFSET_M = 1.0  # office_gate_ev・CamGate で、0 m だと入館の 72%、1 m で 93% を MOPF が数えた（docs/integration.md の 3）


def build_config(gt, camera, step=1.0, line_offset_m=LINE_OFFSET_M):
    """line_offset_m: 通過線をゲートから入館の向きへずらす距離（m）。ゲートが人の現れる所（扉の陰）に近いと、
    現れた時点で線を越えていて数えられないので、少し内側に引く。"""
    sp = load_space(gt["space"])
    cam = Camera(gt["cameras"][camera])
    lv = sp.spec["levels"][0]
    tv = lv["top_view"]
    top = Camera(camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"]))

    def norm(c, pts):
        uv, d = c.project([(x, y, 0.0) for x, y in pts])
        return uv / np.array([c.w, c.h]), d

    # 対応: カメラに映る床（歩ける所）の格子点
    x0, x1, y0, y1 = sp.bounds()
    pts = [(x, y) for x in np.arange(x0, x1, step) for y in np.arange(y0, y1, step)
           if sp.walkable(x, y) and cam.sees_floor(sp, x, y)]
    if len(pts) < 8:
        raise ValueError(f"カメラ {camera} に映る床の点が少ない（{len(pts)}）")
    cam_n, _ = norm(cam, pts)
    plan_n, _ = norm(top, pts)
    ok = (cam_n[:, 0] > 0.02) & (cam_n[:, 0] < 0.98) & (cam_n[:, 1] > 0.02) & (cam_n[:, 1] < 0.98)
    cam_n, plan_n = cam_n[ok], plan_n[ok]
    H = homography(cam_n, plan_n)
    pred = np.c_[cam_n, np.ones(len(cam_n))] @ H.T
    err = np.linalg.norm(pred[:, :2] / pred[:, 2:] - plan_n, axis=1)
    sel = np.linspace(0, len(cam_n) - 1, min(24, len(cam_n))).astype(int)
    lines = []
    for k, g in gt.get("gates", {}).items():
        lane = np.array(g["lanes"])
        d = np.array(g["in_dir"])
        n = np.array([-d[1], d[0]])
        c = lane.mean(0) + d * line_offset_m
        half = np.abs((lane - c) @ n).max() + 0.6
        a, b = c - n * half, c + n * half
        ab_n, depth = norm(cam, [tuple(a), tuple(b)])
        if np.any(depth <= 0.1) or np.any(ab_n < -0.2) or np.any(ab_n > 1.2):
            continue
        probe, _ = norm(cam, [tuple(c + d * 0.8)])  # 入館の向きの先の点が +1 の側になるように a・b の順を決める
        A, B = ab_n[0] * [cam.w, cam.h], ab_n[1] * [cam.w, cam.h]
        P = probe[0] * [cam.w, cam.h]
        side = (B[0] - A[0]) * (P[1] - A[1]) - (B[1] - A[1]) * (P[0] - A[0])
        if side < 0:
            ab_n = ab_n[::-1]
        lines.append({"name": k, "a": ab_n[0].clip(0, 1).tolist(), "b": ab_n[1].clip(0, 1).tolist(), "pos_label": "入館", "neg_label": "退館"})
    zones = []
    for z, poly in sp.zones.items():
        inside = [(x, y) for x in np.arange(min(p[0] for p in poly), max(p[0] for p in poly), 0.5)
                  for y in np.arange(min(p[1] for p in poly), max(p[1] for p in poly), 0.5) if sp.walkable(x, y) and sp.zone_of(x, y) == z]
        if not inside:
            continue
        seen = sum(cam.sees_floor(sp, x, y) for x, y in inside) / len(inside)
        if seen < 0.6:
            continue
        pn, depth = norm(cam, poly)
        if np.any(depth <= 0.1):
            continue
        zones.append({"name": z, "points": pn.clip(0, 1).tolist(), "max_people": None, "max_dwell_s": None})
    floor = {"image": "floor.jpg", "H": H.tolist(), "cam_points": cam_n[sel].tolist(), "plan_points": plan_n[sel].tolist()}
    return {"lines": lines, "zones": zones, "floor": floor, "max_people_total": None}, {
        "points": int(len(cam_n)), "reproj_err_median": round(float(np.median(err)), 5), "reproj_err_max": round(float(err.max()), 5),
        "floor_image": str(sp.folder / lv["top_image"])}


def write(run_dir, camera, out=None, line_offset_m=LINE_OFFSET_M):
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    cfg, info = build_config(gt, camera, line_offset_m=line_offset_m)
    info["line_offset_m"] = line_offset_m
    out = Path(out) if out else run / "mopf" / camera
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))
    shutil.copy(info["floor_image"], out / "floor.jpg")
    (out / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    return out, cfg, info


def apply(out_dir, base=None):
    """動いている MOPF に送る（床の図 → 位置合わせ → 線とエリア）。"""
    base = base or f"{config.MOPF_URL}/api/live"
    out = Path(out_dir)
    cfg = json.loads((out / "config.json").read_text())
    boundary = uuid.uuid4().hex
    img = (out / "floor.jpg").read_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"floor.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() \
        + img + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{base}/floor/image", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    urllib.request.urlopen(req, timeout=30).read()

    def put(path, obj):
        r = urllib.request.Request(f"{base}{path}", data=json.dumps(obj).encode(), method="PUT", headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(r, timeout=30).read())
    put("/floor/calibration", {"cam_points": cfg["floor"]["cam_points"], "plan_points": cfg["floor"]["plan_points"]})
    return put("/config", {"lines": cfg["lines"], "zones": cfg["zones"], "max_people_total": cfg["max_people_total"]})
