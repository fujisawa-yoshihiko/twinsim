"""置き場所と接続先（環境変数で変えられる）。ほかのモジュールはここから読む。

  TWINSIM_DATA         計算の結果・実データで合わせたシナリオの置き場所（既定 ~/dt-data/twinsim。git の外）
  TWINSIM_MOPF_HOME    MOPF（~/MOPF_ALL_video。start_ampb.sh・stop_ampb.sh がある所）
  TWINSIM_MOPF_URL     MOPF の CV の API（既定 http://127.0.0.1:8010）
  TWINSIM_MOPF_APP_URL MOPF の画面（既定 http://localhost:5174。手元の PC から ssh -L で転送して開く）
  TWINSIM_ISAAC_WORK   Isaac Sim と受け渡しする場所（既定 ~/isaac-sim-work/twinsim）
  TWINSIM_TOKEN_FILE   GUI のトークン（既定 ~/.config/twinsim/token）
"""

import os
from pathlib import Path


def _path(env, default):
    return Path(os.environ.get(env, default)).expanduser()


DATA = _path("TWINSIM_DATA", "~/dt-data/twinsim")
RUNS = DATA / "runs"
CALIBRATION = DATA / "calibration"
MOPF_HOME = _path("TWINSIM_MOPF_HOME", "~/MOPF_ALL_video")
MOPF_CV = MOPF_HOME / "MOPF_CV_Native"
MOPF_URL = os.environ.get("TWINSIM_MOPF_URL", "http://127.0.0.1:8010")
MOPF_APP_URL = os.environ.get("TWINSIM_MOPF_APP_URL", "http://localhost:5174")
ISAAC_WORK = _path("TWINSIM_ISAAC_WORK", "~/isaac-sim-work/twinsim")
TOKEN_FILE = _path("TWINSIM_TOKEN_FILE", "~/.config/twinsim/token")
FONT_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"  # 図・動画の日本語（なければ文字なしで描く）
