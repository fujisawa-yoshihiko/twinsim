"""描いた動画を MOPF で検出・追跡する（MOPF が動いているときだけ。GPU を使う）。"""

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config
from .io import open_run


def _get(url, timeout=10):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def mopf_ready(base=None):
    base = base or config.MOPF_URL
    try:
        urllib.request.urlopen(f"{base}/api/video/list", timeout=3).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def process(run_dir, cameras=None, model="yolo11m", base=None, poll=5, wait_s=3600):
    base = base or config.MOPF_URL
    run, gt, f0 = open_run(run_dir)
    if not mopf_ready(base):
        raise RuntimeError("MOPF が動いていない（cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --no-llm --no-vc3。GPU は確認を取ってから）")
    vids = sorted((run / "video").glob("*.mp4"))
    if cameras:
        vids = [v for v in vids if v.stem in cameras]
    if not vids:
        raise ValueError(f"{run}/video に動画がない（先に render）")
    (run / "mopf_tracks").mkdir(exist_ok=True)
    done = {}
    for v in vids:
        name = f"twinsim-{run.name}-{v.stem}.mp4"
        shutil.copy(v, config.MOPF_CV / "uploads" / name)
        req = urllib.request.Request(f"{base}/api/video/process/{name}?model_name={model}", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=30).read()
        t0 = time.time()
        while True:
            st = _get(f"{base}/api/video/status/{name}")
            if st.get("status") not in ("queued", "processing"):
                break
            if time.time() - t0 > wait_s:
                raise TimeoutError(f"{name}: {wait_s} 秒たっても終わらない")
            time.sleep(poll)
        src = config.MOPF_CV / "outputs/uploads" / Path(name).stem / "tracking.jsonl"
        if not src.exists():
            raise RuntimeError(f"{name}: 結果がない（状態 {st}）")
        shutil.copy(src, run / "mopf_tracks" / f"{v.stem}.jsonl")
        done[v.stem] = {"status": st.get("status"), "model": model, "seconds": round(time.time() - t0, 1), "mopf_name": name}
    (run / "mopf_tracks" / "info.json").write_text(json.dumps({"frame_offset": f0, "videos": done}, ensure_ascii=False, indent=1))
    return done
