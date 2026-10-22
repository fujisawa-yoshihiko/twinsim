"""twinsim の GUI と REST API（標準の http.server だけで動く）。

- 待ち受けは 127.0.0.1 だけ。手元の PC から `ssh -N -L 8770:localhost:8770 ampb` で開く。
- ampb には他の利用者もいて 127.0.0.1 には誰でもつなげるので、トークンを確かめる（~/.config/twinsim/token、本人だけ読める）。
  ブラウザは `?token=...` 付きの URL で一度開けば Cookie に入る。プログラムからは `Authorization: Bearer <トークン>`。
- 別のホスト名で届いた要求（DNS rebinding など）は断る。トークンはログに出さない。
使い方: python -m twinsim serve [--port 8770]   （開く URL を表示する）

API（JSON。詳しくは docs/spec.md の「API」）:
  GET  /api/spaces、/api/spaces/<名前>、/api/spaces/<名前>/top     空間の一覧・中身・真上の図
  GET  /api/templates、/api/templates/<名前>                        テンプレートの一覧・中身（既定を足したもの）
  POST /api/runs {scenario: 名前か dict, overrides, name}            計算を始める（CPU）→ {id}
  GET  /api/runs、/api/runs/<id>、/api/runs/<id>/file?path=...       結果の一覧・状態と要約・ファイル
  POST /api/runs/<id>/mopf {camera, apply}                           MOPF の人流モニターの設定を作る（apply で送る）
  POST /api/runs/<id>/render {frames, cameras, confirm}              描画（GPU）。confirm がなければ見積もりだけ返す
  GET  /api/isaac                                                    Isaac Sim が受け付けているか
"""

import argparse
import gzip
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import yaml

from . import api, isaac_bridge, mopf
from .camera import camera_dict
from .scenario import TEMPLATES, load_scenario
from .space import ROOT, list_spaces, load_space

STATIC = ROOT / "static"
RUNS = Path.home() / "dt-data/twinsim/runs"
COOKIE = "twinsim_token"
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
RENDER_FPS_EST = 2.8  # 描画の速さの目安（コマ/秒、GPU 1 枚。hospital-sim の記録）


class ApiError(Exception):
    def __init__(self, msg, status=HTTPStatus.BAD_REQUEST):
        super().__init__(msg)
        self.status = status


class App:
    def __init__(self):
        self.jobs = {}  # id → {kind, status, started, finished, error, ...}
        self.lock = threading.Lock()

    # ---- 空間・テンプレート ----
    def space(self, name):
        sp = load_space(name)
        lv = sp.spec["levels"][0]
        tv = lv.get("top_view")
        top = None
        if tv:
            c = camera_dict("top", tv["eye"], tv["target"], tv["width"], tv["height"], tv["focal_mm"], tv["h_aperture_mm"])
            M = np.asarray(c["world_to_camera_rowmajor"])
            top = {**c, "camera_to_world_rowmajor": np.linalg.inv(M).tolist()}
        rows = ["".join("." if v else "#" for v in r) for r in sp.grid[::-1]]
        return {"name": name, "title": sp.spec.get("title"), "usd": sp.spec.get("usd"), "license": sp.spec.get("license"), "z": sp.z,
                "bounds": sp.bounds(),
                "pois": sp.pois, "zones": {k: [list(p) for p in v] for k, v in sp.zones.items()},
                "cameras": sp.spec.get("cameras", {}), "top_view": top, "has_top": bool(lv.get("top_image")),
                "grid": {"x0": sp.x0, "y0": sp.y0, "res": sp.res, "rows": rows}}

    def templates(self):
        out = []
        for p in sorted(TEMPLATES.glob("*.yaml")):
            s = yaml.safe_load(p.read_text(encoding="utf-8"))
            out.append({"name": p.stem, "title": s.get("title", ""), "space": s.get("space")})
        return out

    # ---- 計算 ----
    def start_run(self, scenario, overrides=None, name=None):
        spec = load_scenario(scenario, overrides)  # ここで誤りを返す
        base = name or spec.get("name") or "run"
        safe = "".join(c for c in base if c.isalnum() or c in "-_")[:40] or "run"
        rid = f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}"
        with self.lock:
            self.jobs[rid] = {"kind": "run", "status": "running", "started": time.time()}

        def work():
            try:
                s = api.run(spec, RUNS / rid)
                self.jobs[rid].update(status="done", summary=s)
            except Exception as e:
                traceback.print_exc()
                self.jobs[rid].update(status="error", error=f"{type(e).__name__}: {e}")
            self.jobs[rid]["finished"] = time.time()
        threading.Thread(target=work, daemon=True).start()
        return rid

    def run_dir(self, rid):
        d = (RUNS / rid).resolve()
        if RUNS.resolve() not in d.parents:
            raise ApiError("結果の名前が正しくない")
        return d

    def runs(self):
        out = []
        for d in sorted(RUNS.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            if (d / "summary.json").exists() or d.name in self.jobs:
                j = self.jobs.get(d.name, {})
                out.append({"id": d.name, "status": j.get("status", "done"), "mtime": d.stat().st_mtime,
                            "videos": sorted(p.name for p in (d / "video").glob("*.mp4")) if (d / "video").exists() else []})
        return out

    def run_info(self, rid):
        d = self.run_dir(rid)
        j = {k: v for k, v in self.jobs.get(rid, {}).items() if k != "summary"}
        s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else None
        render = self.jobs.get(f"render:{rid}")
        return {"id": rid, "job": j, "summary": s, "render": render,
                "files": sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())[:200]}

    def file(self, rid, rel):
        d = self.run_dir(rid)
        p = (d / rel).resolve()
        if d not in p.parents or not p.is_file():
            raise ApiError("ファイルがない", HTTPStatus.NOT_FOUND)
        return p

    def render(self, rid, body):
        d = self.run_dir(rid)
        gt = json.loads((d / "ground_truth.json").read_text())
        frames = body.get("frames") or [0, gt["total_frames"] - 1]
        if body.get("window") == "busy":  # いちばん混む seconds 秒（試し撮り）
            n_f = int(float(body.get("seconds", 5)) * gt["fps"])
            spans = [(v["start_frame"], v["start_frame"] + len(gt["tracks"][k]) - 1) for k, v in gt["people"].items()]
            best = max(range(0, max(gt["total_frames"] - n_f, 1), gt["fps"]),
                       key=lambda f: sum(a <= f + n_f // 2 <= b for a, b in spans))
            frames = [best, min(best + n_f - 1, gt["total_frames"] - 1)]
        cams = body.get("cameras") or list(gt["cameras"])
        n = (int(frames[1]) - int(frames[0]) + 1) * len(cams)
        est = {"frames": n, "range": [int(frames[0]), int(frames[1])], "estimate_s": round(n / RENDER_FPS_EST + 120),
               "gpu": "1 枚（isim up のときに選んだもの）",
               "isaac_ready": isaac_bridge.ready()}
        if not body.get("confirm"):
            return {"estimate": est}
        if not est["isaac_ready"]:
            raise ApiError("Isaac Sim が動いていない（ampb で ./isaac_up.sh <GPU の番号>）")
        key = f"render:{rid}"
        if self.jobs.get(key, {}).get("status") == "running":
            raise ApiError("この結果の描画は実行中")
        self.jobs[key] = {"kind": "render", "status": "running", "started": time.time(), **est}

        def work():
            try:
                r = isaac_bridge.render(d, frames, cams)
                self.jobs[key].update(status="done", videos=r["videos"], seconds=r["seconds"])
            except Exception as e:
                traceback.print_exc()
                self.jobs[key].update(status="error", error=f"{type(e).__name__}: {e}")
        threading.Thread(target=work, daemon=True).start()
        return {"estimate": est, "started": True}


def load_token(path):
    path = Path(path).expanduser()
    if path.exists() and path.read_text().strip():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    token = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token + "\n")
    return token


UNAUTHORIZED = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>twinsim</title>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto;line-height:1.7">
<h1 style="font-size:1.2em">トークン付きの URL で開いてください</h1>
<p>他の利用者もいるマシンで動いているので、起動した本人だけが開けるようにしています。
ampb で <code>python -m twinsim serve --url</code> を実行すると、開く URL が表示されます。</p></body></html>"""


def make_handler(app, token):
    class H(BaseHTTPRequestHandler):
        server_version = "twinsim/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            path = urllib.parse.urlsplit(getattr(self, "path", "")).path
            sys.stderr.write(f"[twinsim] {self.log_date_time_string()} {getattr(self, 'command', '-')} {path} {fmt % args}\n")

        def log_request(self, code="-", size="-"):
            self.log_message("%s", code.value if isinstance(code, HTTPStatus) else code)

        def _send(self, status, body, ctype, extra=None):
            if int(self.headers.get("Content-Length") or 0) and not getattr(self, "_consumed", False):
                self.close_connection = True
                extra = {**(extra or {}), "Connection": "close"}
            if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", "") and not ctype.startswith(("image/", "video/")):
                body = gzip.compress(body, 5)
                extra = {**(extra or {}), "Content-Encoding": "gzip"}
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

        def _host_ok(self):
            host = (self.headers.get("Host") or "").strip().lower()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            return name in ALLOWED_HOSTS

        def _authorized(self):
            auth = self.headers.get("Authorization") or ""
            if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:].strip(), token):
                return True
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return COOKIE in c and secrets.compare_digest(c[COOKIE].value, token)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4 << 20:
                raise ApiError("要求が大きすぎる", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            raw = self.rfile.read(n) if n else b"{}"
            self._consumed = True
            return json.loads(raw or b"{}")

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            self._consumed = False
            if not self._host_ok():
                return self._send(HTTPStatus.FORBIDDEN, b"forbidden host", "text/plain; charset=utf-8")
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/api/health":
                return self._json({"ok": True})
            if "token" in query:
                if secrets.compare_digest(query["token"][0], token):
                    return self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {
                        "Location": url.path, "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"})
                return self._send(HTTPStatus.UNAUTHORIZED, UNAUTHORIZED.encode(), "text/html; charset=utf-8")
            if not self._authorized():
                if url.path.startswith("/api/"):
                    return self._json({"ok": False, "error": "トークンが要る"}, HTTPStatus.UNAUTHORIZED)
                return self._send(HTTPStatus.UNAUTHORIZED, UNAUTHORIZED.encode(), "text/html; charset=utf-8")
            try:
                if url.path.startswith("/api/"):
                    return self._api(method, url.path, {k: v[0] for k, v in query.items()})
                return self._static(url.path)
            except ApiError as e:
                return self._json({"ok": False, "error": str(e)}, e.status)
            except (ValueError, KeyError, TypeError) as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, HTTPStatus.BAD_REQUEST)
            except Exception as e:
                traceback.print_exc()
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _static(self, path):
            if path == "/":
                path = "/index.html"
            p = (STATIC / path.lstrip("/")).resolve()
            if STATIC not in p.parents or not p.is_file():
                return self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            return self._send(200, p.read_bytes(), ctype)

        def _file(self, p):
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            return self._send(200, p.read_bytes(), ctype)

        def _api(self, method, path, q):
            parts = path.strip("/").split("/")[1:]
            if method in ("GET", "HEAD"):
                if parts == ["spaces"]:
                    return self._json([{"name": n, "title": load_space(n).spec.get("title")} for n in list_spaces()])
                if len(parts) == 2 and parts[0] == "spaces":
                    return self._json(app.space(parts[1]))
                if len(parts) == 3 and parts[0] == "spaces" and parts[2] == "top":
                    sp = load_space(parts[1])
                    return self._file(sp.folder / sp.spec["levels"][0]["top_image"])
                if parts == ["templates"]:
                    return self._json(app.templates())
                if len(parts) == 2 and parts[0] == "templates":
                    return self._json(load_scenario(parts[1]))
                if parts == ["runs"]:
                    return self._json(app.runs())
                if len(parts) == 2 and parts[0] == "runs":
                    return self._json(app.run_info(parts[1]))
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "file":
                    return self._file(app.file(parts[1], q["path"]))
                if parts == ["isaac"]:
                    return self._json({"ready": isaac_bridge.ready()})
            if method == "POST":
                body = self._body()
                if parts == ["runs"]:
                    return self._json({"id": app.start_run(body["scenario"], body.get("overrides"), body.get("name"))})
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "mopf":
                    out, cfg, info = mopf.write(app.run_dir(parts[1]), body["camera"])
                    res = {"config": cfg, "info": info, "out": str(out)}
                    if body.get("apply"):
                        res["applied"] = mopf.apply(out)
                    return self._json(res)
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "render":
                    return self._json(app.render(parts[1], body))
            raise ApiError("ない API", HTTPStatus.NOT_FOUND)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(prog="twinsim serve")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--url", action="store_true", help="開く URL を表示するだけ")
    ap.add_argument("--token-file", default=str(Path.home() / ".config/twinsim/token"))
    a = ap.parse_args(argv)
    token = load_token(a.token_file)
    url = f"http://localhost:{a.port}/?token={token}"
    if a.url:
        print(url)
        return 0
    RUNS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(App(), token))
    print(f"twinsim: 127.0.0.1:{a.port} で待ち受け中。手元の PC で ssh -N -L {a.port}:localhost:{a.port} ampb を実行し、"
          f"python -m twinsim serve --url で表示される URL を開く", flush=True)
    srv.serve_forever()
