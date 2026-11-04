"""ガラスの奥の人の隠れ（twinsim/glass.py）の確かめ（CPU だけ）。"""

import pytest

from twinsim import glass
from twinsim.camera import Camera, camera_dict
from twinsim.space import load_space


def box(lo, hi):
    """軸にそろった箱の 8 つの角（probe_materials.py と同じ並び: k のビット i が軸 i の大きい側）。"""
    return [[(lo, hi)[(k >> i) & 1][i] for i in range(3)] for k in range(8)]


CAM = Camera(camera_dict("c", eye=(0.0, 0.0, 2.5), target=(5.0, 0.0, 0.9)))


def frac(*boxes):
    return glass.GlassOcclusion(CAM, glass.boxes_from_corners([box(lo, hi) for lo, hi in boxes])).fraction(5.0, 0.0, 1.75)


def test_pane_between_camera_and_person_hides_all():
    assert frac(((2.5, -2.0, 0.0), (2.5, 2.0, 3.0))) == 1.0  # 厚みのない板


def test_pane_behind_person_or_beside_does_not_count():
    assert frac(((7.0, -2.0, 0.0), (7.0, 2.0, 3.0))) == 0.0
    assert frac(((2.5, 3.0, 0.0), (2.5, 5.0, 3.0))) == 0.0
    assert frac() == 0.0


def test_low_pane_hides_lower_part():
    f = frac(((2.5, -2.0, 0.0), (2.5, 2.0, 1.7)))  # 線が板を通る高さは (2.5 + 点の高さ) / 2。点の高さ 0.9 m 以下が隠れる
    assert 0.3 < f < 0.7


def test_person_touching_pane_is_behind_it():
    assert frac(((4.7, -2.0, 0.0), (4.76, 2.0, 3.0))) == 1.0


def test_spaces_glass_files_load():
    for name in ("office", "hospital"):
        sp = load_space(name)
        if sp.spec.get("glass"):
            b = glass.load_boxes(sp)
            assert b is not None and len(b["center"]) > 0
        assert (sp.folder / "glass.json").exists()


@pytest.mark.parametrize("thin_axis", [0, 1, 2])
def test_boxes_from_corners_thin_axes(thin_axis):
    lo, hi = [0.0, 0.0, 0.0], [1.0, 2.0, 3.0]
    hi[thin_axis] = 0.0
    b = glass.boxes_from_corners([box(lo, hi)])
    assert b["half"][0][thin_axis] == glass.THIN_M
