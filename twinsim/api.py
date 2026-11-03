"""Python から使う入口（twinsim.simulate など。twinsim/__init__.py から呼べる）。

    import twinsim
    result = twinsim.simulate("config.json", out_dir="runs/test")      # JSON のファイル
    result = twinsim.simulate({"space": "office_...", ...})            # dict
    result = twinsim.simulate("office_gate_ev", overrides={"duration_s": 60})   # テンプレート
    print(result.summary["people"], result.out_dir)
    labels = result.mot("CamGate")                                     # 物体検知の正解ラベル（カメラごとの枠）
    result = twinsim.open_result("runs/test")                          # 計算済みの結果を開く

overrides はシナリオの一部を上書きする dict（GUI・ほかの道具から値を変えて回すとき）。
elevator_policy(sim, t) を渡すと、EV の運行を差し替えられる（毎秒呼ばれ、car.arrivals に着く時刻を足す。運行の最適化の差し込み口）。
"""

import csv
import gzip
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config
from .outputs import write_all
from .scenario import build, load_scenario


class Result:
    """1 回の計算の結果。out_dir のファイルを読む入口。ファイルの形は docs/formats.md。"""

    def __init__(self, out_dir, summary, spec):
        self.out_dir = Path(out_dir).expanduser()
        self.summary = summary  # summary.json の中身
        self.config = spec      # 既定の値を足した設定（JSON にできる dict）

    def __repr__(self):
        return f"<twinsim.Result {self.summary.get('scenario')} {self.summary.get('people')} 人 {self.out_dir}>"

    @property
    def files(self):
        return list(self.summary.get("files", []))

    def _json(self, name):
        return json.loads((self.out_dir / name).read_text(encoding="utf-8"))

    def ground_truth(self):
        """正解: 人ごとの軌跡・状態・出来事、カメラ、EV・ゲートの出来事（ground_truth.json）。"""
        return self._json("ground_truth.json")

    def tasks(self):
        """場所ごとの人数・通過・滞留などの集計（tasks.json）。"""
        return self._json("tasks.json")

    def validity(self):
        """文献との比べ（validity.json）。"""
        return self._json("validity.json")

    def frames(self):
        """1 コマ 1 人の行を順に返す（dict: frame, t, person, x, y, yaw, moving, state, zone, group, type）。"""
        num = {"frame": int, "t": float, "x": float, "y": float, "yaw": float, "moving": int}
        with gzip.open(self.out_dir / "frames.csv.gz", "rt", newline="") as fh:
            for row in csv.DictReader(fh):
                yield {k: num[k](v) if k in num else v for k, v in row.items()}

    @property
    def cameras(self):
        return sorted(p.stem for p in (self.out_dir / "mot").glob("*.txt"))

    def mot(self, camera):
        """物体検知・追跡の正解ラベル: [frame, id, x, y, w, h, conf, class, visibility] の配列（frame は 1 始まり、MOTChallenge の形）。"""
        p = self.out_dir / "mot" / f"{camera}.txt"
        if not p.exists():
            raise FileNotFoundError(f"カメラ {camera} の枠がない（あるのは {', '.join(self.cameras) or 'なし'}。設定の cameras と outputs を確かめる）")
        return np.loadtxt(p, delimiter=",", ndmin=2) if p.stat().st_size else np.empty((0, 9))

    @property
    def videos(self):
        """描画した動画 {カメラ: mp4 の場所}（twinsim.render のあと）。"""
        return {p.stem: p for p in sorted((self.out_dir / "video").glob("*.mp4"))}

    @property
    def video_first_frame(self):
        """動画の 0 コマ目のシミュレータのコマ（一部だけ描いたときは途中から始まる）。"""
        p = self.out_dir / "render_log.json"
        return int(json.loads(p.read_text())["frames"][0]) if p.exists() else 0

    def video_frames(self, camera, frames=None, step=1):
        """動画のコマを順に返す: (シミュレータのコマ, 高さ×幅×3 の RGB の配列)。ffmpeg を使う。

        frames=(始まり, 終わり) はシミュレータのコマで、端を含む。step=30 なら 30 コマごと。
        MOT の正解ラベルの frame は、シミュレータのコマ ＋ 1。
        """
        if camera not in self.videos:
            raise FileNotFoundError(f"カメラ {camera} の動画がない（あるのは {', '.join(self.videos) or 'なし'}。先に twinsim.render）")
        gt = self.ground_truth()
        w, h, first = gt["cameras"][camera]["width"], gt["cameras"][camera]["height"], self.video_first_frame
        start, stop = frames or (first, None)
        start = max(start, first)  # 描いていない所から始めても、コマの番号をずらさない
        # 半コマ手前を指す（秒を丸めても、次のコマに飛ばないように）
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start - first - 0.5, 0) / gt['fps']:.4f}", "-i", str(self.videos[camera]),
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
            frame = start
            while stop is None or frame <= stop:
                data = proc.stdout.read(w * h * 3)
                if len(data) < w * h * 3:
                    break
                if (frame - start) % step == 0:
                    yield frame, np.frombuffer(data, np.uint8).reshape(h, w, 3)
                frame += 1
            proc.kill()


# 同じ場所に計算し直すとき、前の結果から消すもの（設定によっては書かれないので、残すと新しい結果と混ざる）
STALE_OUTPUTS = ("mot", "aicity", "graph", "logs", "preview.png", "validity.json", "validity.md", "validity.png")


def run(scenario, out_dir, overrides=None, elevator_policy=None):
    t0 = time.monotonic()
    spec = load_scenario(scenario, overrides)
    sim, builder = build(spec)
    if elevator_policy is not None:
        sim.elevator_policy = elevator_policy
        for car in sim.cars:  # 差し替えるので、設定の schedule で決めた到着は使わない
            car.arrivals = []
    sim.run()
    t1 = time.monotonic()
    out0 = Path(out_dir).expanduser()
    stale = [out0 / n for n in ("video", "render_log.json", "render_stdout.txt") if (out0 / n).exists()]
    if stale:  # 前の計算の動画・描画の記録は新しい正解と合わないので、まとめて名前を変えて残す（消さない）
        moved = out0 / f"before_{time.strftime('%Y%m%d-%H%M%S')}"
        moved.mkdir()
        for p in stale:
            p.rename(moved / p.name)
        print(f"前の動画・描画の記録を {moved} に移した（新しい計算と合わないため）")
    if (out0 / "summary.json").is_file():  # 計算の結果のフォルダのときだけ（ほかのフォルダのものは消さない）
        for name in STALE_OUTPUTS:
            p = out0 / name
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
    summary = write_all(sim, builder, spec, Path(out_dir).expanduser())
    summary["timing_s"] = {"simulate": round(t1 - t0, 1), "write": round(time.monotonic() - t1, 1)}
    out = Path(out_dir).expanduser()
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    if "validity" in spec["outputs"]:
        try:  # 文献との比べ（validity.json・md・png）。失敗しても計算の結果は残す
            from .validity import evaluate
            evaluate(out)
            summary["files"] += ["validity.json", "validity.md", "validity.png"]
            (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
        except Exception as e:
            print("validity failed:", e)
    return summary


def simulate(config_src, out_dir=None, overrides=None, elevator_policy=None):
    """人の動きを計算し、正解ラベルなどを書き出して Result を返す（CPU だけ。描画はしない）。

    config_src: dict・JSON の文字列・ファイル（.json・.yaml）の場所・テンプレートの名前
    out_dir: 書き出す場所（既定 <TWINSIM_DATA>/runs/<設定の name>、TWINSIM_DATA の既定は ~/.twinsim）
    """
    spec = load_scenario(config_src, overrides)
    out = Path(out_dir).expanduser() if out_dir else config.RUNS / (spec.get("name") or "run")
    summary = run(spec, out, elevator_policy=elevator_policy)
    return Result(out, summary, spec)


def open_result(out_dir):
    """計算済みの結果のフォルダを開いて Result を返す（計算し直さない）。"""
    out = Path(out_dir).expanduser()
    if not (out / "summary.json").is_file():
        raise FileNotFoundError(f"{out} に計算の結果（summary.json）がない。先に twinsim.simulate")
    resolved = out / "scenario_resolved.json"
    spec = json.loads(resolved.read_text(encoding="utf-8")) if resolved.is_file() else {}
    return Result(out, json.loads((out / "summary.json").read_text(encoding="utf-8")), spec)


def template(name):
    """テンプレートを dict で返す（既定の値は足さない）。値を変えて simulate に渡す、JSON に書き出す、など。"""
    from .scenario import TEMPLATES, read_config
    if not (TEMPLATES / f"{name}.yaml").is_file():
        from .scenario import list_templates
        raise FileNotFoundError(f"テンプレート {name} がない（{', '.join(list_templates())}）")
    return read_config(name)


def render(out_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=None, chunk_s=None, keep_frames=True):
    """計算の結果を Isaac Sim で描画して video/<カメラ>.mp4 を作る（GPU。Isaac Sim の受け付けが動いているとき）。
    tint=False で服の色を変えない。None なら設定の render.tint に従う。
    chunk_s（秒）を渡すと、カメラごと・その長さごとに分けて投入し、動いている受け付け全部で並べて描く（tools/render_farm.sh）。
    keep_frames=False なら、mp4 にしたあとで作業場所の画像（1 コマ約 1.6 MB）を消す。"""
    from . import isaac_bridge
    if not isaac_bridge.ready():
        raise RuntimeError("Isaac Sim が動いていない。先に ./isaac_up.sh か tools/render_farm.sh up を実行する（終わったら isim down・render_farm.sh down）")
    return isaac_bridge.render(out_dir, frames, cameras, preset, tint, chunk_s, keep_frames)
