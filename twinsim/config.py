"""置き場所と接続先（環境変数で変えられる）。ほかのモジュールはここから読む。

  TWINSIM_DATA         計算の結果・実データで合わせたシナリオの置き場所（既定 ~/.twinsim。git の外。./run.sh は ~/dt-data/twinsim）
  TWINSIM_SPACES       自分の空間（<名前>/space.yaml か space.json）を置く場所。付属の空間より先に探す
  TWINSIM_ISAAC_WORK   Isaac Sim と受け渡しする場所（既定 ~/isaac-sim-work/twinsim）
  TWINSIM_TOKEN_FILE   GUI のトークン（既定 ~/.config/twinsim/token）
"""

import os
from pathlib import Path


def _path(env, default):
    return Path(os.environ.get(env, default)).expanduser()


DATA = _path("TWINSIM_DATA", "~/.twinsim")
RUNS = DATA / "runs"
CALIBRATION = DATA / "calibration"
USER_SPACES = _path("TWINSIM_SPACES", "") if os.environ.get("TWINSIM_SPACES") else None
ISAAC_WORK = _path("TWINSIM_ISAAC_WORK", "~/isaac-sim-work/twinsim")
TOKEN_FILE = _path("TWINSIM_TOKEN_FILE", "~/.config/twinsim/token")
FONT_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"  # 図の日本語


def font(size):
    """図の文字のフォント。日本語のフォントがなければ既定のフォントで描く（日本語は読めないが、図はできる）。"""
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT_CJK, size)
    except OSError:
        return ImageFont.load_default(size)
