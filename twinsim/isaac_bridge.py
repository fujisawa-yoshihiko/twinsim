"""Isaac Sim（isim のコンテナ）とのやり取り。Isaac Sim は先に起動しておく（README の「描画」）:
  isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
作業場所はホストの ~/isaac-sim-work/twinsim（コンテナの /workspace/twinsim）。isaac/ の部品はジョブのたびに写す。
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from .space import ROOT, load_space

WORK = Path.home() / "isaac-sim-work/twinsim"
CONTAINER = "/workspace/twinsim"


def sync():
    for d in ("isaac/vendor", "inbox", "outbox", "done", "jobs", "runs"):
        (WORK / d).mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "isaac").glob("*.py"):
        shutil.copy(p, WORK / "isaac" / p.name)
    for p in (ROOT / "isaac/vendor").glob("*.py"):
        shutil.copy(p, WORK / "isaac/vendor" / p.name)


def ready(max_age_s=30):
    """twinsim の受け付けが動いているか（受け付けが 5 秒ごとに書く _alive.txt の時刻で見る。描画の最中は書かれないので、走っているジョブがあれば真）。"""
    alive = WORK / "outbox/_alive.txt"
    if alive.exists() and time.time() - alive.stat().st_mtime < max_age_s:
        return True
    return any((WORK / "inbox").glob("*.py")) and alive.exists() and time.time() - alive.stat().st_mtime < 6 * 3600


def submit(script, job, name, wait_s=4 * 3600, poll=5):
    """job（dict）を jobs/<name>.json に書き、isaac/<script> を JOB つきで実行させて、outbox の結果（文字列）を返す。"""
    sync()
    (WORK / "jobs" / f"{name}.json").write_text(json.dumps(job, ensure_ascii=False))
    out = WORK / "outbox" / f"{name}.txt"
    out.unlink(missing_ok=True)
    body = (f'JOB = "{CONTAINER}/jobs/{name}.json"\n'
            f'exec(compile(open("{CONTAINER}/isaac/{script}", encoding="utf-8").read(), "{script}", "exec"))\n')
    tmp = WORK / "inbox" / f"{name}.py.tmp"
    tmp.write_text(body)
    tmp.rename(WORK / "inbox" / f"{name}.py")
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        if out.exists():
            fix_perms()
            return out.read_text()
        time.sleep(poll)
    return "timeout"


def fix_perms():
    subprocess.run(["isim", "fix-perms"], capture_output=True)


def frame_no(p):
    try:
        return int(p.stem.split(".")[-1])
    except ValueError:
        return -1


def encode(frames_dir, mp4, fps, frames=None):
    """連番の画像（f.<コマ>.png）を mp4 に。frames=(始まり, 終わり) ならその範囲だけ。"""
    pngs = sorted(Path(frames_dir).rglob("*.png"), key=frame_no)
    if frames:
        pngs = [p for p in pngs if frames[0] <= frame_no(p) <= frames[1]]
    if not pngs:
        return None
    lst = Path(mp4).with_suffix(".txt")
    lst.write_text("".join(f"file '{p}'\nduration {1 / fps:.6f}\n" for p in pngs))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-r", str(fps),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(mp4)], check=True)
    lst.unlink()
    return len(pngs)


def render(run_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=True):
    """計算の結果（run_dir）を描画し、run_dir/video/<カメラ>.mp4 を作る。frames=(始まり, 終わり) で範囲を絞る（試し撮り）。"""
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    spec = yaml.safe_load((run / "scenario_resolved.yaml").read_text(encoding="utf-8"))
    sp = load_space(gt["space"])
    name = run.name
    dst = WORK / "runs" / name
    dst.mkdir(parents=True, exist_ok=True)
    fix_perms()
    shutil.rmtree(dst / "frames", ignore_errors=True)  # 前回の画像が混ざらないように
    shutil.copy(run / "ground_truth.json", dst / "ground_truth.json")
    f0, f1 = frames or (0, gt["total_frames"] - 1)
    props = []
    for pr in spec.get("render", {}).get("props", []):
        p = sp.poi(pr)
        if p.get("prop") == "signage":
            props.append({"kind": "signage", "xy": p["xy"], "face": p["face"]})
    for k, g in gt.get("gates", {}).items():  # ゲートの機械（USD にないので置く）
        if spec.get("render", {}).get("gate_props", True):
            props.append({"kind": "gate", "line": sp.poi(k)["line"], "lanes": len(g["lanes"]), "in_dir": g["in_dir"]})
    job = {"run_dir": f"{CONTAINER}/runs/{name}", "usd": sp.spec["usd"], "frames": [int(f0), int(f1)],
           "cameras": cameras or [], "props": props, "tint": tint, "preset": preset, "z": sp.z, "lights": sp.spec.get("lights", [])}
    t0 = time.monotonic()
    log = submit("render.py", job, f"render_{name}")
    r = finish_render(run, log, (f0, f1), cameras)
    r["seconds"] = round(time.monotonic() - t0, 1)
    return r


def finish_render(run_dir, log=None, frames=None, cameras=None):
    """描画のあとの手順: コマを mp4 にし、描画の記録を写す。Isaac Sim の描画が終わったあとに止まったときは、これだけやり直せる
    （描画に使った正解が今の正解と同じことを確かめる）。"""
    run = Path(run_dir).expanduser()
    gt = json.loads((run / "ground_truth.json").read_text())
    dst = WORK / "runs" / run.name
    if (dst / "ground_truth.json").read_bytes() != (run / "ground_truth.json").read_bytes():
        raise RuntimeError(f"{dst} の正解が {run} の正解と違う（描き直しが要る）")
    fix_perms()
    if log is None:
        out = WORK / "outbox" / f"render_{run.name}.txt"
        log = out.read_text() if out.exists() else ""
    (run / "render_stdout.txt").write_text(log)
    rl = json.loads((dst / "render_log.json").read_text()) if (dst / "render_log.json").exists() else {}
    f0, f1 = frames or rl.get("frames") or (0, gt["total_frames"] - 1)
    vids = {}
    (run / "video").mkdir(exist_ok=True)
    for cam in (cameras or list(gt["cameras"])):
        vids[cam] = encode(dst / "frames" / cam, run / "video" / f"{cam}.mp4", gt["fps"], (f0, f1))
    if (dst / "render_log.json").exists():
        shutil.copy(dst / "render_log.json", run / "render_log.json")
    return {"log": log, "videos": vids}


def export_space(name, usd, region, res=0.25):
    """USD から空間の材料を作り、spaces/<name>/ に置く（walkable_1f.npz・top_1f.jpg・candidates.json・space.yaml のひな形）。"""
    dst = WORK / "spaces" / name
    dst.mkdir(parents=True, exist_ok=True)
    job = {"usd": usd, "region": list(map(float, region)), "res": res, "out": f"{CONTAINER}/spaces/{name}"}
    log = submit("export_space.py", job, f"export_{name}", wait_s=3600)
    folder = ROOT / "spaces" / name
    folder.mkdir(parents=True, exist_ok=True)
    if (dst / "walkable.npz").exists():
        shutil.copy(dst / "walkable.npz", folder / "walkable_1f.npz")
    if (dst / "top.png").exists():
        from PIL import Image
        Image.open(dst / "top.png").convert("RGB").save(folder / "top_1f.jpg", quality=88)
    for f in ("candidates.json", "info.json", "top_view.json"):
        if (dst / f).exists():
            shutil.copy(dst / f, folder / f)
    if not (folder / "space.yaml").exists() and (dst / "top_view.json").exists():
        tv = json.loads((dst / "top_view.json").read_text())
        skel = {"name": name, "title": name, "usd": usd, "license": "（確かめて書く）", "navmesh_region": list(map(float, region)),
                "levels": [{"name": "1F", "z": float(region[4]), "walkable": "walkable_1f.npz", "top_image": "top_1f.jpg", "top_view": tv}],
                "pois": {}, "zones": {}, "cameras": {}}
        (folder / "space.yaml").write_text("# export-space が作ったひな形。candidates.json と top_1f.jpg を見て、pois・zones・cameras を書く\n"
                                           + yaml.safe_dump(skel, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"log": log, "folder": str(folder)}
