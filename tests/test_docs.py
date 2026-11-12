"""JSON の設定の文書（チュートリアル・リファレンス）が、コードと合っているかの確かめ（CPU だけ）。

文書の ```json の塊は、全部そのまま計算に通す。{ で始まる塊は全部の設定で、それ以外は直前の設定のキーを置き換える一部。
"""

import json
import re
from pathlib import Path

import pytest

import twinsim
from twinsim.literature import PROFILES
from twinsim.scenario import CAMERA_KEYS, CONFIG_KEYS, OUTPUTS
from twinsim.space import load_space

DOCS = Path(__file__).resolve().parent.parent / "docs"
PAGES = ["config-tutorial", "config-reference"]
BASE = {"space": "office", "duration_s": 30, "streams": [{"origin": "entrance", "rate": 10, "destinations": ["south_exit"]}]}


def read(page, lang):
    return (DOCS / f"{page}{'.en' if lang == 'en' else ''}.md").read_text(encoding="utf-8")


def json_blocks(text):
    return [b.strip() for b in re.findall(r"```json\n(.*?)```", text, re.S)]


@pytest.mark.parametrize("page", PAGES)
def test_every_json_block_runs(page, tmp_path):
    base = BASE
    blocks = json_blocks(read(page, "ja"))
    assert blocks
    for i, block in enumerate(blocks):
        if block.startswith("{"):
            config = base = json.loads(block)
        else:
            config = {**base, **json.loads("{" + block + "}")}
        result = twinsim.simulate({**config, "duration_s": 30}, out_dir=tmp_path / str(i))
        assert result.summary["people"] >= 0


@pytest.mark.parametrize("page", PAGES)
def test_both_languages_show_the_same_settings(page):
    ja, en = read(page, "ja"), read(page, "en")
    assert json_blocks(ja) == json_blocks(en)
    anchors = [re.findall(r'<a id="([^"]+)"', t) for t in (ja, en)]
    assert anchors[0] == anchors[1] and anchors[0]
    assert re.findall(r"^#+ ", ja, re.M) == re.findall(r"^#+ ", en, re.M)


@pytest.mark.parametrize("name", [f"{p}{s}" for p in PAGES for s in ("", ".en")])
def test_links_lead_somewhere(name):
    text = (DOCS / f"{name}.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)\s]+)\)", text)
    assert links
    for link in links:
        path, _, anchor = link.partition("#")
        target = (DOCS / path).resolve() if path else DOCS / f"{name}.md"
        assert target.exists(), link
        if anchor:
            assert f'<a id="{anchor}"' in target.read_text(encoding="utf-8"), link


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_reference_covers_every_key(lang):
    text = read("config-reference", lang)
    keys = (CONFIG_KEYS | CAMERA_KEYS | set(OUTPUTS) | set(PROFILES)
            | {"profile", "speed", "group_size", "group_speed", "group_lateral_m", "lateral_max_m", "speed_density", "models",  # people
               "population", "period", "peak_pct_5min", "level",  # demand
               "origin", "rate", "types", "destinations", "start_s",  # streams
               "to", "p", "via", "dwell", "state", "glance", "meet", "then", "variant_p", "delay", "from",  # 行き先
               "cars", "capacity", "schedule", "alight", "transfer_s", "door_open_s", "offset", "interval", "travel_s", "max_wait_s", "dwell_s",  # EV
               "count", "service_s", "tint", "props", "gate_props", "cell_m"})
    missing = sorted(k for k in keys if f"`{k}" not in text and f'"{k}"' not in text)
    assert not missing


def test_reference_lists_the_places_of_each_space():
    text = read("config-reference", "ja")
    section = text[text.index('<a id="places">'):text.index('<a id="checks">')]
    for name in ("office", "hospital", "warehouse", "simple_room", "corridor", "corridor_door"):
        sp = load_space(name)
        names = [k for k, p in sp.pois.items() if p.get("kind") != "wait_zone"] + list(sp.spec.get("cameras", {}))
        row = next(line for line in section.splitlines() if line.startswith(f"| `{name}` "))
        missing = [k for k in names if re.sub(r"\d+$", "", k) not in row]
        assert not missing, name


def test_stated_defaults_match_the_code():
    spec = twinsim.validate(BASE)
    assert (spec["seed"], spec["fps"], spec["duration_s"]) == (0, 30, 30)
    assert spec["people"]["group_lateral_m"] == 0.66 and spec["people"]["lateral_max_m"] == 1.0
    assert spec["render"]["width"] == 1280 and spec["render"]["height"] == 720 and spec["render"]["tint"] == "per_person"
    assert set(spec["outputs"]) == set(OUTPUTS) and spec["people"]["models"] == "all"


def test_files_written_whatever_outputs_says(tmp_path):
    r = twinsim.simulate({**BASE, "outputs": []}, out_dir=tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert {"summary.json", "ground_truth.json", "frames.csv.gz", "tasks.json", "scenario_resolved.json"} <= names
    assert not {"preview.png", "validity.json", "mot", "graph"} & names and r.summary["people"] >= 0


def github_anchor(heading):
    """GitHub が見出しに付ける名前（小文字にし、文字・数字・空白・-・_ のほかを消し、空白を - に）。"""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@pytest.mark.parametrize("name", sorted(p.stem for p in [*DOCS.glob("release-*.md"), *DOCS.glob("roadmap*.md")]))
def test_release_notes_links_and_languages(name):
    """リリースノート: リンク先のファイルと見出しがあり、日本語と英語で見出しの組み立てが同じ。"""
    text = (DOCS / f"{name}.md").read_text(encoding="utf-8")
    assert "{{" not in text
    for link in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"^https?:", link):
            continue
        path, _, anchor = link.partition("#")
        target = (DOCS / path).resolve()
        assert target.exists(), link
        if anchor and target.suffix == ".md":
            heads = re.findall(r"^#+ (.+)$", target.read_text(encoding="utf-8"), re.M)
            assert anchor in {github_anchor(h) for h in heads}, link
    other = name[:-3] if name.endswith(".en") else name + ".en"
    pair = (DOCS / f"{other}.md").read_text(encoding="utf-8")
    assert re.findall(r"^#+ ", text, re.M) == re.findall(r"^#+ ", pair, re.M)
