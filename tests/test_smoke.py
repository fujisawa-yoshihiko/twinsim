"""動作確認（CPU だけ、数秒）: uv run --no-project --with numpy --with scipy --with pyyaml --with pillow --with pytest pytest -q tests"""

import json

from twinsim import api
from twinsim.quality import check
from twinsim.scenario import TEMPLATES, load_scenario


def test_templates_validate():
    for p in TEMPLATES.glob("*.yaml"):
        load_scenario(p.stem)


def test_smoke_run(tmp_path):
    s = api.run("office_smoke", tmp_path / "run")
    assert s["people"] > 0
    gt = json.loads((tmp_path / "run/ground_truth.json").read_text())
    assert set(gt["tracks"]) == set(gt["people"])
    for f in ("frames.csv.gz", "tasks.json", "graph/graph.json", "mot/CamEV.txt"):
        assert (tmp_path / "run" / f).exists(), f
    q = check(tmp_path / "run")
    assert q["not_walkable_frac"] < 0.005
    assert q["closest_non_group_pair_m"]["p1"] > 0.05


def test_same_seed_same_result(tmp_path):
    a = api.run("office_smoke", tmp_path / "a")
    b = api.run("office_smoke", tmp_path / "b")
    ga = json.loads((tmp_path / "a/ground_truth.json").read_text())
    gb = json.loads((tmp_path / "b/ground_truth.json").read_text())
    assert ga["tracks"] == gb["tracks"] and a["people"] == b["people"]
