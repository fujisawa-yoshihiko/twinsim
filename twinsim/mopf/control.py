"""MOPF の起動・停止・状態（~/MOPF_ALL_video の start_ampb.sh・stop_ampb.sh）と、ライブの集計の中継。GUI の「MOPF」のタブから使う。

GPU は他の利用者と共有。起動の前に gpus() で空きを見せ、選んだ GPU が他のジョブで使われていれば start_ampb.sh が止める（2,000 MiB 以上）。
このマシンの決まり（同時に使う GPU は 2 枚まで）は、own_gpus() で twinsim・MOPF が使っている GPU を数えて確かめる。
"""

import json
import subprocess
import time
import urllib.error
import urllib.request

from .. import config
from .process import mopf_ready

MAX_OWN_GPUS = 2  # このマシンで同時に使ってよい GPU（CLAUDE.md の決まり）


def gpus():
    """[{index, memory_used_mib, memory_total_mib, util}]（nvidia-smi がなければ空）"""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in out.strip().splitlines():
        i, used, total, util = (x.strip() for x in line.split(","))
        rows.append({"index": int(i), "memory_used_mib": int(used), "memory_total_mib": int(total), "util": int(util)})
    return rows


def _docker_gpu(name_filter):
    """名前に name_filter を含む動いているコンテナの GPU の番号（docker inspect の DeviceRequests）。"""
    try:
        names = subprocess.run(["docker", "ps", "--filter", f"name={name_filter}", "--format", "{{.Names}}"],
                               capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return set()
    out = set()
    for n in names:
        try:
            info = json.loads(subprocess.run(["docker", "inspect", n], capture_output=True, text=True, timeout=10).stdout)[0]
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError):
            continue
        for r in (info.get("HostConfig", {}).get("DeviceRequests") or []):
            out |= {int(x) for x in (r.get("DeviceIDs") or []) if str(x).isdigit()}
        env = dict(e.split("=", 1) for e in info.get("Config", {}).get("Env", []) if "=" in e)
        if env.get("NVIDIA_VISIBLE_DEVICES", "").isdigit():
            out.add(int(env["NVIDIA_VISIBLE_DEVICES"]))
    return out


def own_gpus():
    """twinsim・MOPF が使っている GPU: {"mopf": {...}, "isaac": {...}}"""
    return {"mopf": _docker_gpu("cv-app") | _docker_gpu("mopf"), "isaac": _docker_gpu("isaac")}


def _get(path, timeout=5):
    return json.loads(urllib.request.urlopen(f"{config.MOPF_URL}{path}", timeout=timeout).read())


def status():
    st = {"ready": mopf_ready(), "app_url": config.MOPF_APP_URL, "monitor_url": f"{config.MOPF_APP_URL}/monitor", "live": None}
    if st["ready"]:
        try:
            s = _get("/api/live/summary")
            st["live"] = {"status": s.get("status"), "fps": s.get("fps"), "count_now": s.get("count_now")}
        except (urllib.error.URLError, OSError, ValueError):
            pass
    own = own_gpus()
    st["gpus"] = gpus()
    st["own_gpus"] = {k: sorted(v) for k, v in own.items()}
    return st


def start(gpu, live_video=None, log=None):
    """start_ampb.sh --gpu N --no-llm --no-vc3 [--live-demo 動画]。動けば True。log は 1 行ずつ受け取る関数。
    ライブにするとカメラの入力として動画を繰り返し流す（cv-app を作り直す）。動画の処理（process）はカメラなしのときに行う。"""
    own = own_gpus()
    used = (own["mopf"] | own["isaac"]) - set(own["mopf"])  # MOPF を起動し直すときは、MOPF の今の GPU は数えない
    if gpu not in used and len(used | {gpu}) > MAX_OWN_GPUS:
        raise RuntimeError(f"同時に使う GPU は {MAX_OWN_GPUS} 枚まで（今 {sorted(used)} を使用中）")
    cmd = ["./start_ampb.sh", "--gpu", str(int(gpu)), "--no-llm", "--no-vc3"]
    if live_video:
        cmd += ["--live-demo", str(live_video)]
    stop(log)
    p = subprocess.Popen(cmd, cwd=config.MOPF_HOME, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        if log:
            log(line.rstrip())
    if p.wait() != 0:
        raise RuntimeError(f"start_ampb.sh が失敗（終了コード {p.returncode}）")
    for _ in range(100):
        if mopf_ready():
            return True
        time.sleep(3)
    raise RuntimeError("MOPF の API（8010）が 5 分たっても応えない")


def stop(log=None):
    p = subprocess.run(["./stop_ampb.sh"], cwd=config.MOPF_HOME, capture_output=True, text=True)
    if log:
        for line in (p.stdout + p.stderr).splitlines():
            log(line)
    return p.returncode == 0


def live_summary():
    return _get("/api/live/summary")


def live_reset():
    req = urllib.request.Request(f"{config.MOPF_URL}/api/live/reset", data=b"", method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read() or b"{}")


def live_stream():
    """MJPEG（multipart/x-mixed-replace）の応答をそのまま開く（GUI のサーバーが中継する）。"""
    return urllib.request.urlopen(f"{config.MOPF_URL}/api/live/stream", timeout=10)
