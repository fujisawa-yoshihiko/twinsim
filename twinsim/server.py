"""twinsim の GUI と REST API（標準の http.server だけで動く）。

- 待ち受けは 127.0.0.1 だけ。手元の PC から `ssh -N -L 8770:localhost:8770 ampb` で開く。
- ampb には他の利用者もいて 127.0.0.1 には誰でもつなげるので、トークンを確かめる（~/.config/twinsim/token、本人だけ読める）。
  ブラウザは `?token=...` 付きの URL で一度開けば Cookie に入る。プログラムからは `Authorization: Bearer <トークン>`。
- 別のホスト名で届いた要求（DNS rebinding など）は断る。トークンはログに出さない。
使い方: python -m twinsim serve [--port 8770]   （開く URL を表示する）

API（JSON。詳しくは docs/spec.md の「API」）:
  GET  /api/spaces、/api/spaces/<名前>、/api/spaces/<名前>/top     空間の一覧・中身・真上の図
  GET  /api/templates、/api/templates/<名前>                        テンプレートの一覧・中身（既定を足したもの）
  GET  /api/profiles                                                 文献に基づく人の分布の組（people.profile）と文献の一覧
  POST /api/runs {scenario: 名前か dict, overrides, name}            計算を始める（CPU）→ {id}
  GET  /api/runs、/api/runs/<id>、/api/runs/<id>/file?path=...       結果の一覧・状態と要約・ファイル
  GET  /api/runs/<id>/file?path=..&download=1、/api/runs/<id>/zip[?videos=1]   ダウンロード（zip は既定で動画を除く）
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

from . import __version__, api, config, isaac_bridge
from .camera import camera_dict
from .literature import LIFT_MIX, PROFILES, REFS
from .scenario import TEMPLATES, list_templates, load_scenario
from .space import ROOT, list_spaces, load_space

STATIC = ROOT / "static"
RUNS = config.RUNS
COOKIE = "twinsim_token"
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
RENDER_FPS_EST = 2.8  # 描画の速さの目安（コマ/秒、GPU 1 枚。hospital-sim の記録）
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


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
        return {"name": name, "title": sp.spec.get("title"), "title_en": sp.spec.get("title_en"), "usd": sp.spec.get("usd"),
                "license": sp.spec.get("license"), "license_en": sp.spec.get("license_en"), "z": sp.z,
                "bounds": sp.bounds(),
                "pois": sp.pois, "zones": {k: [list(p) for p in v] for k, v in sp.zones.items()},
                "cameras": sp.spec.get("cameras", {}), "top_view": top, "has_top": bool(lv.get("top_image")),
                "grid": {"x0": sp.x0, "y0": sp.y0, "res": sp.res, "rows": rows}}

    def templates(self):
        out = []
        for p in sorted(TEMPLATES.glob("*.yaml")):
            s = yaml.safe_load(p.read_text(encoding="utf-8"))
            out.append({"name": p.stem, "title": s.get("title", ""), "title_en": s.get("title_en", ""), "space": s.get("space")})
        return out

    # ---- 計算 ----
    def start_run(self, scenario, overrides=None, name=None):
        # 画面から渡せるのは設定そのものかテンプレートの名前だけ（サーバーの上のファイルを読ませない）
        if isinstance(scenario, str) and scenario not in list_templates():
            raise ApiError(f"テンプレート {scenario} がない", HTTPStatus.NOT_FOUND)
        spec = load_scenario(scenario, overrides)  # ここで誤りを返す
        base = name or spec.get("name") or "run"
        safe = "".join(c for c in base if c.isalnum() or c in "-_")[:40] or "run"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with self.lock:  # 同じ秒に始めた計算が同じ場所に書かないように
            rid, n = f"{safe}-{stamp}", 1
            while rid in self.jobs or (RUNS / rid).exists():
                n += 1
                rid = f"{safe}-{stamp}-{n}"
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
        if rid not in self.jobs and not d.is_dir():
            raise ApiError("結果がない", HTTPStatus.NOT_FOUND)
        j = {k: v for k, v in self.jobs.get(rid, {}).items() if k != "summary"}
        s = json.loads((d / "summary.json").read_text()) if (d / "summary.json").exists() else None
        render = self.jobs.get(f"render:{rid}")
        return {"id": rid, "job": j, "summary": s, "render": render,
                "files": sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())[:200]}

    def zip(self, rid, videos=False):
        """結果をまとめた zip（既定は動画を除く）。返り値: (ファイルの名前, 中身)"""
        import io
        import zipfile
        d = self.run_dir(rid)
        if not d.is_dir():
            raise ApiError("結果がない", HTTPStatus.NOT_FOUND)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(d.rglob("*")):
                rel = p.relative_to(d)
                if p.is_symlink() or not p.is_file() or rel.parts[0].startswith(("before_", "video_before_")):
                    continue
                if p.suffix == ".mp4" and not videos:
                    continue
                z.write(p, f"{rid}/{rel}")
        return f"{rid}{'' if videos else '-no-video'}.zip", buf.getvalue()

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
        isaac_bridge.check_render_args(gt, frames, cams)
        n = (int(frames[1]) - int(frames[0]) + 1) * len(cams)
        est = {"frames": n, "range": [int(frames[0]), int(frames[1])], "estimate_s": round(n / RENDER_FPS_EST + 120),
               "gpu": "1 枚（isim up のときに選んだもの）",
               "isaac_ready": isaac_bridge.ready()}
        if not body.get("confirm"):
            return {"estimate": est}
        if not est["isaac_ready"]:
            raise ApiError("Isaac Sim が動いていない（./isaac_up.sh で起動する）")
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
        if path.stat().st_mode & 0o077:  # 他の利用者が読めると、画面を開けてしまう
            os.chmod(path, 0o600)
        return path.read_text().strip()
    if not path.parent.exists():
        path.parent.mkdir(parents=True)
        os.chmod(path.parent, 0o700)
    token = secrets.token_urlsafe(24)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(token + "\n")
    return token


def same_token(a, b):
    return secrets.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))


UNAUTHORIZED = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>twinsim</title>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto;line-height:1.7">
<h1 style="font-size:1.2em">トークン付きの URL で開いてください</h1>
<p>他の利用者もいるマシンで動いているので、起動した本人だけが開けるようにしています。
サーバーで <code>twinsim serve --url</code> を実行すると、開く URL が表示されます。</p></body></html>"""


def make_handler(app, token):
    class H(BaseHTTPRequestHandler):
        server_version = f"twinsim/{__version__}"
        protocol_version = "HTTP/1.1"
        timeout = 120  # 開いたままの接続を残さない

        def log_message(self, fmt, *args):
            path = urllib.parse.urlsplit(getattr(self, "path", "")).path
            sys.stderr.write(f"[twinsim] {self.log_date_time_string()} {getattr(self, 'command', '-')} {path} {fmt % args}\n")

        def log_request(self, code="-", size="-"):
            self.log_message("%s", code.value if isinstance(code, HTTPStatus) else code)

        def _length(self):
            try:
                return max(int(self.headers.get("Content-Length") or 0), 0)
            except ValueError:
                return 0

        def _send(self, status, body, ctype, extra=None):
            if self._length() and not getattr(self, "_consumed", False):
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
            self.send_header("Content-Security-Policy", CSP)
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

        def _bearer(self):
            auth = self.headers.get("Authorization") or ""
            return auth.startswith("Bearer ") and same_token(auth[7:].strip(), token)

        def _authorized(self):
            if self._bearer():
                return True
            for part in (self.headers.get("Cookie") or "").split(";"):  # 別のアプリの Cookie があっても読めるように、1 つずつ見る
                c = SimpleCookie(part.strip())
                if COOKIE in c:
                    return same_token(c[COOKIE].value, token)
            return False

        def _same_origin(self):
            """Cookie での POST は、この画面から来たものだけ受ける（同じ PC の別のポートのページからの CSRF を防ぐ）。"""
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlsplit(origin).netloc != (self.headers.get("Host") or ""):
                return False
            return (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json"

        def _body(self):
            n = self._length()
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
                if same_token(query["token"][0], token):
                    return self._send(HTTPStatus.SEE_OTHER, b"", "text/plain", {
                        "Location": url.path, "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"})
                return self._send(HTTPStatus.UNAUTHORIZED, UNAUTHORIZED.encode(), "text/html; charset=utf-8")
            if not self._authorized():
                if url.path.startswith("/api/"):
                    return self._json({"ok": False, "error": "トークンが要る"}, HTTPStatus.UNAUTHORIZED)
                return self._send(HTTPStatus.UNAUTHORIZED, UNAUTHORIZED.encode(), "text/html; charset=utf-8")
            if method == "POST" and not self._bearer() and not self._same_origin():
                return self._json({"ok": False, "error": "この画面からの要求ではない"}, HTTPStatus.FORBIDDEN)
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

        def _file(self, p, download=False):
            """ファイルを返す。Range（動画の早送り・途中から）に対応。download でダウンロード（保存）にする。"""
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/"):
                ctype += "; charset=utf-8"
            extra = {"Accept-Ranges": "bytes"}
            if download:
                extra["Content-Disposition"] = f"attachment; filename*=UTF-8''{urllib.parse.quote(p.name)}"
            size = p.stat().st_size
            rng = self.headers.get("Range", "")
            if rng.startswith("bytes=") and "," not in rng:
                a, _, b = rng[6:].partition("-")
                start = int(a) if a else max(0, size - int(b))
                end = min(int(b), size - 1) if (a and b) else size - 1
                if start >= size or start > end:
                    return self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                with open(p, "rb") as fh:
                    fh.seek(start)
                    body = fh.read(end - start + 1)
                return self._send(HTTPStatus.PARTIAL_CONTENT, body, ctype, {**extra, "Content-Range": f"bytes {start}-{end}/{size}"})
            return self._send(200, p.read_bytes(), ctype, extra)

        def _api(self, method, path, q):
            parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")[1:]]  # 日本語の名前の結果も開けるように
            if method in ("GET", "HEAD"):
                if parts == ["profiles"]:
                    profiles = {k: {"title": v["title"], "title_en": v.get("title_en"), "sources": v["sources"], "notes": v.get("notes", []),
                                    "notes_en": v.get("notes_en")} for k, v in PROFILES.items()}
                    return self._json({"profiles": profiles,
                                       "periods": list(LIFT_MIX), "refs": {k: r["cite"] for k, r in REFS.items()}})
                if parts == ["spaces"]:
                    return self._json([{"name": n, "title": load_space(n).spec.get("title")} for n in list_spaces()])
                if len(parts) >= 2 and parts[0] == "spaces" and parts[1] not in list_spaces():
                    raise ApiError("空間がない", HTTPStatus.NOT_FOUND)  # load_space はフォルダの場所も読むので、一覧の名前だけにする
                if len(parts) == 2 and parts[0] == "spaces":
                    return self._json(app.space(parts[1]))
                if len(parts) == 3 and parts[0] == "spaces" and parts[2] == "top":
                    sp = load_space(parts[1])
                    return self._file(sp.folder / sp.spec["levels"][0]["top_image"])
                if parts == ["templates"]:
                    return self._json(app.templates())
                if len(parts) == 2 and parts[0] == "templates":
                    if parts[1] not in list_templates():
                        raise ApiError("テンプレートがない", HTTPStatus.NOT_FOUND)
                    return self._json(load_scenario(parts[1]))
                if parts == ["runs"]:
                    return self._json(app.runs())
                if len(parts) == 2 and parts[0] == "runs":
                    return self._json(app.run_info(parts[1]))
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "file":
                    return self._file(app.file(parts[1], q["path"]), download=q.get("download") == "1")
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "zip":
                    name, body = app.zip(parts[1], videos=q.get("videos") == "1")
                    return self._send(200, body, "application/zip",
                                      {"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}"})
                if parts == ["isaac"]:
                    return self._json({"ready": isaac_bridge.ready()})
            if method == "POST":
                body = self._body()
                if parts == ["runs"]:
                    return self._json({"id": app.start_run(body["scenario"], body.get("overrides"), body.get("name"))})
                if parts == ["validate"]:  # 既定の値を足した設定を返す（画面の「この JSON を反映」）
                    if not isinstance(body.get("scenario"), dict):
                        raise ApiError("scenario は設定のオブジェクト")
                    return self._json({"scenario": load_scenario(body["scenario"])})
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "render":
                    return self._json(app.render(parts[1], body))
            raise ApiError("ない API", HTTPStatus.NOT_FOUND)
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(prog="twinsim serve")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--url", action="store_true", help="開く URL を表示するだけ")
    ap.add_argument("--token-file", default=str(config.TOKEN_FILE))
    a = ap.parse_args(argv)
    token = load_token(a.token_file)
    url = f"http://localhost:{a.port}/?token={token}"
    if a.url:
        print(url)
        return 0
    RUNS.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(App(), token))
    print(f"twinsim: 127.0.0.1:{a.port} で待ち受け中。twinsim serve --port {a.port} --url で表示される URL を開く"
          f"（別の PC からは ssh -N -L {a.port}:localhost:{a.port} <サーバー> でつなぐ）", flush=True)
    srv.serve_forever()
