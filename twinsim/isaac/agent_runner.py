"""twinsim 用（元: ~/digitaltwin/hospital-sim/agent_runner.py。作業場所だけ /workspace/twinsim に替えた）。
検証用: 作業フォルダの inbox/ に置かれた Python スクリプトを Isaac Sim の中で順に実行し、結果を outbox/ に書く。

isim up --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py" で読み込む（twinsim の README の手順）。
ネットワークのポートは開けない（このフォルダに書ける人＝本人と Isaac Sim のコンテナだけが使える）。
スクリプトは log(...) で結果を書き、async def main() があれば待って実行する。

いくつ起動してもよい（tools/render_farm.sh が GPU ごとに起動する）。受け付けは環境変数 TWINSIM_WORKER の名前（既定 main）で区別し、
inbox のジョブは名前の付け替えで 1 つずつ取る（付け替えは 1 つしか成功しないので、同じジョブを 2 つが動かすことはない）。
取ったジョブは running/<名前>@<受け付け>.py に置き、終わったら done/ へ。途中で止まった受け付けを同じ名前で起動し直すと、自分の分を inbox に戻す。
"""

import asyncio
import os
import time
import traceback
from pathlib import Path

import omni.kit.app

ROOT = Path("/workspace/twinsim")
INBOX, OUTBOX, DONE, RUNNING = ROOT / "inbox", ROOT / "outbox", ROOT / "done", ROOT / "running"
WORKER = os.environ.get("TWINSIM_WORKER", "main")
SHARED = {}  # スクリプトの間で受け渡す値（ナビメッシュの経路など）


def claim(path: Path):
    """inbox のジョブを自分のものにする。ほかの受け付けが先に取っていたら None。"""
    mine = RUNNING / f"{path.stem}@{WORKER}.py"
    try:
        path.rename(mine)
    except FileNotFoundError:
        return None
    return mine


def requeue_own():
    """前に動いていた自分（同じ名前）が途中で止まったときのジョブを、inbox に戻す。"""
    for p in RUNNING.glob(f"*@{WORKER}.py"):
        p.rename(INBOX / f"{p.stem.rsplit('@', 1)[0]}.py")


async def run_one(path: Path, stem: str):
    lines = []

    def log(*args):
        lines.append(" ".join(str(a) for a in args))

    t0 = time.monotonic()
    g = {"__name__": "__agent__", "log": log, "SHARED": SHARED, "asyncio": asyncio}
    try:
        exec(compile(path.read_text(), str(path), "exec"), g)
        main = g.get("main")
        if main is not None and asyncio.iscoroutinefunction(main):
            await main()
        status = "ok"
    except Exception:
        lines.append(traceback.format_exc())
        status = "error"
    lines.append(f"[{status}] {time.monotonic() - t0:.1f} s（受け付け {WORKER}）")
    (OUTBOX / f"{stem}.txt").write_text("\n".join(lines) + "\n")
    path.replace(DONE / f"{stem}.py")


async def loop():
    app = omni.kit.app.get_app()
    for d in (INBOX, OUTBOX, DONE, RUNNING):
        d.mkdir(parents=True, exist_ok=True)
    requeue_own()
    (OUTBOX / "_ready.txt").write_text("ready\n")
    last = 0.0
    while True:
        if time.monotonic() - last > 5:  # 生きている印（twinsim の isaac_bridge.ready() が時刻を見る）
            (OUTBOX / "_alive.txt").write_text(f"{time.time():.0f}\n")
            (OUTBOX / f"_alive.{WORKER}.txt").write_text(f"{time.time():.0f}\n")
            last = time.monotonic()
        for p in sorted(INBOX.glob("*.py")):
            mine = claim(p)
            if mine is not None:
                await run_one(mine, p.stem)
                break  # 1 つ終えたら、生きている印を書いてから inbox を見直す
        for _ in range(15):  # 15 フレームごとに見る
            await app.next_update_async()


asyncio.ensure_future(loop())
