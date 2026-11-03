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

from . import config
from .space import ROOT, load_space

WORK = config.ISAAC_WORK
CONTAINER = "/workspace/twinsim"


def sync():
    for d in ("isaac/vendor", "inbox", "outbox", "done", "running", "jobs", "runs"):
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


def enqueue(script, job, name):
    """job（dict）を jobs/<name>.json に書き、isaac/<script> を JOB つきで実行させるジョブを inbox に置く（待たない）。結果の場所を返す。"""
    sync()
    (WORK / "jobs" / f"{name}.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    out = WORK / "outbox" / f"{name}.txt"
    out.unlink(missing_ok=True)
    # 名前は設定から来るので、json.dumps で文字列として埋める（そのまま埋めると Isaac Sim の中で Python として動いてしまう）
    body = (f'JOB = {json.dumps(f"{CONTAINER}/jobs/{name}.json")}\n'
            f'exec(compile(open({json.dumps(f"{CONTAINER}/isaac/{script}")}, encoding="utf-8").read(), {json.dumps(script)}, "exec"))\n')
    tmp = WORK / "inbox" / f"{name}.py.tmp"
    tmp.write_text(body)
    tmp.rename(WORK / "inbox" / f"{name}.py")
    return out


def submit(script, job, name, wait_s=4 * 3600, poll=5):
    """enqueue して、outbox の結果（文字列）を返す。時間切れなら "timeout"。"""
    out = enqueue(script, job, name)
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        if out.exists():
            fix_perms()
            return out.read_text()
        time.sleep(poll)
    return "timeout"


def workers(max_age_s=30):
    """動いている受け付けの名前（_alive.<名前>.txt が新しいもの。描画の最中は書かれないので、走っているジョブの受け付けも数える）。"""
    alive = set()
    for p in (WORK / "outbox").glob("_alive.*.txt"):
        if time.time() - p.stat().st_mtime < max_age_s:
            alive.add(p.name[len("_alive."):-len(".txt")])
    for p in (WORK / "running").glob("*@*.py"):
        alive.add(p.stem.rsplit("@", 1)[1])
    return sorted(alive)


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
    numbers = [frame_no(p) for p in pngs]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):  # 抜けたまま動画にすると、以降が正解とずれる
        raise RuntimeError(f"描画のコマが抜けている（{frames_dir}: {len(numbers)} 枚、{numbers[0]}〜{numbers[-1]}）")
    # 画像を順に流し込み、入力の時点で一定の間隔にする（concat の duration は丸められ、-r で途中に 1 コマ増えて、以降が正解とずれる）
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(mp4)]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        for p in pngs:
            proc.stdin.write(p.read_bytes())
        proc.stdin.close()
    if proc.returncode:
        raise RuntimeError(f"ffmpeg が失敗（終了コード {proc.returncode}）: {mp4}")
    return len(pngs)


def check_render_args(gt, frames, cameras):
    """描くコマとカメラが、この結果にあるものか。"""
    if not isinstance(cameras, (list, tuple, type(None))):
        raise ValueError("cameras はカメラの名前の配列")
    unknown = [c for c in cameras or [] if c not in gt["cameras"]]
    if unknown:
        raise ValueError(f"カメラ {unknown} がない（あるのは {', '.join(gt['cameras'])}）")
    if frames is not None:
        a, b = frames
        if not (isinstance(a, int) and isinstance(b, int) and 0 <= a <= b < gt["total_frames"]):
            raise ValueError(f"frames は 0 以上 {gt['total_frames']} 未満の [始まり, 終わり]（今は {frames}）")


def chunks(f0, f1, size):
    """[f0, f1] を size コマずつの区間に分ける（最後は短くなる）。"""
    return [(a, min(a + size - 1, f1)) for a in range(f0, f1 + 1, size)]


def plan_render(run_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=None, chunk_s=None):
    """描画のジョブの一覧を作る（まだ投入しない）。chunk_s を渡すと、カメラごと・chunk_s 秒ごとに分けて、いくつもの受け付けで並べて描ける。
    分けないときは、全部のカメラを 1 つのジョブで描く（舞台の読み込みが 1 回で済む）。"""
    run = Path(run_dir).expanduser().resolve()
    gt = json.loads((run / "ground_truth.json").read_text())
    spec = yaml.safe_load((run / "scenario_resolved.yaml").read_text(encoding="utf-8"))
    sp = load_space(spec.get("space", gt["space"]))
    check_render_args(gt, frames, cameras)
    if chunk_s is not None and not chunk_s > 0:
        raise ValueError(f"chunk_s は正の秒数（今は {chunk_s}）")
    if tint is None:
        tint = bool(spec.get("render", {}).get("tint", "per_person"))
    name = run.name
    f0, f1 = frames or (0, gt["total_frames"] - 1)
    props = []
    for pr in spec.get("render", {}).get("props", []):
        p = sp.poi(pr)
        if p.get("prop") == "signage":
            props.append({"kind": "signage", "xy": p["xy"], "face": p["face"]})
    for k, g in gt.get("gates", {}).items():  # ゲートの機械（USD にないので置く）
        if spec.get("render", {}).get("gate_props", True):
            props.append({"kind": "gate", "line": sp.poi(k)["line"], "lanes": len(g["lanes"]), "in_dir": g["in_dir"]})
    base = {"run_dir": f"{CONTAINER}/runs/{name}", "usd": sp.spec["usd"], "props": props, "tint": tint, "preset": preset,
            "z": sp.z, "lights": sp.spec.get("lights", [])}
    cams = list(cameras or gt["cameras"])
    if chunk_s is None:
        parts = [(f"render_{name}", {**base, "frames": [int(f0), int(f1)], "cameras": list(cameras or [])})]
    else:
        size = max(1, round(chunk_s * gt["fps"]))
        parts = [(f"render_{name}__{cam}__{a:06d}", {**base, "frames": [int(a), int(b)], "cameras": [cam],
                                                     "frames_dir": f"{cam}/{a:06d}", "log_name": f"render_log.{cam}.{a:06d}.json"})
                 for cam in cams for a, b in chunks(int(f0), int(f1), size)]
    return {"run": str(run), "name": name, "frames": [int(f0), int(f1)], "cameras": cams, "parts": parts}


def prepare_render(plan):
    """描画の作業場所を用意する（前回の画像と記録は消す）。"""
    run = Path(plan["run"])
    dst = WORK / "runs" / plan["name"]
    dst.mkdir(parents=True, exist_ok=True)
    fix_perms()
    shutil.rmtree(dst / "frames", ignore_errors=True)  # 前回の画像が混ざらないように
    for f in dst.glob("render_log*.json"):
        f.unlink()
    shutil.copy(run / "ground_truth.json", dst / "ground_truth.json")


def start_render(plan):
    """作業場所を用意して、ジョブを全部 inbox に置く。少しずつ置くときは prepare_render のあと enqueue("render.py", job, 名前) を順に。"""
    prepare_render(plan)
    for key, job in plan["parts"]:
        enqueue("render.py", job, key)


def render_state(plan):
    """{"done": 終わったジョブの数, "total": 全部の数, "errors": [失敗したジョブの名前]}"""
    done, errors = 0, []
    for key, _ in plan["parts"]:
        out = WORK / "outbox" / f"{key}.txt"
        if out.exists():
            done += 1
            if "[error]" in out.read_text():
                errors.append(key)
    return {"done": done, "total": len(plan["parts"]), "errors": errors}


def wait_render(plan, wait_s=12 * 3600, poll=5):
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        st = render_state(plan)
        if st["errors"]:
            log = (WORK / "outbox" / f"{st['errors'][0]}.txt").read_text()
            raise RuntimeError(f"描画に失敗した（{len(st['errors'])} 件、最初は {st['errors'][0]}）: {log[-500:]}")
        if st["done"] == st["total"]:
            return
        time.sleep(poll)
    raise RuntimeError(f"描画が時間内に終わらなかった（{render_state(plan)}）")


def finish_plan(plan, keep_frames=True):
    """全部のジョブが終わったあと: カメラごとに mp4 にし（コマの抜けがあれば止まる）、記録をまとめて結果の場所に写す。
    keep_frames=False なら、mp4 にしたあとで作業場所の画像を消す。"""
    run = Path(plan["run"])
    gt = json.loads((run / "ground_truth.json").read_text())
    dst = WORK / "runs" / plan["name"]
    if (dst / "ground_truth.json").read_bytes() != (run / "ground_truth.json").read_bytes():
        raise RuntimeError(f"{dst} の正解が {run} の正解と違う（描き直しが要る）")
    fix_perms()
    logs = []
    for key, _ in plan["parts"]:
        out = WORK / "outbox" / f"{key}.txt"
        logs.append(f"== {key}\n" + (out.read_text() if out.exists() else ""))
    log = "\n".join(logs) if len(plan["parts"]) > 1 else logs[0].split("\n", 1)[1]
    (run / "render_stdout.txt").write_text(log)
    f0, f1 = plan["frames"]
    vids = {}
    (run / "video").mkdir(exist_ok=True)
    for cam in plan["cameras"]:
        vids[cam] = encode(dst / "frames" / cam, run / "video" / f"{cam}.mp4", gt["fps"], (f0, f1))
    parts = [json.loads((dst / (job.get("log_name") or "render_log.json")).read_text())
             for _, job in plan["parts"] if (dst / (job.get("log_name") or "render_log.json")).exists()]
    if len(plan["parts"]) == 1 and parts:
        rl = parts[0]
    else:
        cams = {}
        for p in parts:
            for c, s in p["cameras"].items():
                cams[c] = round(cams.get(c, 0.0) + s, 1)
        rl = {"frames": [f0, f1], "cameras": cams, "people_placed": max((p["people_placed"] for p in parts), default=0),
              "total_s": round(sum(p["total_s"] for p in parts), 1), "parts": len(parts),
              "workers": sorted({p.get("worker", "main") for p in parts})}
    (run / "render_log.json").write_text(json.dumps(rl, ensure_ascii=False))
    if not keep_frames:
        shutil.rmtree(dst / "frames", ignore_errors=True)
    return {"log": log, "videos": vids}


def render(run_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=None, chunk_s=None, keep_frames=True):
    """計算の結果（run_dir）を描画し、run_dir/video/<カメラ>.mp4 を作る。frames=(始まり, 終わり) で範囲を絞る（試し撮り）。
    tint は人ごとに服の色を変えるか。None なら設定の render.tint に従う。
    chunk_s を渡すと、カメラごと・chunk_s 秒ごとに分けて投入する（受け付けがいくつも動いていれば、並べて描く。tools/render_farm.sh）。"""
    plan = plan_render(run_dir, frames, cameras, preset, tint, chunk_s)
    t0 = time.monotonic()
    start_render(plan)
    wait_render(plan)
    r = finish_plan(plan, keep_frames)
    missing = [c for c, n in r["videos"].items() if n is None]
    if missing:
        raise RuntimeError(f"描画の画像がない: {', '.join(missing)}")
    r["seconds"] = round(time.monotonic() - t0, 1)
    return r


def finish_render(run_dir, log=None, frames=None, cameras=None, chunk_s=None):
    """描画のあとの手順だけをやり直す（Isaac Sim の描画が終わったあとに止まったとき）。描画したときと同じ frames・cameras・chunk_s を渡す。"""
    plan = plan_render(run_dir, frames, cameras, chunk_s=chunk_s)
    if log is not None and len(plan["parts"]) == 1:
        (WORK / "outbox" / f"{plan['parts'][0][0]}.txt").write_text(log)
    return finish_plan(plan)


def export_space(name, usd, region, res=0.25):
    """USD から空間の材料を作り、TWINSIM_SPACES か付属の spaces/ の <name>/ に置く（walkable_1f.npz・top_1f.jpg・candidates.json・space.yaml のひな形）。"""
    dst = WORK / "spaces" / name
    dst.mkdir(parents=True, exist_ok=True)
    job = {"usd": usd, "region": list(map(float, region)), "res": res, "out": f"{CONTAINER}/spaces/{name}"}
    log = submit("export_space.py", job, f"export_{name}", wait_s=3600)
    folder = (config.USER_SPACES or ROOT / "spaces") / name
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
