"""MOPF（~/MOPF_ALL_video）との連携。

  monitor    人流モニターの設定（床の図・位置合わせ・線・エリア）をシミュレータのカメラと空間から作り、MOPF に送る
  process    描いた動画を MOPF で検出・追跡する（GPU）
  evaluate   MOPF の追跡を正解と比べる
  graph      MOPF の追跡から中間層のグラフ（シミュレータの graph/ と同じ形）
  crossings  人流モニターの数え方: 正解なら数えるはずの値・MOPF で横切った出来事・その突き合わせ
  floormap   MOPF の追跡を床に写した図（正解の軌跡と並べる）
  overlay    正解と MOPF の枠を重ねた動画・数えもらした場面の画像
  identity   カメラを時刻でそろえ、同じ人が各カメラでどの MOPF の ID だったか（対応表・並べた動画）
  control    MOPF の起動・停止・状態（start_ampb.sh・stop_ampb.sh）と、ライブの集計の中継
  synthetic  確かめ用の MOPF の形の追跡
  io         共通の読み込み
"""

from . import control
from .crossings import compare_crossings, expect, track_crossings
from .evaluate import evaluate
from .floormap import floormap
from .graph import graph
from .identity import identities, sync_video
from .io import ensure_ids, load_mot_gt, load_tracks, open_run
from .monitor import apply, build_config, write
from .overlay import overlay
from .process import mopf_ready, process
from .synthetic import synthetic_tracks

__all__ = ["control", "apply", "build_config", "compare_crossings", "ensure_ids", "evaluate", "expect", "floormap", "graph",
           "identities", "sync_video", "load_mot_gt", "load_tracks", "mopf_ready", "open_run", "overlay", "process", "synthetic_tracks",
           "track_crossings", "write"]
