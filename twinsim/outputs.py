"""計算の結果を書き出す（形式は docs/spec.md の「出力」）。

  ground_truth.json   研究側（~/MOPF_ALL_video/research の cctv_eval_lib・flow_tasks）が読める正解（tracks・moving・people・cameras）に、
                      状態・グループ・EV・ゲートの出来事を足したもの
  frames.csv.gz       1 コマ 1 人 1 行（frame, t, person, x, y, yaw, moving, state, zone, group, type）
  tasks.json          p7 の 6 タスクの正解の集計（ゾーンの人数・ゲートの通過・滞留・グループ・混み具合・行き先）と EV の待ち時間
  graph/              GNN 向け: ゾーンのグラフと 2 m の格子のグラフ、ノードの人数の時系列、辺の流れ、行き先の表、カメラから見えるノード
  mot/<カメラ>.txt     MOTChallenge の形式の枠（frame, id, x, y, w, h, 1, 1, 見えている割合）。見えている割合は近似（camera.py）
  preview.png         真上の図に、人の軌跡・ゾーン・カメラの向きを重ねた確認の図
  summary.json        人数・状態ごとの時間・EV・ゲートなどの要約と、書き出したファイル
"""

import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import yaml

from .camera import Camera, boxes_with_visibility, camera_dict
from .engine import state_runs

STOP_STATES = ("gate_queue", "ev_wait", "reception", "dwell", "sign_check", "companion_wait")


def resolve_cameras(spec, space):
    out = {}
    W, H = spec["render"]["width"], spec["render"]["height"]
    for c in spec["cameras"]:
        base = dict(space.spec.get("cameras", {}).get(c["name"], {}))
        base.update(c)
        extra = {k: base[k] for k in ("clock_offset_s", "drop_rate", "note") if k in base}
        out[c["name"]] = camera_dict(c["name"], base["eye"], base["target"], base.get("width", W), base.get("height", H),
                                     base.get("focal_mm", 12.0), base.get("h_aperture_mm", 20.955), spec["fps"], extra)
    return out


def write_all(sim, builder, spec, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sp = sim.space
    fps, total = sim.fps, sim.total
    agents = [a for a in sim.agents if a.frames]
    cams = resolve_cameras(spec, sp)
    files = []

    (out / "scenario_resolved.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    files.append("scenario_resolved.yaml")

    # ---- 正解 ----
    people, tracks, moving = {}, {}, {}
    for a in agents:
        f0, f1 = a.frames[0][0], a.frames[-1][0]
        info = {k: v for k, v in a.info.items() if k not in ("origin_xy", "alight_zones")}
        info.update({"start_frame": f0, "arrive_frame": f1, "speed_m_s": round(a.speed, 3), "group": a.group,
                     "flow": f"{a.info.get('origin')}->{a.info.get('destination')}",
                     "events": a.events, "states": state_runs(a.states, f0)})
        people[a.name] = info
        tracks[a.name] = [[round(x, 4), round(y, 4), round(((yaw + 180) % 360) - 180, 2)] for _, x, y, yaw, _ in a.frames]
        moving[a.name] = [1 if m else 0 for *_, m in a.frames]
    first_car = sim.cars[0] if sim.cars else None
    gt = {"fps": fps, "total_frames": total, "seed": spec["seed"], "space": sp.name, "scenario": spec.get("name"),
          "people": people, "cameras": cams, "tracks": tracks, "moving": moving,
          "elevator_times": sorted(x for c in sim.cars for x in c.arrivals if x < total / fps),
          "cars": {c.name: {"door": list(c.door), "inside": list(c.inside), "capacity": c.capacity} for c in sim.cars},
          "elevator_events": sim.ev_events, "gate_events": sim.gate_events,
          "spots": [list(s) for s in sim.spots], "door": list(first_car.door) if first_car else None,
          "gates": {k: {"lanes": [ln.center.tolist() for ln in g.lanes], "in_dir": g.in_dir.tolist(), "service_s": g.service_s}
                    for k, g in sim.gates.items()},
          "zones": {k: [list(p) for p in v] for k, v in sp.zones.items()},
          "note": "tracks[name][k] = [x, y, yaw_deg] は people[name]['start_frame'] + k のコマ（現れてから消えるまで）。moving は歩いているか。"
                  "people[name]['states'] は [始まりのコマ, 終わりのコマ, 状態]。events・*_events は秒。座標は世界の m（Z が上）"}
    (out / "ground_truth.json").write_text(json.dumps(gt, ensure_ascii=False))
    files.append("ground_truth.json")

    # ---- 1 コマずつの表 ----
    zone_cache = {}

    def zone(x, y):
        k = (round(x, 1), round(y, 1))
        if k not in zone_cache:
            zone_cache[k] = sp.zone_of(x, y)
        return zone_cache[k]

    per_frame = defaultdict(list)  # コマ → [(名前, x, y, 状態, 背の高さ)]
    with gzip.open(out / "frames.csv.gz", "wt", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "t", "person", "x", "y", "yaw", "moving", "state", "zone", "group", "type"])
        for a in agents:
            for (f, x, y, yaw, mv), st in zip(a.frames, a.states):
                z = zone(x, y)
                w.writerow([f, round(f / fps, 3), a.name, round(x, 3), round(y, 3), round(((yaw + 180) % 360) - 180, 1), int(mv), st, z or "",
                            a.group or "", a.info.get("type", "")])
                per_frame[f].append((a.name, x, y, st, a.info["height_m"], z))
    files.append("frames.csv.gz")

    # ---- タスクの集計 ----
    tasks = task_aggregates(sim, agents, per_frame, spec)
    (out / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False))
    files.append("tasks.json")

    # ---- グラフ ----
    if "graph" in spec["outputs"]:
        files += write_graph(sim, agents, per_frame, cams, out / "graph", spec)

    # ---- カメラごとの枠 ----
    if "mot" in spec["outputs"]:
        files += write_mot(sp, cams, per_frame, total, out / "mot", spec)

    if "preview" in spec["outputs"]:
        try:
            write_preview(sp, agents, cams, out / "preview.png")
            files.append("preview.png")
        except Exception as e:  # 図は確認用なので、失敗しても計算の結果は残す
            print("preview failed:", e)

    states_s = Counter()
    for a in agents:
        for st in a.states:
            states_s[st] += 1 / fps
    waits = [a.events["board"] - a.events["wait_start"] for a in agents if "board" in a.events and "wait_start" in a.events]
    summary = {"scenario": spec.get("name"), "space": sp.name, "seed": spec["seed"], "duration_s": spec["duration_s"], "fps": fps,
               "people": len(agents), "groups": len({a.group for a in agents if a.group}),
               "by_stream": Counter(a.info.get("stream") for a in agents), "by_destination": Counter(str(a.info.get("destination")) for a in agents),
               "state_seconds": {k: round(v, 1) for k, v in states_s.most_common()},
               "max_present": max((len(v) for v in per_frame.values()), default=0),
               "elevator": {"arrivals": len(sim.ev_events), "boarded": sum(len(e["boarded"]) for e in sim.ev_events),
                            "alighted": sum(len(e["alighted"]) for e in sim.ev_events),
                            "wait_mean_s": round(float(np.mean(waits)), 1) if waits else None,
                            "wait_max_s": round(float(np.max(waits)), 1) if waits else None},
               "gate_passes": Counter(e["dir"] for e in sim.gate_events),
               "still_waiting_at_end": len(sim.queue), "files": files + ["summary.json"]}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def task_aggregates(sim, agents, per_frame, spec):
    sp, fps, total = sim.space, sim.fps, sim.total
    secs = list(range(0, total, fps))
    zones = list(sp.zones)
    area = {z: sp.zone_area(z) for z in zones}
    counts = {z: [] for z in zones}
    by_state = defaultdict(lambda: [0] * len(secs))
    present = []
    for k, f in enumerate(secs):
        rows = per_frame.get(f, [])
        present.append(len(rows))
        c = Counter(r[5] for r in rows)
        for z in zones:
            counts[z].append(c.get(z, 0))
        for r in rows:
            by_state[r[3]][k] += 1
    lv = spec.get("congestion_levels", [0.10, 0.20])
    density = {z: [round(n / area[z], 3) if area[z] else 0.0 for n in counts[z]] for z in zones}
    level = {z: [int(sum(d >= t for t in lv)) for d in density[z]] for z in zones}
    minutes = int(math.ceil(total / fps / 60))
    gate_min = {}
    for e in sim.gate_events:
        key = f"{e['gate']}:{e['dir']}"
        gate_min.setdefault(key, [0] * minutes)[min(int(e["t"] // 60), minutes - 1)] += 1
    dwell = []
    for a in agents:
        f0 = a.frames[0][0]
        for s0, s1, st in state_runs(a.states, f0):
            if st in STOP_STATES and (s1 - s0 + 1) / fps >= 3.0:
                k = s0 - f0
                dwell.append({"person": a.name, "state": st, "start_s": round(s0 / fps, 2), "end_s": round(s1 / fps, 2),
                              "zone": sp.zone_of(a.frames[k][1], a.frames[k][2])})
    groups = defaultdict(list)
    for a in agents:
        if a.group:
            groups[a.group].append(a.name)
    od = Counter()
    for a in agents:
        od[(int(a.frames[0][0] / fps // 60), str(a.info.get("origin")), str(a.info.get("destination")))] += 1
    waits = [{"person": a.name, "car": a.events.get("car"), "wait_s": round(a.events["board"] - a.events["wait_start"], 2)}
             for a in agents if "board" in a.events and "wait_start" in a.events]
    return {"seconds": len(secs), "zones": zones, "zone_area_m2": {z: round(area[z], 1) for z in zones},
            "1_count": {"present": present, "by_zone": counts, "by_state": dict(by_state)},
            "2_direction": {"gate_per_min": gate_min, "gate_events": sim.gate_events},
            "3_dwell": dwell,
            "4_group": {k: v for k, v in groups.items() if len(v) > 1},
            "5_congestion": {"levels_per_m2": lv, "density": density, "level": level},
            "6_trend": {"od_per_min": [{"minute": m, "origin": o, "destination": d, "count": n} for (m, o, d), n in sorted(od.items())]},
            "elevator": {"waits": waits, "events": sim.ev_events}}


def write_graph(sim, agents, per_frame, cams, folder, spec, cell_m=None):
    folder.mkdir(parents=True, exist_ok=True)
    sp, fps, total = sim.space, sim.fps, sim.total
    cell_m = cell_m or float(spec.get("graph", {}).get("cell_m", 2.0))
    files = []
    # ゾーンのグラフ: ノード = ゾーン、辺 = 歩ける格子でとなり合うゾーン
    lab = np.full(sp.grid.shape, -1, int)
    zones = list(sp.zones)
    for i in range(sp.ny):
        for j in range(sp.nx):
            if sp.grid[i, j]:
                z = sp.zone_of(*sp.center(i, j))
                if z is not None:
                    lab[i, j] = zones.index(z)
    adj = set()
    for i in range(sp.ny):
        for j in range(sp.nx):
            a = lab[i, j]
            if a < 0:
                continue
            for di, dj in ((1, 0), (0, 1)):
                if i + di < sp.ny and j + dj < sp.nx:
                    b = lab[i + di, j + dj]
                    if b >= 0 and b != a:
                        adj.add(tuple(sorted((zones[a], zones[b]))))
    nodes = []
    for z in zones:
        poly = sp.zones[z]
        nodes.append({"id": z, "kind": "zone", "x": round(float(np.mean([p[0] for p in poly])), 2),
                      "y": round(float(np.mean([p[1] for p in poly])), 2), "area_m2": round(sp.zone_area(z), 1)})
    # 辺の流れ（1 分ごと）: 人のゾーンの列の移り変わり
    minutes = int(math.ceil(total / fps / 60))
    flows = Counter()
    for a in agents:
        prev = None
        for f, x, y, *_ in a.frames:
            z = sp.zone_of(x, y)
            if z is None:
                continue
            if prev is not None and z != prev:
                flows[(int(f / fps // 60), prev, z)] += 1
                adj.add(tuple(sorted((prev, z))))
            prev = z
    edges = [{"source": a, "target": b} for a, b in sorted(adj)]
    secs = list(range(0, total, fps))
    with open(folder / "zone_counts.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t"] + zones)
        for f in secs:
            c = Counter(r[5] for r in per_frame.get(f, []))
            w.writerow([f // fps] + [c.get(z, 0) for z in zones])
    with open(folder / "zone_flows.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["minute", "source", "target", "count"])
        for (m, a, b), n in sorted(flows.items()):
            w.writerow([m, a, b, n])
    # 格子のグラフ: cell_m の正方形のうち、歩ける所が 3 割以上のもの
    x0, x1, y0, y1 = sp.bounds()
    nxc, nyc = int(math.ceil((x1 - x0) / cell_m)), int(math.ceil((y1 - y0) / cell_m))
    k = max(1, int(round(cell_m / sp.res)))
    cells = {}
    for ci in range(nyc):
        for cj in range(nxc):
            blk = sp.grid[ci * k:(ci + 1) * k, cj * k:(cj + 1) * k]
            if blk.size and blk.mean() >= 0.3:
                cells[(ci, cj)] = len(cells)
    gnodes = [{"id": f"c{n}", "kind": "cell", "x": round(x0 + (cj + 0.5) * cell_m, 2), "y": round(y0 + (ci + 0.5) * cell_m, 2)}
              for (ci, cj), n in cells.items()]
    gedges = []
    for (ci, cj), n in cells.items():
        for di, dj in ((1, 0), (0, 1)):
            m = cells.get((ci + di, cj + dj))
            if m is not None:
                gedges.append({"source": f"c{n}", "target": f"c{m}"})
    gcount = np.zeros((len(secs), len(cells)), np.int16)
    for t, f in enumerate(secs):
        for r in per_frame.get(f, []):
            n = cells.get((int((r[2] - y0) // cell_m), int((r[1] - x0) // cell_m)))
            if n is not None:
                gcount[t, n] += 1
    np.savez_compressed(folder / "grid_counts.npz", counts=gcount, t=np.array([f // fps for f in secs]))
    # カメラから見えるノード（ゾーン: 歩ける格子のうち見える割合、格子: 中心が見えるか）
    observed = {}
    for name, c in cams.items():
        cam = Camera(c)
        seen = Counter()
        tot = Counter()
        for i in range(sp.ny):
            for j in range(sp.nx):
                if lab[i, j] >= 0:
                    tot[zones[lab[i, j]]] += 1
                    if cam.sees_floor(sp, *sp.center(i, j)):
                        seen[zones[lab[i, j]]] += 1
        observed[name] = {"zones": {z: round(seen[z] / tot[z], 3) for z in zones if tot[z]},
                          "cells": [gn["id"] for gn in gnodes if cam.sees_floor(sp, gn["x"], gn["y"])]}
    graph = {"zone_graph": {"nodes": nodes, "edges": edges}, "grid_graph": {"cell_m": cell_m, "nodes": gnodes, "edges": gedges},
             "observed": observed,
             "note": "zone_counts.csv（秒ごとのゾーンの人数）、zone_flows.csv（1 分ごとのゾーン間の移動）、grid_counts.npz（counts[秒, 格子]）。"
                     "observed はカメラごとの、見えるゾーンの割合と見える格子（近似）"}
    (folder / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, indent=1))
    try:
        import networkx as nx
        G = nx.Graph()
        for n in nodes:
            G.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
        for e in edges:
            G.add_edge(e["source"], e["target"])
        nx.write_graphml(G, folder / "zone_graph.graphml")
        files.append("graph/zone_graph.graphml")
    except ImportError:
        pass
    return files + ["graph/graph.json", "graph/zone_counts.csv", "graph/zone_flows.csv", "graph/grid_counts.npz"]


def write_mot(sp, cams, per_frame, total, folder, spec):
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    stride = int(spec.get("mot_stride", 1))
    ids = {}
    for name, c in cams.items():
        cam = Camera(c)
        with open(folder / f"{name}.txt", "w") as fh:
            for f in range(0, total, stride):
                rows = per_frame.get(f, [])
                people = [(r[0], r[1], r[2], r[4]) for r in rows]
                boxes = boxes_with_visibility(cam, sp, people)
                for pname, (x0, y0, x1, y1, inside, vis) in boxes.items():
                    if inside < 0.2:
                        continue
                    pid = ids.setdefault(pname, len(ids) + 1)
                    fh.write(f"{f + 1},{pid},{x0:.1f},{y0:.1f},{x1 - x0:.1f},{y1 - y0:.1f},1,1,{vis:.2f}\n")
        files.append(f"mot/{name}.txt")
    (folder / "ids.json").write_text(json.dumps(ids))
    return files + ["mot/ids.json"]


def write_preview(sp, agents, cams, path):
    from PIL import Image, ImageDraw, ImageFont
    lv = sp.spec["levels"][0]
    tv = lv.get("top_view")
    if tv and lv.get("top_image"):
        img = Image.open(sp.folder / lv["top_image"]).convert("RGB")
        top = Camera(camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"]))

        def P(x, y):
            uv, _ = top.project([(x, y, 0.0)])
            return float(uv[0][0]), float(uv[0][1])
    else:  # 真上の画像がなければ、歩ける所の地図を描く
        S = 12
        img = Image.new("RGB", (sp.nx * S, sp.ny * S), (60, 60, 60))
        d0 = ImageDraw.Draw(img)
        for i in range(sp.ny):
            for j in range(sp.nx):
                if sp.grid[i, j]:
                    d0.rectangle([j * S, (sp.ny - 1 - i) * S, j * S + S - 1, (sp.ny - 1 - i) * S + S - 1], fill=(235, 235, 235))

        def P(x, y):
            return (x - sp.x0) / sp.res * S + S / 2, (sp.ny - 1 - (y - sp.y0) / sp.res) * S + S / 2
    img = Image.blend(img, Image.new("RGB", img.size, "white"), 0.35)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 14)
    for z, poly in sp.zones.items():
        pts = [P(*q) for q in poly]
        d.line(pts + [pts[0]], fill=(120, 120, 120), width=1)
        cx, cy = np.mean([q[0] for q in pts]), np.mean([q[1] for q in pts])
        d.text((cx, cy), z, font=font, fill=(90, 90, 90), anchor="mm")
    palette = [(48, 88, 122), (200, 90, 40), (60, 140, 80), (150, 60, 150), (120, 120, 40), (40, 140, 160)]
    streams = sorted({str(a.info.get("stream")) for a in agents})
    for a in agents:
        col = palette[streams.index(str(a.info.get("stream"))) % len(palette)]
        pts = [P(x, y) for _, x, y, *_ in a.frames[::10]]
        if len(pts) > 1:
            d.line(pts, fill=col, width=1)
    for name, c in cams.items():
        cam = Camera(c)
        ex, ey = P(c["eye"][0], c["eye"][1])
        tx, ty = P(c["target"][0], c["target"][1])
        d.ellipse([ex - 5, ey - 5, ex + 5, ey + 5], fill=(220, 30, 30))
        d.line([ex, ey, tx, ty], fill=(220, 30, 30), width=2)
        d.text((ex + 8, ey - 8), name, font=font, fill=(220, 30, 30))
    for k, s in enumerate(streams):
        d.rectangle([10, 10 + 20 * k, 24, 24 + 20 * k], fill=palette[k % len(palette)])
        d.text((30, 10 + 20 * k), s, font=font, fill=(0, 0, 0))
    img.save(path)
