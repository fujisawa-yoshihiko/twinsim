"""twinsim 用（元: ~/digitaltwin/hospital-sim/agent_runner.py。作業場所だけ /workspace/twinsim に替えた）。
検証用: 作業フォルダの inbox/ に置かれた Python スクリプトを Isaac Sim の中で順に実行し、結果を outbox/ に書く。

isim up --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py" で読み込む（twinsim の README の手順）。
ネットワークのポートは開けない（このフォルダに書ける人＝本人と Isaac Sim のコンテナだけが使える）。
スクリプトは log(...) で結果を書き、async def main() があれば待って実行する。
"""

import asyncio
import time
import traceback
from pathlib import Path

import omni.kit.app

ROOT = Path("/workspace/twinsim")
INBOX, OUTBOX, DONE = ROOT / "inbox", ROOT / "outbox", ROOT / "done"
SHARED = {}  # スクリプトの間で受け渡す値（ナビメッシュの経路など）


async def run_one(path: Path):
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
    lines.append(f"[{status}] {time.monotonic() - t0:.1f} s")
    (OUTBOX / f"{path.stem}.txt").write_text("\n".join(lines) + "\n")
    path.replace(DONE / path.name)


async def loop():
    app = omni.kit.app.get_app()
    for d in (INBOX, OUTBOX, DONE):
        d.mkdir(parents=True, exist_ok=True)
    (OUTBOX / "_ready.txt").write_text("ready\n")
    while True:
        for p in sorted(INBOX.glob("*.py")):
            await run_one(p)
        for _ in range(15):  # 15 フレームごとに見る
            await app.next_update_async()


asyncio.ensure_future(loop())
