"""GUI のサーバーの守り（トークン・パスの脱出・CSRF・XSS の防ぎ・ファイルの名前）を、実際の HTTP で確かめる（CPU だけ）。"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import twinsim
from twinsim import isaac_bridge, server

TOKEN = "test-token"
CONFIG = {"space": "office", "duration_s": 10, "streams": [{"origin": "entrance", "rate": 10, "destinations": ["south_exit"]}]}


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(server.App(), TOKEN))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(url, body=None, headers=None, auth=True, method=None):
    h = dict(headers or {})
    if auth:
        h.setdefault("Authorization", f"Bearer {TOKEN}")
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=20)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_token_is_required(base):
    assert call(f"{base}/api/health", auth=False)[0] == 200
    for path in ("/", "/api/runs", "/api/templates", "/app.js"):
        assert call(base + path, auth=False)[0] == 401
    assert call(f"{base}/api/runs", headers={"Authorization": "Bearer wrong"})[0] == 401
    assert call(f"{base}/?token=%E3%81%82", auth=False)[0] == 401  # 日本語のトークンでも落ちない
    assert call(f"{base}/api/runs", auth=False, headers={"Cookie": f'other={{"a":1}}; {server.COOKIE}={TOKEN}'})[0] == 200


def test_csp_on_every_response(base):
    status, headers, _ = call(f"{base}/")
    assert status == 200 and "script-src 'self'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", ["/api/spaces/..%2F..%2F..", "/api/spaces/%2Fetc", "/api/templates/..%2F..%2Fpyproject", "/api/templates/pyproject.toml",
                                  "/api/runs/..%2F..", "/api/runs/..%2F../file?path=x", "/api/runs/x/file?path=../../pyproject.toml"])
def test_paths_cannot_escape(base, path):
    assert call(base + path)[0] in (400, 404)


def test_scenario_must_be_a_template_or_a_config(base):
    assert call(f"{base}/api/runs", {"scenario": "/etc/hostname"})[0] == 404


def test_post_from_another_page_is_refused(base):
    cookie = {"Cookie": f"{server.COOKIE}={TOKEN}"}
    assert call(f"{base}/api/validate", {"scenario": CONFIG}, cookie, auth=False)[0] == 200
    evil = {**cookie, "Origin": "http://localhost:9999"}
    assert call(f"{base}/api/validate", {"scenario": CONFIG}, evil, auth=False)[0] == 403
    assert call(f"{base}/api/validate", {"scenario": CONFIG}, {**cookie, "Content-Type": "text/plain"}, auth=False)[0] == 403


def test_run_ids_do_not_collide_and_japanese_names_open(base):
    ids = [json.loads(call(f"{base}/api/runs", {"scenario": {**CONFIG, "name": "テスト計算"}})[2])["id"] for _ in range(2)]
    assert ids[0] != ids[1]
    url = f"{base}/api/runs/" + urllib.parse.quote(ids[0])
    for _ in range(300):
        info = json.loads(call(url)[2])
        if info["job"].get("status") != "running":
            break
        threading.Event().wait(0.1)
    assert info["summary"]["people"] >= 0
    assert call(f"{base}/api/runs/none")[0] == 404


def test_unsafe_names_are_errors_before_simulating(tmp_path):
    for name in ("../../outside", "a/b", "<img src=x>", 'x"\nprint(1)\n#'):
        with pytest.raises(ValueError, match="name に使える"):
            twinsim.validate({**CONFIG, "name": name})
        with pytest.raises(ValueError, match="名前に使える"):
            twinsim.validate({**CONFIG, "cameras": [{"name": name, "eye": [0, 0, 3], "target": [1, 1, 1]}]})
    assert twinsim.validate({**CONFIG, "name": "テスト-1_a"})["name"] == "テスト-1_a"


def test_isaac_job_names_stay_strings(tmp_path, monkeypatch):
    monkeypatch.setattr(isaac_bridge, "WORK", tmp_path)
    monkeypatch.setattr(isaac_bridge, "sync", lambda: None)
    for d in ("jobs", "outbox", "inbox"):
        (tmp_path / d).mkdir()
    name = 'x"\nraise SystemExit("injected")\n#'
    assert isaac_bridge.submit("render.py", {}, name, wait_s=0) == "timeout"
    body = (tmp_path / "inbox" / f"{name}.py").read_text()
    ns = {}
    exec(body.split("exec(compile")[0], ns)  # 1 行目は JOB への代入だけで、中の文字は実行されない
    assert ns["JOB"].endswith(f"{name}.json") and len(body.splitlines()) == 2


def test_render_arguments_are_checked():
    gt = {"cameras": {"CamGate": {}}, "total_frames": 100}
    isaac_bridge.check_render_args(gt, (0, 99), ["CamGate"])
    for frames, cameras in (((10, 2), None), ((0, 100), None), (None, ["../evil"]), (None, "CamGate")):
        with pytest.raises(ValueError):
            isaac_bridge.check_render_args(gt, frames, cameras)
