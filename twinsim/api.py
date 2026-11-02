"""Python から使う入口（twinsim.simulate など。twinsim/__init__.py から呼べる）。

    import twinsim
    result = twinsim.simulate("config.json", out_dir="runs/test")      # JSON のファイル
    result = twinsim.simulate({"space": "office_...", ...})            # dict
    result = twinsim.simulate("office_gate_ev", overrides={"duration_s": 60})   # テンプレート
    print(result.summary["people"], result.out_dir)
    labels = result.mot("CamGate")                                     # 物体検知の正解ラベル（カメラごとの枠）

overrides はシナリオの一部を上書きする dict（GUI・ほかの道具から値を変えて回すとき）。
elevator_policy(sim, t) を渡すと、EV の運行を差し替えられる（毎秒呼ばれ、car.arrivals に着く時刻を足す。UC2 の最適化の差し込み口）。
"""

import csv
import gzip
import json
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
        return np.loadtxt(p, delimiter=",", ndmin=2)


def run(scenario, out_dir, overrides=None, elevator_policy=None):
    t0 = time.monotonic()
    spec = load_scenario(scenario, overrides)
    sim, builder = build(spec)
    if elevator_policy is not None:
        sim.elevator_policy = elevator_policy
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


def template(name):
    """テンプレートを dict で返す（既定の値は足さない）。値を変えて simulate に渡す、JSON に書き出す、など。"""
    from .scenario import TEMPLATES, read_config
    if not (TEMPLATES / f"{name}.yaml").is_file():
        from .scenario import list_templates
        raise FileNotFoundError(f"テンプレート {name} がない（{', '.join(list_templates())}）")
    return read_config(name)


def render(out_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=True):
    """計算の結果を Isaac Sim で描画して video/<カメラ>.mp4 を作る（GPU。Isaac Sim の受け付けが動いているとき。tint=False で服の色を変えない）。"""
    from . import isaac_bridge
    return isaac_bridge.render(out_dir, frames, cameras, preset, tint)
