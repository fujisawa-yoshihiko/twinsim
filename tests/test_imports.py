"""すべてのモジュールが読み込めるか（分割・名前の変更の取りこぼしを見つける）。Isaac Sim の中で動く isaac/ は除く。"""

import importlib
import pkgutil

import twinsim


def test_all_modules_import():
    names = [m.name for m in pkgutil.walk_packages(twinsim.__path__, "twinsim.")]
    assert "twinsim.engine" in names and "twinsim.server" in names
    assert not any(".mopf" in n or ".reid" in n for n in names)  # 物体検知・人物照合はこのブランチに入れない
    for n in names:
        importlib.import_module(n)


def test_cli_help():
    from twinsim.__main__ import main
    try:
        main(["--help"])
    except SystemExit as e:
        assert e.code == 0
