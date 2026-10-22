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


def ready():
    return (WORK / "outbox/_ready.txt").exists()


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


def encode(frames_dir, mp4, fps):
    pngs = sorted(Path(frames_dir).rglob("*.png"))
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
    shutil.copy(run / "ground_truth.json", dst / "ground_truth.json")
    f0, f1 = frames or (0, gt["total_frames"] - 1)
    props = []
    for pr in spec.get("render", {}).get("props", []):
        p = sp.poi(pr)
        if p.get("prop") == "signage":
            props.append({"kind": "signage", "xy": p["xy"], "face": p["face"]})
    job = {"run_dir": f"{CONTAINER}/runs/{name}", "usd": sp.spec["usd"], "frames": [int(f0), int(f1)],
           "cameras": cameras or [], "props": props, "tint": tint, "preset": preset}
    t0 = time.monotonic()
    log = submit("render.py", job, f"render_{name}")
    (run / "render_stdout.txt").write_text(log)
    vids = {}
    (run / "video").mkdir(exist_ok=True)
    for cam in (cameras or list(gt["cameras"])):
        n = encode(dst / "frames" / cam, run / "video" / f"{cam}.mp4", gt["fps"])
        vids[cam] = n
    if (dst / "render_log.json").exists():
        shutil.copy(dst / "render_log.json", run / "render_log.json")
    return {"log": log, "videos": vids, "seconds": round(time.monotonic() - t0, 1)}


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
