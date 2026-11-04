"""描画を分けて並べるための仕組みの確かめ（CPU だけ。Isaac Sim の代わりに、画像を書く偽の受け付けを使う）。"""

import json
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import twinsim
from twinsim import isaac_bridge

CONFIG = {"space": "office", "duration_s": 12, "fps": 10, "seed": 3,
          "streams": [{"origin": "entrance", "rate": 30, "destinations": ["south_exit"]}],
          "cameras": [{"name": "CamGate"}, {"name": "CamEV"}]}
RUNNER = Path(isaac_bridge.__file__).parent / "isaac" / "agent_runner.py"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(isaac_bridge, "WORK", tmp_path / "work")
    monkeypatch.setattr(isaac_bridge, "fix_perms", lambda: None)
    isaac_bridge.sync()
    return tmp_path / "work"


def fake_worker(work, name="fake", fail=()):
    """inbox のジョブを全部片付ける偽の受け付け: 描く範囲のコマを 1 枚ずつ PNG にし、記録と結果を書く。"""
    for p in sorted((work / "inbox").glob("*.py")):
        job = json.loads((work / "jobs" / f"{p.stem}.json").read_text())
        run = work / "runs" / Path(job["run_dir"]).name
        f0, f1 = job["frames"]
        for cam in job["cameras"]:
            folder = run / "frames" / (job.get("frames_dir") or cam) / "f_frames"
            folder.mkdir(parents=True, exist_ok=True)
            for f in range(f0, f1 + 1):
                Image.fromarray(np.full((36, 64, 3), f % 256, np.uint8)).save(folder / f"f.{f}.png")
        log = {"frames": [f0, f1], "cameras": {c: 1.5 for c in job["cameras"]}, "people_placed": 4, "total_s": 2.0, "worker": name}
        (run / (job.get("log_name") or "render_log.json")).write_text(json.dumps(log))
        status = "error" if p.stem in fail else "ok"
        (work / "outbox" / f"{p.stem}.txt").write_text(f"[{status}] 2.0 s\n")
        p.replace(work / "done" / p.name)


def frame_count(mp4):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                          "-of", "csv=p=0", str(mp4)], capture_output=True, text=True, check=True).stdout
    return int(out.strip())


def test_work_names_differ_for_same_named_results(tmp_path):
    a = twinsim.simulate(CONFIG, out_dir=tmp_path / "v0" / "r")
    b = twinsim.simulate(CONFIG, out_dir=tmp_path / "v1" / "r")  # 同じ名前の結果でも、場所が違えば作業場所とジョブの名前は別
    pa, pb = isaac_bridge.plan_render(a.out_dir, chunk_s=5), isaac_bridge.plan_render(b.out_dir, chunk_s=5)
    assert pa["name"] != pb["name"] and not {k for k, _ in pa["parts"]} & {k for k, _ in pb["parts"]}


def test_chunks_cover_the_range_once():
    assert isaac_bridge.chunks(0, 9, 4) == [(0, 3), (4, 7), (8, 9)]
    assert isaac_bridge.chunks(5, 5, 30) == [(5, 5)]


def test_plan_splits_by_camera_and_time(tmp_path):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    whole = isaac_bridge.plan_render(r.out_dir)
    assert len(whole["parts"]) == 1 and whole["parts"][0][1]["cameras"] == []  # 分けないときは今までどおり 1 つ
    plan = isaac_bridge.plan_render(r.out_dir, chunk_s=5)
    assert len(plan["parts"]) == 2 * 3  # カメラ 2 台 × 120 コマを 50 コマずつ
    keys = [k for k, _ in plan["parts"]]
    assert len(set(keys)) == len(keys)
    for cam in ("CamGate", "CamEV"):
        ranges = [j["frames"] for _, j in plan["parts"] if j["cameras"] == [cam]]
        assert ranges == [[0, 49], [50, 99], [100, 119]]
    assert len({j["frames_dir"] for _, j in plan["parts"]}) == len(plan["parts"])
    assert len({j["log_name"] for _, j in plan["parts"]}) == len(plan["parts"])
    with pytest.raises(ValueError, match="chunk_s"):
        isaac_bridge.plan_render(r.out_dir, chunk_s=0)


def test_split_render_joins_into_one_video_per_camera(tmp_path, work):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, frames=(10, 109), chunk_s=3)
    isaac_bridge.start_render(plan)
    assert isaac_bridge.render_state(plan) == {"done": 0, "total": len(plan["parts"]), "errors": []}
    fake_worker(work)
    assert isaac_bridge.render_state(plan)["done"] == len(plan["parts"])
    out = isaac_bridge.finish_plan(plan, keep_frames=False)
    assert out["videos"] == {"CamGate": 100, "CamEV": 100}
    for cam in ("CamGate", "CamEV"):
        assert frame_count(r.out_dir / "video" / f"{cam}.mp4") == 100
    rl = json.loads((r.out_dir / "render_log.json").read_text())
    assert rl["parts"] == len(plan["parts"]) and rl["frames"] == [10, 109] and rl["workers"] == ["fake"]
    assert rl["cameras"] == {"CamGate": 1.5 * 4, "CamEV": 1.5 * 4}
    assert not (work / "runs" / r.out_dir.name / "frames").exists()  # 画像は mp4 にしたら消す
    assert twinsim.open_result(r.out_dir).video_first_frame == 10
    # 偽の画像はコマの番号の明るさ。つないだ動画の k コマ目が、シミュレータの 10 + k コマ目になっている（区間の境目でずれない）
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(r.out_dir / "video" / "CamEV.mp4"), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    shade = np.frombuffer(raw, np.uint8).reshape(-1, 36, 64).mean(axis=(1, 2))
    assert np.abs(shade - np.arange(10, 110)).max() < 3


def test_split_render_stops_on_a_missing_chunk(tmp_path, work):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, cameras=["CamGate"], chunk_s=4)
    isaac_bridge.start_render(plan)
    middle = plan["parts"][1][0]
    (work / "inbox" / f"{middle}.py").unlink()  # 真ん中の区間が描かれなかった
    fake_worker(work)
    with pytest.raises(RuntimeError, match="抜けている"):
        isaac_bridge.finish_plan(plan)


def test_failed_chunk_is_reported(tmp_path, work):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    plan = isaac_bridge.plan_render(r.out_dir, cameras=["CamEV"], chunk_s=4)
    isaac_bridge.start_render(plan)
    fake_worker(work, fail={plan["parts"][2][0]})
    assert isaac_bridge.render_state(plan)["errors"] == [plan["parts"][2][0]]
    with pytest.raises(RuntimeError, match="描画に失敗"):
        isaac_bridge.wait_render(plan, wait_s=1, poll=0)


def test_start_clears_the_previous_frames(tmp_path, work):
    r = twinsim.simulate(CONFIG, out_dir=tmp_path / "r")
    old = work / "runs" / isaac_bridge.work_name(r.out_dir) / "frames" / "CamGate" / "old" / "f.999.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    isaac_bridge.start_render(isaac_bridge.plan_render(r.out_dir, chunk_s=5))
    assert not old.exists()


def load_runner(root, worker, monkeypatch):
    """agent_runner.py を Isaac Sim の外で読む（omni を偽物にし、最後の起動の行は動かさない）。"""
    fake = types.ModuleType("omni")
    fake.kit = types.ModuleType("omni.kit")
    fake.kit.app = types.ModuleType("omni.kit.app")
    for name, m in (("omni", fake), ("omni.kit", fake.kit), ("omni.kit.app", fake.kit.app)):
        monkeypatch.setitem(sys.modules, name, m)
    monkeypatch.setenv("TWINSIM_WORKER", worker)
    src = RUNNER.read_text(encoding="utf-8").replace("asyncio.ensure_future(loop())", "")
    g = {"__name__": "runner"}
    exec(compile(src, str(RUNNER), "exec"), g)
    g["INBOX"], g["RUNNING"] = root / "inbox", root / "running"
    for d in ("inbox", "running"):
        (root / d).mkdir(exist_ok=True)
    return g


def test_two_runners_never_take_the_same_job(tmp_path, monkeypatch):
    a = load_runner(tmp_path, "g3-1", monkeypatch)
    b = load_runner(tmp_path, "g3-2", monkeypatch)
    assert (a["WORKER"], b["WORKER"]) == ("g3-1", "g3-2")
    job = tmp_path / "inbox" / "render_x__CamGate__000000.py"
    job.write_text("pass\n")
    got_a = a["claim"](job)
    assert got_a == tmp_path / "running" / "render_x__CamGate__000000@g3-1.py" and got_a.exists()
    assert b["claim"](job) is None  # 先に取られていた
    b["requeue_own"]()
    assert got_a.exists()  # ほかの受け付けの分は戻さない
    a["requeue_own"]()  # 止まった受け付けを同じ名前で起動し直したとき
    assert job.exists() and not got_a.exists()


def test_workers_are_listed_by_alive_marks(work):
    (work / "outbox" / "_alive.g3-1.txt").write_text("0\n")
    (work / "running" ).mkdir(exist_ok=True)
    (work / "running" / "render_y@g2-1.py").write_text("")
    assert isaac_bridge.workers() == ["g2-1", "g3-1"]


def test_unstick_restarts_hung_worker_then_gives_up(work, monkeypatch):
    """[Fatal] が出て固まった受け付けは起動し直す（ジョブは受け付けが inbox に戻す）。同じジョブで 2 回目なら [error] にして、やり直さない。"""
    calls = []

    def docker(*args):
        calls.append(args)
        if args[0] == "logs":
            return subprocess.CompletedProcess(args, 0, "[Fatal] [omni.rtx] Out of resource descriptors!\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(isaac_bridge, "_docker", docker)
    run = work / "running" / "render_x__h22p15__001800@g0-3.py"
    run.write_text("")
    assert isaac_bridge.unstick(every_s=0, log=lambda *_: None) == ["g0-3"]
    assert ("restart", "-t", "20", "twinsim-render-g0-3") in calls
    assert run.exists() and not (work / "outbox" / "render_x__h22p15__001800.txt").exists()
    assert isaac_bridge.unstick(every_s=0, log=lambda *_: None) == ["g0-3"]
    assert not run.exists() and (work / "done" / "render_x__h22p15__001800.py").exists()
    assert "[error]" in (work / "outbox" / "render_x__h22p15__001800.txt").read_text()


def test_unstick_by_age_and_skips_non_farm(work, monkeypatch):
    def docker(*args):
        if args[0] == "logs" and args[-1].endswith("main"):
            return subprocess.CompletedProcess(args, 1, "", "No such container")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(isaac_bridge, "_docker", docker)
    (work / "running" / "a@g1-2.py").write_text("")
    (work / "running" / "b@main.py").write_text("")
    assert isaac_bridge.stuck_jobs(max_s=3600) == []
    t = time.time()
    monkeypatch.setattr(isaac_bridge.time, "time", lambda: t + 7200)
    assert [(n, w) for n, w, _ in isaac_bridge.stuck_jobs(max_s=3600)] == [("a", "g1-2")]


def test_sync_replaces_files_whole(work):
    """写しは中身が変わったときだけ、名前の付け替えで入れ替える（書きかけの部品を受け付けが読まない）。"""
    dst = work / "isaac" / "render.py"
    ino = dst.stat().st_ino
    isaac_bridge.sync()
    assert dst.stat().st_ino == ino  # 変わっていなければ書かない
    dst.write_text("# old\n")
    isaac_bridge.sync()
    assert dst.stat().st_ino != ino and dst.read_text() != "# old\n"
    assert not list((work / "isaac").glob(".*.tmp"))
