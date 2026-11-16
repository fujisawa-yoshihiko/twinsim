"""人の動きの計算（1 コマずつ、Isaac Sim なしで動く）。
digitaltwin の hospital-sim/scripts/flow_scene_lib.py・flow_scene2_lib.py（経路に沿った歩行とよけ合い、段取りの列で動く人）を、
複数台のエレベーター・入館のゲート（レーンごとの列）・出口・壁へのめり込みの補正に広げたもの。

段取り（Agent.plan の要素）:
  ("walk", 行き先, 状態, {"until_zone": ゾーン})  行き先まで歩く（経路は空間の A*）。until_zone に入ったら次へ
  ("gate", ゲートの名前)                          列の短いレーンに並び、前の人が通ってから service_s 秒（分布でもよい）あけて通る
  ("stop", 秒, 向く点, 状態, 見回す角度)          その場で止まる
  ("meet", Meet, 向く点, 状態, 見回す角度)        待ち合わせの全員がそろうまで待つ（同行者待ち）
  ("wait_ev", 見回す角度)                         EV 待ちの場所に立ち、着いた EV に着いた順に定員まで乗る（扉で消える）。
                                                  扉が開いてから降りる人 → 乗る人の順に 1 人 transfer_s 秒ずつ
  ("exit",)                                       消える（出口・建物の外へ）
  ("regroup", ゲートの段取り, 最長の秒数)         ゲートを先に通った人が、通った先で仲間を待つ（cfsm。ゲートを通ったときに足す）
状態（1 コマごとの正解）: pass・gate_queue・ev_approach・ev_wait・alight・reception・dwell・sign_check・companion_wait・group_wait
歩く速さは、前の半円（半径 speed_density.radius m）の人の密度から Weidmann (1993) の速さと密度の関係で落とす（グループの仲間は数えない）。
"""

import math
import random
import zlib

import numpy as np

from . import dists
from .components import SEAT_MOVE_M_S, ComponentsMixin
from .literature import GROUP_DENSITY, GROUP_RELATIONS, group_lateral_scale, weidmann_speed

TURN_DEG_S = 90.0
WALKING = ("walk", "to_spot", "board", "to_gate", "gate_pass")
# 前の人についていく速さの上限: 前の人までの距離 d に要る長さ d = a + b v（Seyfried ら 2005、1 列の歩行の測定 a = 0.36 m, b = 1.06 s）
FOLLOW = {"a": 0.36, "b": 1.06, "lateral": 0.45, "overtake_m_s": 0.5}
MIN_SEP = 0.35  # グループ以外の 2 人の中心がこれより近づく一歩は取り消す（m。肩幅 0.45 m・胸の厚さ 0.3 m ほど）
QUEUE_GAP = 0.65  # ゲートの列の前後の間隔（m）。0.6 では混んだ列で 0.45 m 未満に近づく場面が 8.5%、0.65 で 2.6%（verify_gate_capacity）
QUEUE_LANE_OFF = 0.6  # 列が経路に沿って曲がった先で、隣のレーンの列との横の間隔（m）
GROUP_GAP = 0.4  # グループの仲間と前後にこれ以上離れたら、前の人は遅く・後ろの人は速く（最大 1.3 倍）歩いて戻る
NO_WALL_LAT_M = 0.35  # 扉の向こう（歩ける所の外）との行き来で、まっすぐな線から横へずれてよい幅（m。2 人がすれ違える 2 × 0.18 m 以上）
NO_WALL_BACK = 0.5  # 扉の向こうへの線から大きく外れたとき、1 コマに戻す幅（自分の速さ × dt に対する割合）
PASS_SIDE = 1.0  # 真正面の人をよける向き（+1 = 進む向きの左。日本の歩道の左側通行）
GOAL_NEAR_M, GOAL_STALL_S = 1.2, 2.0  # 行き先からこの距離の中で、この秒数ほとんど進めなければ、そこで着いたことにする
DOOR_CLEAR_M = 1.0  # EV の扉からこれより近くでは待たない（motion_model "cfsm"）
AISLE_M = (2.5, 1.2)  # EV の扉から外へ、この長さ・幅の通り道でも待たない（降りる人が待つ人の中を通り抜けていた、2026-11-05）
ENTRY_CLEAR_M = 0.5  # 扉の向こうから入る人は、扉の点からこの距離の中に人がいれば外で待つ（m。1.0 m では入る人が 192 → 106 人に減った）
MATE_SPAWN_M = 0.4  # グループの仲間が現れる点からこの距離（m）より近ければ、次の仲間は待つ（同じ点に重なって現れないように）
LEAVE_LOOK_M = 5.0  # 入る人が出る人の線を使うのは、そこを出ていく人が扉の点からこの距離（m）の中にいないとき
# この秒数進めずにいる歩く人は、行き先の向きの前側のこの距離（m）以内に立つ人に道をあけてもらう。距離は 0.9 → 1.2 m（1.2、2026-11-16。
# 立つ人と 1.0〜1.1 m で釣り合って止まる人がいた。安全弁が EV の前で 1 回あたり 0.9〜3.8 → 0.2〜0.7、docs/validity.md の 5.13）
NUDGE_ASK_S, NUDGE_ASK_M = 3.0, 1.2
# EV に乗る人・降りた人の扉までの道（前 CLEAR_AHEAD_M・横 CLEAR_W_M の中）に立って待つ人は、進めなくなる前に横へよける。降りた人は扉から CLEAR_DOOR_M の中だけ
CLEAR_AHEAD_M, CLEAR_W_M, CLEAR_DOOR_M = 1.5, 0.5, 4.0
GROUP_STOP_WAIT_S = 60.0  # 止まる段取りを先に済ませた人が、仲間を待つ最長の秒数
# グループの組み方（motion_model "cfsm"、1.2）。仲間はそれぞれ、先導の人（最初に現れた人）からの持ち場（横・前後）へ寄る
# グループの周りの密度: 文献（Zanlungo ら 2015、0.5 m 角のセルの人数を 300 秒ならした値）に合わせ、0.5 m 角のセルの人数を FORM_RHO_TAU 秒の
# 指数移動平均でならし、グループの中心の周り 3 × 3 のセル（1.5 m 角）で平均する。前は周り 2 m の今の人数で測り、EV の前では横で立って待つ人も
# 数えて、判定（文献と同じ測り方）より混んでいると見て横を狭めすぎた（office_ev_hall の 0.15〜0.3 人/m² で 0.2 m 狭い、2026-11-12）
FORM_RHO_CELL_M, FORM_RHO_TAU = 0.5, 150.0
FORM_FILE_LAT = 0.36  # 隣の持ち場との距離がこれより狭くなる（混む・通路が狭い）と、縦 1 列に並ぶ（m。体の幅。3 人組は V 字の前後 0.14 m も入れた距離）
# 持ち場の前後の揺らぎの時定数（秒。文献の値がないので仮）。揺らぎの大きさは、2 人連れの前後の差の平均（関係ごと、Zanlungo ら 2017）に合わせる
FORM_LON_TAU = 5.0
FORM_FILE_GAP = 0.8  # 縦 1 列のときの前後の間隔（m。仲間についていく間隔 0.36 + 0.5 秒 × 0.9 m/s ほど）
FORM_ROW_GAP = 0.7  # 4 人以上の後ろの列の、前の列からの距離（m。文献の値がないので仮）
FORM_NEAR = 4.0  # 先導の人からこの距離より遠い仲間は、持ち場へ寄らず自分の経路を歩く（前後のまとまりで追いつく）
FORM_GAIN = 1.0  # 持ち場との前後のずれ 1 m あたりに足し引きする速さ（m/s）
FORM_END_M = 2.5  # 行き先（止まる所など）の手前この距離からは、持ち場へ寄らず自分の行き先へ歩く
REGROUP_M = 2.0  # ゲートを先に通った人が仲間を待つ所（通った向きに、ゲートからこの距離。m）
REGROUP_MAX_S = 30.0  # ゲートの先で仲間を待つ最長の秒数（文献の値がないので仮）
GROUP_LANE_EXTRA = 1  # ゲートで、仲間が並ぶレーンの列が、いちばん短い列よりこの人数まで長くても、仲間のレーンに並ぶ
GROUP_EV_WAIT_S = 60.0  # EV の前で、まだ来ない仲間を待って乗らずにいる最長の秒数
FORM_TAKEN_M = 0.5  # 持ち場からこの距離（m）の中に知らない人がいれば、持ち場へ寄らず自分の経路を歩く
FORM_STALL_S, FORM_OFF_S = 2.0, 4.0  # この秒数行き先に近づけなければ、この秒数のあいだ持ち場へ寄らない
MATE_SPOT_M = 1.0  # EV を待つ場所は、グループの仲間の待つ場所からこの距離（m）以内の空いた所を選ぶ（なければ扉に近い所）
LINK_M = 1.3  # この距離より近い仲間どうしを結ぶ線を、知らない人はよける（間を通らない。3 人組の両端 1.1 m を入れる）
LD_RECOVER_PER_S = 0.5  # 歩く人の横のずれ（l_pref）を壁の手前で減らしたあと、1 秒に戻す割合
YIELD_S, YIELD_LAT, YIELD_D = 5.0, 0.6, 1.0  # 合流で譲る: この秒数進めずにいる人が、斜め前のこの横・距離（m）の中にいれば先に入れる
DETOUR_MOVED_M = 0.3  # その 1 秒にこれ以上動いた人だけ、大回りの経路の残りの長さでも進み具合を見る（m）
DETOUR_M = 2.0  # 経路の残りの長さが行き先までの直線距離よりこれ以上長ければ、大回りの経路として残りの長さでも進み具合を見る（m）
UNSTICK_S, SQUEEZE_S = 15.0, 2.0  # 安全弁: この秒数行き先に近づけなければ、この秒数だけ周りの人を無視して通り抜ける
BOARD_LANE_M = (0.25, 0.35)  # EV に乗る 2 列の、扉とかごの中での真ん中からの横のずれ（m）
BOARD_FRONT_M = 0.6  # 扉の横（扉の前へこれより出ていない所）から乗る人は、扉の前のこの距離の点を通ってから入る（m。0 で通らない）
REROUTE_M = 1.5  # 歩く人が経路からこれより離れたら、今の位置から経路を引き直す（m）
HOME_CLEAR_M = 0.9  # 道をあけた人は、歩く人がこれより離れたら元の立つ場所へ戻る
SPACE_M, SPACE_M_S, SPACE_MAX_M = 0.45, 0.2, 0.4  # EV を待つ人は、知らない人と SPACE_M より近ければ、SPACE_M_S で離れる（立った所から SPACE_MAX_M まで）
NUDGE_M_S = 0.4  # 立っている人が、ふさいだ歩く人に道をあけるときの速さ（m/s、1.5 秒まで）
SEPARATE_M_S = 0.3  # 歩く人が、体の幅より近い人から離れるときの速さ（m/s。重なったまま止まらないように）
BALANCE_E = 0.5  # 行き先へ引く向きと周りの人・壁から離れる向きの和の長さがこれより短ければ（打ち消し合う）、長さに比例して遅くする
BACK_M_S = SEPARATE_M_S  # 行き先と逆向きに押し戻される一歩の速さの上限（m/s）
CHATTER_S = 0.5  # 遅くするのは、向きが 90 度より大きく逆になってからこの秒数のあいだと、そのあと和が短いままのあいだ（0 でいつも）
OUT_TAU = 0.3  # 書き出す「歩いているか」と体の向きは、この時定数（秒）でならした速さから決める（0 で 1 コマの一歩から。前の決め方）
MOVE_ON_M_S, MOVE_OFF_M_S = 0.2, 0.1  # ならした速さがこれを超えたら歩き始め、これを下回ったら止まる（入れ替わりが毎コマ起きないように）
# 人どうしがぶつからない動き（Collision-Free Speed Model、Tordeux・Chraibi・Seyfried 2016。JuPedSim の CollisionFreeSpeedModel と同じ形）。
# 速さ = min(自分の速さ, (前の人までの距離 − 2 × 半径) ÷ time_gap)。前の人は、進む向きの、体の幅（2 × 半径）の帯の中の人。
# 向き = 行き先の向き + 周りの人から離れる向き（strength × exp((2 × 半径 − 距離) ÷ range)）+ 壁から離れる向き。
# 半径と time_gap は前の人についていく規則と同じ Seyfried ら 2005 の値（2 × 0.18 = 0.36 m、1.06 秒）、離れる向きの強さと距離は JuPedSim の既定。
# 周りの人から離れる向きが届く距離は 0.25 m（JuPedSim の既定 0.1 m では遅い人の後ろについたままになり、速さと密度の関係が文献より遅かった。
# 0.1・0.2・0.25・0.3 m と強さ 3・5・8 を比べ、Weidmann の式と幅 1 m の出入口の実験に合う組を選んだ。docs/validity.md の 5、2026-11-05）
CFSM = {"radius": FOLLOW["a"] / 2, "time_gap": FOLLOW["b"], "neighbor_strength": 8.0, "neighbor_range": 0.25,
        "wall_strength": 5.0, "wall_range": 0.1,  # JuPedSim の既定は 0.02 m。歩ける所の格子が 0.25〜0.5 m と粗いので広くする
        "mate_range": 0.05, "mate_time_gap": 0.5, "cutoff": 3.0, "look_m": 1.0, "arrive_m": 0.15, "min_sep": 0.32}


def group_slots(size, relation, lateral_m=None, scale=1.0):
    """グループの持ち場 [(横, 前後), ...]（m。横は左が正、前後は前が正）。並びは仲間の順（先導の人が 0 番）。
    2 人連れは横に並ぶ（前後の差は平均 0、Zanlungo ら 2015）、3 人組は V 字（真ん中の人が 0.14 m 後ろ、同じ）。
    横の広がりは関係ごとの値（GROUP_RELATIONS）× scale（密度で狭める比、group_lateral_scale）。lateral_m を与えると 2 人連れの横はその値
    （設定の people.group_lateral_m、3 人組は文献の比 1.096 / 0.646 で広げる）。4 人以上は前の列と後ろの列の 2 列（文献の値がないので仮）。
    隣との横の間隔が FORM_FILE_LAT より狭ければ、縦 1 列（FORM_FILE_GAP おき）。"""
    if size <= 1:
        return [(0.0, 0.0)]
    rel = GROUP_RELATIONS.get(relation) or GROUP_RELATIONS["friends"]
    x2 = float(lateral_m) if lateral_m is not None else rel["dyad"]["x"]
    x3 = x2 * GROUP_DENSITY["triad_x"][0] / GROUP_DENSITY["dyad_x"][0] if lateral_m is not None else rel["triad"]["x"]
    if size == 2:
        gap = x2 * scale
        slots = [(gap / 2, 0.0), (-gap / 2, 0.0)]
    elif size == 3:
        gap = x3 * scale / 2
        slots = [(gap, 0.0), (0.0, -GROUP_DENSITY["triad_v_m"]), (-gap, 0.0)]
        gap = math.hypot(gap, GROUP_DENSITY["triad_v_m"])
    else:
        gap = x2 * scale
        front = (size + 1) // 2
        slots = [((front - 1) / 2 * gap - k * gap, 0.0) for k in range(front)]
        back = size - front
        slots += [((back - 1) / 2 * gap - k * gap, -FORM_ROW_GAP) for k in range(back)]
    if gap < FORM_FILE_LAT:
        slots = [(0.0, -FORM_FILE_GAP * k) for k in range(size)]
    return slots


class Path:
    """折れ線の経路。step m ごとの点にしておき、s（経路に沿った長さ）と l（左向きを正とする横のずれ）から位置を返す。"""

    def __init__(self, pts, step=0.25):
        pts = [tuple(map(float, p[:2])) for p in pts]
        if len(pts) == 1:
            pts = pts * 2
        dense = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            dense += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n)]
        dense.append(pts[-1])
        self.p = np.array(dense)
        seg = np.linalg.norm(np.diff(self.p, axis=0), axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(seg)])
        self.length = float(self.cum[-1])
        t = np.zeros_like(self.p)
        for i in range(len(self.p)):
            a, b = self.p[max(i - 2, 0)], self.p[min(i + 2, len(self.p) - 1)]
            d = b - a
            n = np.linalg.norm(d)
            t[i] = d / n if n > 1e-9 else (t[i - 1] if i else np.array([1.0, 0.0]))
        self.t = t

    def at(self, s):
        s = min(max(s, 0.0), self.length)
        i = int(np.searchsorted(self.cum, s, side="right") - 1)
        i = min(max(i, 0), len(self.p) - 2)
        f = (s - self.cum[i]) / max(self.cum[i + 1] - self.cum[i], 1e-9)
        pos = self.p[i] + (self.p[i + 1] - self.p[i]) * f
        tan = self.t[i] * (1 - f) + self.t[i + 1] * f
        tan /= max(np.linalg.norm(tan), 1e-9)
        return pos, tan


    def project(self, xy, lo, hi):
        """xy に一番近い経路の上の点の s（lo〜hi の範囲で探す）。"""
        i0 = max(int(np.searchsorted(self.cum, lo, side="right")) - 2, 0)
        i1 = min(int(np.searchsorted(self.cum, hi, side="right")) + 1, len(self.p) - 1)
        a, b = self.p[i0:i1], self.p[i0 + 1:i1 + 1]
        if len(a) == 0:
            return min(max(lo, 0.0), self.length)
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(1), 1e-12)
        u = np.clip(((np.asarray(xy) - a) * ab).sum(1) / L2, 0.0, 1.0)
        d2 = ((np.asarray(xy) - (a + ab * u[:, None])) ** 2).sum(1)
        k = int(np.argmin(d2))
        return float(self.cum[i0 + k] + u[k] * math.sqrt(L2[k]))


class Meet:
    def __init__(self, members):
        self.members = set(members)
        self.arrived = set()
        self.done = False


class Agent:
    def __init__(self, name, plan, t0, speed, l_pref, group=None, info=None):
        self.name, self.plan, self.t0, self.speed, self.l_pref, self.group = name, list(plan), t0, speed, l_pref, group
        self.info = dict(info or {})  # 人物モデル・種類・流れなど（正解に書く）
        self.k = -1
        self.mode = "pending"
        self.path, self.s, self.l = None, 0.0, l_pref
        self.until, self.state, self.spot, self.until_zone = 0.0, None, None, None
        self.frames, self.states, self.events = [], [], {}
        self.yaw, self.dir = None, None
        self.base_yaw, self.glance, self.next_glance, self.glance_i = None, 0.0, 0.0, 0
        self.rng = random.Random(name)
        self.taper = False
        self.lane, self.gate_dir, self.gate_slot = None, None, None
        self.wait_glance, self.requeue = 0.0, False
        self.xy, self.no_walls = None, False  # 歩く人の位置（motion_model "cfsm"）、壁を見ない歩き（歩ける所の外との行き来）
        self.blocker, self.walk_state = None, None  # 前でふさいでいる人、列の後ろで止まる前の状態（motion_model "cfsm"）
        self.nudge_by = None  # 道をあけるように頼んだ人（その人が近くで止まっている間は、元の場所へ戻らない）
        # 部品（components.py）: 今の部品の段取り、着いたら呼ぶ関数、段取りを終えるときに呼ぶ関数、放されるまで待つ、取った席、座っているか、座ったコマの区間
        self.comp, self.on_arrive, self.on_done, self.hold, self.seat, self.sitting, self.sit_spans = None, None, None, False, None, False, []
        # 決まった軌跡どおりに動く間（座る・立つ動作、components.play）、座る動作の途中で放されたときに座り終えてから呼ぶ関数
        self.script, self.leave_after, self.room_wait = None, None, False  # room_wait: 部屋の中の点で扉が閉じる・開くのを待つ間


class Lane:
    def __init__(self, gate, k, center):
        self.gate, self.k, self.center = gate, k, np.asarray(center, float)
        self.queue = []
        self.free_at = -1e9
        self.qpaths = {}  # 向き（+1 入館・−1 退館）→ 列の並ぶ線


class Gate:
    def __init__(self, name, spec, service_s, rng=None):
        (x0, y0), (x1, y1) = spec["line"]
        n = int(spec.get("lanes", 1))
        self.name, self.service_s = name, service_s  # 秒か分布（dists の書き方）
        self.rng = rng or random.Random(name)
        self.in_dir = np.asarray(spec.get("in_dir", [0.0, -1.0]), float)
        self.in_dir /= np.linalg.norm(self.in_dir)
        self.lanes = [Lane(self, k, (x0 + (x1 - x0) * (k + 0.5) / n, y0 + (y1 - y0) * (k + 0.5) / n)) for k in range(n)]
        self.lanes_in = [self.lanes[k] for k in spec.get("lanes_in", range(n))]  # 入館に使うレーン（既定はすべて）
        self.lanes_out = [self.lanes[k] for k in spec.get("lanes_out", range(n))]

    def next_service(self):
        return max(0.3, float(dists.sample(self.service_s, self.rng)))


class Car:
    def __init__(self, name, door, inside, capacity, depth_m=0.0):
        """door: 扉の点、inside: 扉からかごの向き（space.yaml の face）、depth_m: 乗る人が扉からかごの中へ歩く距離（0 なら扉で消える）。"""
        self.name, self.door, self.inside, self.capacity = name, tuple(door), tuple(inside), capacity
        d = np.subtract(inside, door)
        d = d / max(float(np.hypot(*d)), 1e-9)
        self.depth_m = float(depth_m)
        self.cabin = tuple(np.asarray(door, float) + d * self.depth_m)  # 乗る人が消え、降りる人が現れる所
        self.arrivals = []


def tie_side(name):
    """真正面の人をどちら側へよけるか。hash() は実行ごとに変わるので、同じ種で同じ結果になるように crc32 で決める。"""
    return 1.0 if zlib.crc32(name.encode()) % 2 else -1.0


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def _no_fold(pts, short=1.0):
    """折れ線の、短い（short m 未満の）行って戻る折り返しを取り除く（つないだ経路の継ぎ目で後ろへ戻る点）。"""
    out = list(pts)
    i = 1
    while i < len(out) - 1:
        a, b, c = (np.asarray(out[k], float) for k in (i - 1, i, i + 1))
        u, v = b - a, c - b
        if float(u @ v) < 0 and min(float(np.hypot(*u)), float(np.hypot(*v))) < short:
            del out[i]
            i = max(1, i - 1)
        else:
            i += 1
    return out


class Sim(ComponentsMixin):
    """sim = Sim(space, fps, total_frames, gates, cars, spots); sim.add(agent); sim.run()。
    services・rooms・seatsets は部品（components.py の Service・Room・SeatSet、名前 → 物）。
    on_arrival(sim, car, t) は EV が着いたときに呼ばれ、降りる人を足すのに使う（scenario.py が入れる）。
    elevator_policy(sim, t) は毎秒呼ばれ、EV の到着を足してよい（運行の最適化を差し込む所）。"""

    def __init__(self, space, fps, total_frames, gates=None, cars=None, spots=None, lmax=0.6, on_arrival=None, elevator_policy=None,
                 speed_density=None, ev_timing=None, motion_model="cfsm", cfsm=None, group_lateral_m=None, services=None, rooms=None, seatsets=None):
        self.space, self.fps, self.total, self.dt = space, fps, total_frames, 1.0 / fps
        if motion_model not in ("cfsm", "lane"):
            raise ValueError(f"motion_model は cfsm か lane（今は {motion_model!r}）")
        self.model = motion_model
        bad = set(cfsm or {}) - set(CFSM)
        if bad:
            raise ValueError(f"people.cfsm に知らないキー {sorted(bad)}（使えるのは {sorted(CFSM)}）")
        self.C = {**CFSM, **(cfsm or {})}
        self.squeezes = 0  # 安全弁を使った回数（summary.json の motion）
        self.lane_swaps = 0  # ゲートの手前で、ふさぎ合った 2 人の列の順・レーンを入れ替えた回数（swap_crossing、summary.json の motion）
        self.entry_alt = 0  # 入る人の線がふさがっていて、出る人の線から入った人数（try_enter、summary.json の motion）
        gy, gx = np.gradient(space.clear)  # 壁から離れる向き（歩ける所の格子の、壁からの距離の傾き）
        self.wall_n = (gx, gy)
        self.gates = gates or {}
        self.cars = cars or []
        self.spots = [tuple(s) for s in (spots or [])]
        self.free = [True] * len(self.spots)
        self.queue = []
        self.lmax = lmax
        self.agents, self.by_name, self.here = [], {}, {}
        self.group_t0 = {}  # グループの最初の人の現れる時刻（add、入口で待つ順）
        self.on_arrival, self.elevator_policy = on_arrival, elevator_policy
        self.ev_events, self.gate_events = [], []
        self.t = 0.0
        self.alloc = {}  # 止まる人の立つ場所（名前 → (x, y)）。同じ点に何人も立たないように割り当てる
        self.sd = dict(speed_density) if speed_density else None  # {v0, gamma, rho_max, radius}
        if self.sd:
            self.sd.setdefault("radius", 1.5)
            self.sd_area = 0.5 * math.pi * self.sd["radius"] ** 2
        self.ev_timing = ev_timing or {"door_open_s": 0.5, "transfer_s": 0.0}
        # グループ（1.2）: 名前 → {members: [仲間の名前、現れた順], relation: 関係, leader: 先導の人}。組み方は毎コマ formation に
        self.group_info, self.group_rho, self.formation = {}, {}, {}
        c = FORM_RHO_CELL_M
        self.occ0 = (space.x0, space.y0)
        self.occ = np.zeros((int(math.ceil(space.nx * space.res / c)) + 1, int(math.ceil(space.ny * space.res / c)) + 1))  # [x, y] のセルの人数（ならした値）
        self.services, self.rooms, self.seatsets = dict(services or {}), dict(rooms or {}), dict(seatsets or {})
        self.group_lateral_m = group_lateral_m  # 設定の people.group_lateral_m（2 人連れの横を関係によらずこの値に。なければ関係ごとの文献の値）
        self.links = (np.zeros((0, 2)), np.zeros((0, 2)), [])  # 知らない人がよける、仲間どうしを結ぶ線（始まり、終わり、グループ）

    def add(self, a):
        # 入口で待つ順（try_enter）: 着いた順。グループは最初の人の時刻でまとめる（同行者 companion は別に来る）
        g = a.group if a.group is not None and a.info.get("role") != "companion" else None
        first = self.group_t0.setdefault(g, a.t0) if g is not None else a.t0
        a.entry_key = (min(first, a.t0), a.t0, len(self.agents))
        self.agents.append(a)
        self.by_name[a.name] = a
        if a.group is not None:
            gi = self.group_info.setdefault(a.group, {"members": [], "relation": None, "leader": None})
            gi["members"].append(a.name)
            gi["relation"] = gi["relation"] or a.info.get("relation")
            if gi["leader"] is None and a.info.get("role") != "companion":
                gi["leader"] = a.name

    # ---- 位置 ----
    def pos(self, a):
        p, t = a.path.at(a.s)
        l = a.l * min(1.0, max(0.0, a.path.length - a.s)) if a.taper else a.l
        nrm = np.array([-t[1], t[0]])
        q = p + nrm * l
        for _ in range(3):  # 壁にめり込むなら横のずれを縮める
            if self.space.walkable(q[0], q[1]):
                break
            l *= 0.5
            q = p + nrm * l
        else:
            q = p
        return q, t

    def where(self, a):
        if a.mode in ("walk", "to_spot", "board", "to_gate", "gate_pass"):
            if self.model == "cfsm":
                if a.xy is None:  # 現れたとき: 経路の始めに、横のずれを付けて置く
                    a.xy = np.asarray(self.pos(a)[0], float)
                return a.xy, a.path.at(a.s)[1]
            return self.pos(a)
        y = math.radians(a.yaw or 0.0)
        return self.here[a.name], np.array([math.cos(y), math.sin(y)])

    # ---- EV 待ちの場所 ----
    def door_d(self, i):
        return min(math.hypot(self.spots[i][0] - c.door[0], self.spots[i][1] - c.door[1]) for c in self.cars) if self.cars else 0.0

    def door_clear(self, xy):
        """motion_model "cfsm": 待つ場所に使ってよいか（EV の扉から DOOR_CLEAR_M 以上。降りる人のために扉の前をあける。
        扉に近い順に待つ場所を選ぶので、扉の正面がふさがり、降りる人がかごから出られなかった、2026-11-05）。"""
        if self.model != "cfsm":
            return True
        for c in self.cars:
            rel = np.subtract(xy, c.door)
            if float(np.hypot(*rel)) < DOOR_CLEAR_M:
                return False
            out = np.subtract(c.door, c.inside)
            out = out / max(float(np.hypot(*out)), 1e-9)
            along, side = float(rel @ out), abs(float(rel @ np.array([-out[1], out[0]])))
            if 0.0 <= along <= AISLE_M[0] and side < AISLE_M[1] / 2:  # 扉から外へまっすぐの通り道（降りる人の通路）
                return False
        return True

    def pick_spot(self, p, a=None):
        cand = [i for i, ok in enumerate(self.free) if ok and self.door_clear(self.spots[i])]
        if not cand:
            return None
        if a is not None and a.group is not None and self.model == "cfsm":
            # グループの仲間がもう待つ場所を取っていれば、その隣（MATE_SPOT_M 以内）の空いた所（仲間がそれぞれ扉に近い所を選び、
            # 3 m 以上離れて 50 秒待った、hospital_gate_ev の種 7、2026-11-12）
            # 仲間のうち、列で自分より先の人（列にまだ入っていない、待つ場所へ歩く途中の人も）の場所。列の先の人は扉に近い所へ詰め、後の人はその隣へ
            ahead = self.queue[:self.queue.index(a)] if a in self.queue else self.queue
            mine = [self.spots[b.spot] for b in self.agents if b is not a and b.group == a.group and b.spot is not None
                    and (b in ahead or (b.mode == "to_spot" and b not in self.queue))]
            near = [k for k in cand if any(math.hypot(self.spots[k][0] - q[0], self.spots[k][1] - q[1]) <= MATE_SPOT_M for q in mine)]
            if near:
                return min(near, key=lambda k: min(math.hypot(self.spots[k][0] - q[0], self.spots[k][1] - q[1]) for q in mine))
        return min(cand, key=lambda k: self.door_d(k) + 0.3 * math.hypot(self.spots[k][0] - p[0], self.spots[k][1] - p[1]))

    def overflow_spot(self, a, p, gap=0.6):
        """待つ場所が埋まったとき: p の近くで、待っている人・立っている人から gap m 以上離れた、歩ける所（壁から 0.2 m）。
        前は p にそのまま立たせていて、混むと何人も同じ所に重なった。見つからなければ半径を広げ、それでもなければ p。"""
        others = [xy for k, xy in self.alloc.items() if k != a.name] + [self.spots[i] for i, ok in enumerate(self.free) if not ok]
        px, py = float(p[0]), float(p[1])
        for r in (0.0, 0.6, 1.0, 1.4, 1.8, 2.3, 2.9, 3.6, 4.4):
            n = max(1, int(2 * math.pi * r / 0.5))
            off = a.rng.random() * 2 * math.pi
            ring = [(px + r * math.cos(off + 2 * math.pi * k / n), py + r * math.sin(off + 2 * math.pi * k / n)) for k in range(n)]
            ok = [(x, y) for x, y in ring if self.space.walkable(x, y) and self.space.clearance(x, y) >= 0.2 and self.door_clear((x, y))
                  and all(math.hypot(x - ox, y - oy) >= gap for ox, oy in others)
                  and (self.model != "cfsm" or r == 0.0 or self.space.los((px, py), (x, y), 0.0))]
            if ok:  # 同じ半径なら扉に近い所
                xy = min(ok, key=lambda q: math.hypot(*np.subtract(self.nearest_door(q), q)))
                self.alloc[a.name] = xy
                return xy
        self.alloc[a.name] = (px, py)
        return (px, py)

    def nearest_door(self, p):
        if not self.cars:
            return p
        return min((c.door for c in self.cars), key=lambda d: math.hypot(d[0] - p[0], d[1] - p[1]))

    # ---- 立つ場所 ----
    def alloc_stand(self, a, target, gap=0.65):
        """target に近く、ほかの人の立つ場所から gap m 以上離れた、歩ける所（壁から 0.2 m）で、target から見通せる所を割り当てる
        （見通しを見ないと、受付の机の向こう側に立つ場所を取り、仲間と逆向きに歩き出した、hospital_gate_ev の種 7、2026-11-12）。"""
        others = [xy for k, xy in self.alloc.items() if k != a.name]
        tx, ty = float(target[0]), float(target[1])
        cands = [(tx, ty)]
        for r in (0.7, 1.2, 1.7, 2.3):
            n = int(2 * math.pi * r / 0.6)
            off = a.rng.random() * 2 * math.pi
            cands += [(tx + r * math.cos(off + 2 * math.pi * k / n), ty + r * math.sin(off + 2 * math.pi * k / n)) for k in range(n)]
        for x, y in cands:
            if not self.space.walkable(x, y) or self.space.clearance(x, y) < 0.2:
                continue
            if self.model == "cfsm" and (x, y) != (tx, ty) and not self.space.los((tx, ty), (x, y), 0.0):
                continue
            if all(math.hypot(x - ox, y - oy) >= gap for ox, oy in others):
                self.alloc[a.name] = (x, y)
                return (x, y)
        self.alloc[a.name] = (tx, ty)
        return (tx, ty)

    # ---- 段取り ----
    def face(self, a, t, p, q, glance):
        a.base_yaw = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) if q is not None else (a.yaw if a.yaw is not None else 0.0)
        a.glance, a.glance_i = glance, 0
        a.next_glance = t + a.rng.uniform(2.0, 4.0)

    def stand(self, a, t, p, state, q=None, glance=0.0):
        self.here[a.name] = np.asarray(p, float)
        a.nudge_home = None  # 新しく立った所が戻る所
        a.stand_xy = self.here[a.name].copy()
        a.xy = self.here[a.name].copy()  # 歩き出すときはここから
        a.state = state
        self.face(a, t, p, q, glance)

    def _path(self, pts):
        return Path(pts)

    def walk_to(self, a, p, target, state, mode="walk", taper=False, l0=None):
        a.path = Path(self.space.route(tuple(p), tuple(target)))
        a.s, a.mode, a.state, a.taper = 0.0, mode, state, taper
        a.no_walls, a.direct = False, False
        a.l = a.l_pref if l0 is None else l0

    def next_step(self, a, t, p):
        if a.on_done is not None:  # 部品の段取りの後始末（窓口の応対の場所を空けるなど）
            fn, a.on_done = a.on_done, None
            fn()
        a.on_arrive, a.hold, a.comp, a.direct = None, False, None, False
        if 0 <= a.k < len(a.plan) and a.plan[a.k][0] in ("stop", "meet", "regroup", "service", "room", "seat"):
            self.alloc.pop(a.name, None)  # 止まり終えたので立つ場所を空ける
            a.regroup = None
        a.k += 1
        a.until_zone = None
        if a.k >= len(a.plan):
            a.mode = "done"
            a.events["end"] = round(t, 2)
            return
        step = a.plan[a.k]
        kind = step[0]
        nxt = a.plan[a.k + 1][0] if a.k + 1 < len(a.plan) else None
        if kind == "straight":  # 歩ける所の外（扉の向こう・EV のかごの中）との行き来は、経路を探さずまっすぐ歩く
            a.path = Path([tuple(map(float, p)), tuple(map(float, step[1]))])
            a.s, a.mode, a.state, a.taper, a.l = 0.0, "walk", step[2], True, 0.0
            a.no_walls = True
            a.until_zone = None
        elif kind == "walk":
            opts = step[3] if len(step) > 3 else {}
            target = self.alloc_stand(a, step[1]) if nxt in ("stop", "meet", "regroup") else step[1]
            self.walk_to(a, p, target, step[2], taper=nxt in ("stop", "meet", "regroup"), l0=a.l_pref if a.k == 0 else 0.0)
            self._join_leader_path(a, p, step, target)
            a.until_zone = opts.get("until_zone")
        elif kind == "gate":
            g = self.gates[step[1]]
            d = 1.0 if float((g.lanes[0].center - np.asarray(p)) @ g.in_dir) > 0 else -1.0  # 入館の向きに進むか
            a.gate_dir = g.in_dir * d
            lanes = g.lanes_in if d > 0 else g.lanes_out
            lane = min(lanes, key=lambda ln: (len(ln.queue), float(np.linalg.norm(ln.center - p))))
            if a.group is not None and self.model == "cfsm":  # 仲間が並ぶレーンがあり、列がいちばん短い列より GROUP_LANE_EXTRA 人までの長さなら、そこに並ぶ
                mates = [ln for ln in lanes if any(b.group == a.group for b in ln.queue)]
                if mates:
                    ml = min(mates, key=lambda ln: len(ln.queue))
                    if len(ml.queue) <= len(lane.queue) + GROUP_LANE_EXTRA:
                        lane = ml
            lane.queue.append(a)
            a.lane = lane
            a.events.setdefault("gate_join", []).append(round(t, 2))  # 列に加わった時刻（ここから通るまでは列の歩き）
            self.retarget_gate(a, t, p, len(lane.queue) - 1)
        elif kind == "stop":
            a.mode, a.until = "stop", t + step[1]
            self.stand(a, t, p, step[3], step[2], step[4])
            a.events.setdefault("stops", []).append([round(t, 2), round(t + step[1], 2), step[3]])
        elif kind in ("service", "room", "seat"):  # 部品（components.py）
            self.comp_step(a, t, p, step)
        elif kind == "regroup":  # ゲートの先で、まだ通っていない仲間を待つ（step[1] はゲートの段取り、step[2] は最長の秒数）
            a.mode, a.until, a.regroup = "stop", t + step[2], step[1]
            self.stand(a, t, p, "group_wait", tuple(np.asarray(p) - a.gate_dir) if a.gate_dir is not None else None, 30.0)
            a.events.setdefault("regroup", []).append([round(t, 2), None])
        elif kind == "meet":
            a.mode = "meet"
            self.stand(a, t, p, step[3], step[2], step[4])
            step[1].arrived.add(a.name)
            a.events["meet_start"] = round(t, 2)
        elif kind == "wait_ev":
            a.events["hall"] = round(t, 2)
            i = self.pick_spot(p, a)
            a.wait_glance = step[1]
            if i is None:  # 待つ場所が埋まっている: ほかの人から離れた所まで歩いてから待つ（着くと to_spot の扱いで列に入る）
                a.spot = None
                self.walk_to(a, p, self.overflow_spot(a, p), "ev_approach", mode="to_spot", taper=True, l0=0.0)
            else:
                self.free[i] = False
                a.spot = i
                self.walk_to(a, p, self.spots[i], "ev_approach", mode="to_spot", taper=True, l0=0.0)
        elif kind == "exit":
            a.mode = "done"
            a.events["end"] = round(t, 2)
            self.alloc.pop(a.name, None)

    def queue_slot(self, a, k):
        """列の k 番目の場所。レーンの手前 0.7 m からまっすぐ戻り（6 m まで、壁から 0.3 m）、その先は来た方への経路の上に QUEUE_GAP（0.65 m）おき。
        経路の部分はレーンごとに横へずらす（列が壁の向こうへ伸びたり、二つの列が重なったりしないように）。"""
        lane, d = a.lane, a.gate_dir
        key = 1 if float(d @ lane.gate.in_dir) > 0 else -1
        qp = lane.qpaths.get(key)
        if qp is None:
            start = lane.center - d * 0.7
            q = start.copy()
            for _ in range(24):
                n = q - d * 0.25
                if not self.space.walkable(*n) or self.space.clearance(*n) < 0.3:
                    break
                q = n
            pts = [tuple(start), tuple(q)]
            far = a.info.get("origin_xy")
            if far is not None:
                try:
                    pts += [tuple(x) for x in self.space.route(tuple(q), tuple(far))[1:]]
                except ValueError:
                    pass
            qp = Path(pts)
            qp.straight = float(np.linalg.norm(q - start))
            lanes = lane.gate.lanes_in if key > 0 else lane.gate.lanes_out
            qp.off = (lanes.index(lane) - (len(lanes) - 1) / 2) * QUEUE_LANE_OFF if lane in lanes else 0.0
            lane.qpaths[key] = qp
        s = QUEUE_GAP * k
        pos, tan = qp.at(s)
        if s > qp.straight and qp.off:
            nrm = np.array([-tan[1], tan[0]])
            for off in (qp.off, qp.off / 2):
                cand = pos + nrm * off
                if self.space.walkable(*cand) and self.space.clearance(*cand) >= 0.2:
                    return cand
        return pos

    def retarget_gate(self, a, t, p, k):
        """列の k 番目の場所（queue_slot）へ歩く。"""
        slot = self.queue_slot(a, k)
        a.gate_slot = k
        if math.hypot(slot[0] - p[0], slot[1] - p[1]) < 0.15:
            a.mode = "gate_wait"
            self.stand(a, t, p, "gate_queue", tuple(a.lane.center + a.gate_dir), 0.0)
            return
        near = math.hypot(slot[0] - p[0], slot[1] - p[1]) < 3.0
        a.path = Path([tuple(p), tuple(slot)]) if a.mode in ("gate_wait", "to_gate") and near else Path(self.space.route(tuple(p), tuple(slot)))
        a.s, a.mode, a.state, a.taper = 0.0, "to_gate", "pass", True
        a.l = 0.0 if k < 3 else a.l

    def reorder_lane(self, lane, t):
        """motion_model "cfsm": 列の順を、ゲートに近い順（実際に並んでいる順）にする。並んだ順のままだと、後から来た人が先に列に立ったとき、
        前の順の人がその人を通り抜けられず自分の場所に着けず、先頭が来ないので列が止まった（verify_gate_capacity、2026-11-05）。"""
        if len(lane.queue) < 2 or t < getattr(lane, "next_sort", 0.0):
            return
        lane.next_sort = t + 0.5
        d = [float(np.hypot(*(self.where(b)[0] - lane.center))) for b in lane.queue]
        order = sorted(range(len(lane.queue)), key=lambda k: d[k])
        if all(d[order[k]] >= d[order[k - 1]] for k in range(1, len(order))) and order == list(range(len(order))):
            return
        if all(abs(d[order[k]] - d[k]) < 0.3 for k in range(len(order))):  # ほとんど同じ距離なら並べ替えない（行ったり来たりしないように）
            return
        new = [lane.queue[k] for k in order]
        for k, b in enumerate(new):
            if b is not lane.queue[k] and b.mode in ("gate_wait", "to_gate"):
                lane.queue[k] = b
                self.retarget_gate(b, t, self.where(b)[0], k)
        lane.queue[:] = new

    def swap_crossing(self, g, t):
        """motion_model "cfsm": ゲートの列へ向かう人が、列の順で後ろの人にふさがれたら、2 人の順（と違うレーンならレーン）を入れ替える。
        ゲートの手前 2 m は経路の上をまっすぐ歩く（よけない）ので、
        - 隣のレーンへ斜めに向かう 2 人の経路が交わると、2 人とも互いにふさがれて止まり、後ろの列も全部止まった（verify_gate_capacity の種 1、2026-11-06）
        - 先頭の人が、先頭の場所の手前で 2 番目の場所に立った人にふさがれ、そのレーンが 1 分止まった（同じく種 3。ゲートまでの距離がほぼ同じで、
          ゲートに近い順の並べ替え reorder_lane も起きなかった）"""
        for lane in g.lanes:
            for a in list(lane.queue):
                b = getattr(a, "blocker", None)
                if (a.mode != "to_gate" or a not in lane.queue or b is None or getattr(b, "lane", None) is None or b.lane.gate is not g
                        or b not in b.lane.queue or float(a.gate_dir @ b.gate_dir) <= 0
                        or t < getattr(a, "swap_t", -1.0) or t < getattr(b, "swap_t", -1.0)):
                    continue
                la, lb = lane, b.lane
                ka, kb = la.queue.index(a), lb.queue.index(b)
                if la is lb:  # 同じレーン: ふさいだ人が列の順で後ろ（互いにふさいでいる横並びの 2 人は、入れ替えても変わらないので入れ替えない）
                    if kb <= ka or b.mode not in ("to_gate", "gate_wait") or (b.mode == "to_gate" and getattr(b, "blocker", None) is a):
                        continue
                elif getattr(b, "blocker", None) is not a or b.mode != "to_gate":  # 違うレーン: 互いにふさいでいる
                    continue
                la.queue[ka], lb.queue[kb] = b, a
                a.lane, b.lane = lb, la
                a.swap_t = b.swap_t = t + 1.0  # 入れ替えたすぐ後は、もう一度は入れ替えない
                self.lane_swaps += 1
                for c, k in ((a, kb), (b, ka)):
                    self.retarget_gate(c, t, self.where(c)[0], k)

    def step_gates(self, t):
        for g in self.gates.values():
            if self.model == "cfsm":
                self.swap_crossing(g, t)
            for lane in g.lanes:
                if self.model == "cfsm":
                    self.reorder_lane(lane, t)
                if not lane.queue:
                    continue
                head = lane.queue[0]
                if head.mode == "gate_wait" and t >= lane.free_at:
                    p = self.here[head.name]
                    exit_ = lane.center + head.gate_dir * 1.0
                    head.path = Path([tuple(p), tuple(lane.center), tuple(exit_)])
                    head.s, head.mode, head.state, head.taper, head.l = 0.0, "gate_pass", "pass", False, 0.0
                    lane.free_at = t + g.next_service()
                    lane.queue.pop(0)
                    self.gate_events.append({"t": round(t, 2), "gate": g.name, "lane": lane.k, "person": head.name,
                                             "dir": "in" if float(head.gate_dir @ g.in_dir) > 0 else "out"})
                    head.events.setdefault("gate", []).append(round(t, 2))
                    for k, b in enumerate(lane.queue):
                        if b.mode in ("gate_wait", "to_gate"):
                            q, _ = self.where(b)
                            self.retarget_gate(b, t, q, k)

    def step_elevators(self, f, t):
        for car in self.cars:
            if f not in car._frames:
                continue
            alighted = self.on_arrival(self, car, t) if self.on_arrival else []
            door_open, tp = self.ev_timing["door_open_s"], self.ev_timing["transfer_s"]
            boarded = []
            for k, a in enumerate(self.board_order(car.capacity, t)):  # 降りる人のあとに、並んだ順に 1 人 tp 秒ずつ
                p, _ = self.where(a)
                self.here[a.name] = np.asarray(p, float)  # 詰めている途中なら、その場で待つ
                a.nudge_home = None
                a.mode, a.until, a.board_car = "board_wait", t + door_open + tp * (len(alighted) + k), car
                a.board_side = 1.0 if k % 2 == 0 else -1.0
                a.events["car"] = car.name
                boarded.append(a.name)
            self.queue = [a for a in self.queue if a.name not in boarded]
            for a in self.queue:  # 残った人は扉に近い空いた場所へ詰める
                p, _ = self.where(a)
                i = self.pick_spot(p, a)
                if i is None:
                    continue
                if a.spot is not None:
                    mates = [self.spots[b.spot] for b in self.queue[:self.queue.index(a)] if b.group is not None and b.group == a.group and b.spot is not None]
                    if mates:  # 仲間の隣へ（仲間が詰めたら、ついていく）
                        def gap(k, mates=mates):
                            return min(math.hypot(self.spots[k][0] - q[0], self.spots[k][1] - q[1]) for q in mates)
                        if gap(i) >= gap(a.spot) - 0.3:
                            continue
                    elif self.door_d(i) > self.door_d(a.spot) - 0.5:
                        continue
                if a.spot is not None:
                    self.free[a.spot] = True
                self.alloc.pop(a.name, None)  # あふれて立っていた所を空ける
                self.free[i] = False
                a.spot = i
                self.walk_to(a, p, self.spots[i], "ev_wait", mode="to_spot", taper=True, l0=0.0)
                a.requeue = True
            self.ev_events.append({"t": round(t, 2), "car": car.name, "boarded": boarded, "alighted": alighted})

    def board_order(self, capacity, t):
        """着いたかごに乗る人（並んだ順に定員まで）。グループは一緒に乗る（motion_model "cfsm"）: 全員が乗れなければ一緒に次を待ち、
        後ろの人が先に乗る。まだ待つ場所に来ていない仲間がいれば、待ち始めてから GROUP_EV_WAIT_S 秒までは乗らずに待つ。"""
        if self.model != "cfsm":
            return self.queue[:capacity]
        out, seen = [], set()
        # 定員で一度見送ったグループは、次のかごでは列の前に回す（見送るたびに後ろの 1 人の人が先に乗り、3 人組が 40 秒以上待った、
        # hospital_gate_ev の種 12、2026-11-12）
        order = sorted(self.queue, key=lambda b: not getattr(b, "ev_skipped", False))
        for a in order:
            if len(out) >= capacity:
                break
            if a.name in seen:
                continue
            if a.group is None:
                out.append(a)
                seen.add(a.name)
                continue
            mates = [b for b in self.queue if b.group == a.group]
            seen.update(b.name for b in mates)
            step = a.plan[a.k] if 0 <= a.k < len(a.plan) else None
            coming = any(b.mode not in ("done", "board", "board_wait") and b not in mates
                         and any(b.plan[j] is step for j in range(max(b.k, 0), len(b.plan)))
                         for b in (self.by_name[n] for n in self.group_info.get(a.group, {}).get("members", ())))
            if coming and t - a.events.get("wait_start", t) < GROUP_EV_WAIT_S:
                continue
            if len(out) + len(mates) <= capacity:
                out += mates
            elif len(mates) > capacity:  # 1 台に入りきらないグループは、入るだけ乗る
                out += mates[:capacity - len(out)]
            else:
                for b in mates:
                    b.ev_skipped = True
        return out

    def try_enter(self, a, t, busy, held):
        """現れてよいか。入口ごとに着いた順（グループはまとめて、entry_key）で、前に待つ人がいれば後ろの人も待つ
        （前は待つ人が 0.2 秒ごとにしか確かめず、あとから着いた人が空いた一瞬を取って、2 人連れの 2 人目が外で 47 秒待った、2026-11-06）。
        扉の向こうから入る人（最初の段取りが straight、motion_model "cfsm"）は、入った先（扉の点）の ENTRY_CLEAR_M 以内に人がいても待つ
        （列の後ろが入口まで伸びると、入る人が列に割り込んで重なった、2026-11-05）。入る人の線がふさがっていれば、出る人の線（entry_alt）を、
        そこを出ていく人が近くにいないときだけ使う（1 本の線では 1 分に 58 人しか入れず、75 人/分を入れる確かめで外に人がたまった）。"""
        o = a.info["origin_xy"]
        key = getattr(a, "door", None) or (round(o[0], 2), round(o[1], 2))
        if key in held:
            return False
        e = a.plan[0][1] if self.model == "cfsm" and a.plan and a.plan[0][0] == "straight" else None

        def clear(o, e):
            # グループの仲間も、現れる点の MATE_SPAWN_M 以内にいれば待つ（同じコマに同じ点に現れた 2 人の 1 人が押し出され、扉の柱の外へ回り込んだ、
            # office_gate_ev、2026-11-06。前は出発の時刻が 0〜0.4 秒ずれていて、たいてい離れて現れた）
            for q, g in busy:
                mate = g is not None and g == a.group
                if math.hypot(q[0] - o[0], q[1] - o[1]) < (MATE_SPAWN_M if mate else 0.5):
                    return False
                if not mate and e is not None and math.hypot(q[0] - e[0], q[1] - e[1]) < ENTRY_CLEAR_M:
                    return False
            return True
        alt = getattr(a, "entry_alt", None)
        usable = e is not None and alt is not None
        if usable and a.group is not None and any(g == a.group and math.hypot(q[0] - o[0], q[1] - o[1]) < 1.0 for q, g in busy):
            # 仲間が入る人の線から入ったところ: 横の線が空いていれば、並んで入る（同じ線で前後に入ると、廊下でも縦に並んだまま歩き、
            # 2 人連れの間隔が 1.0 m を超えた、verify_gate_capacity、2026-11-06）
            if clear(*alt) and not self.leaving_near(*alt):
                return self._use_alt(a, alt)
        if clear(o, e):
            return True
        if usable and clear(*alt) and not self.leaving_near(*alt):
            return self._use_alt(a, alt)
        held.add(key)
        return False

    def _use_alt(self, a, alt):
        """出る人の線（entry_alt）から入る。"""
        a.info["origin_xy"] = tuple(alt[0])
        a.plan[0] = ("straight", tuple(alt[1])) + tuple(a.plan[0][2:])
        self.entry_alt += 1
        return True

    def leaving_near(self, o, e, r=LEAVE_LOOK_M):
        """扉の向こうの点 o へ出ていく途中の人（今かその次の段取りが o への straight）が、扉の点 e から r 以内にいるか。"""
        for b in self.agents:
            if b.mode in ("pending", "done"):
                continue
            for j in (b.k, b.k + 1):
                if 0 <= j < len(b.plan) and b.plan[j][0] == "straight" and math.hypot(b.plan[j][1][0] - o[0], b.plan[j][1][1] - o[1]) < 0.05:
                    q = self.where(b)[0]
                    if math.hypot(q[0] - e[0], q[1] - e[1]) < r:
                        return True
        return False

    def run(self):
        for car in self.cars:
            car._frames = {int(round(x * self.fps)) for x in car.arrivals}
        for f in range(self.total):
            t = f * self.dt
            self.t = t
            if self.elevator_policy and f % self.fps == 0:
                before = {c.name: len(c.arrivals) for c in self.cars}
                self.elevator_policy(self, t)
                for c in self.cars:
                    if len(c.arrivals) != before[c.name]:
                        c._frames = {int(round(x * self.fps)) for x in c.arrivals}
            due = [a for a in self.agents if a.mode == "pending" and t >= a.t0]
            if due:
                busy = [(self.where(b)[0], b.group) for b in self.agents if b.mode not in ("pending", "done")]
                due.sort(key=lambda a: a.entry_key)
                held = set()
            for a in due:
                if self.try_enter(a, t, busy, held):
                    a.events["start"] = round(t, 2)
                    self.next_step(a, t, a.info["origin_xy"])
                    busy.append((np.asarray(a.info["origin_xy"], float), a.group))
                else:  # 現れる場所がふさがっていれば、空くまで外で待つ（待った秒を記録）
                    a.events["spawn_wait_s"] = round(a.events.get("spawn_wait_s", 0.0) + self.dt, 2)
            self.step_elevators(f, t)
            self.step_gates(t)
            if self.services or self.rooms:
                self.step_components(t)
            self.step_away(f, t)
            self.step_agents(f, t)
        return self

    def queue_state(self, a, step):
        """列の後ろでふさがれて止まっている人の状態を「列に並ぶ」（gate_queue）にする（動き出したら元に戻す）。
        ゲートへ向かう人（今の段取りが to_gate か、次の段取りがゲート）で、前でふさいでいる人が列に並んでいる人のとき。"""
        b = getattr(a, "blocker", None)
        heading = a.mode == "to_gate" or (a.k + 1 < len(a.plan) and a.plan[a.k + 1][0] == "gate")
        queued = b is not None and (b.state == "gate_queue" or b.mode in ("gate_wait", "to_gate"))
        if heading and queued and step < 0.1 * self.dt:
            if a.state != "gate_queue":
                a.walk_state, a.state = a.state, "gate_queue"
        elif a.state == "gate_queue" and a.mode != "gate_wait" and getattr(a, "walk_state", None):
            a.state, a.walk_state = a.walk_state, None

    def _can_step(self, p, q):
        """p → q の一歩が歩ける所の中か。格子の角を斜めにすり抜けない（経路の探し方 space.route と同じ決まり。
        すり抜けると、歩ける所の中の離れた区画に入り、経路が見つからなくなった、2026-11-05）。"""
        sp = self.space
        if not sp.walkable(*q):
            return False
        (i0, j0), (i1, j1) = sp.cell(*p), sp.cell(*q)
        di, dj = i1 - i0, j1 - j0
        if abs(di) > 1 or abs(dj) > 1:
            return sp.los(tuple(p), tuple(q), 0.0)
        if di and dj and sp.walkable(*p):
            return bool(sp.grid[i0 + di, j0] and sp.grid[i0, j0 + dj])
        return True

    def mates_behind(self, a, t):
        """グループの仲間が、a と同じ止まる段取り（受付など）にまだ着いていないか、止まっている途中か。先に済んだ人は仲間を待つ
        （着く時刻がずれて終わる時刻もずれ、先に済んだ人が歩き出して、受付へ行く 2 人連れが 10 m 離れて歩いた、hospital_gate_ev、2026-11-06）。"""
        if a.group is None:
            return False
        step = a.plan[a.k]
        for b in self.agents:
            if b is a or b.group != a.group or b.mode == "done":
                continue
            if b.comp is not None and b.comp.get("role") == "follower":  # 部品の段取りで先導の人を待つ仲間（待たせ合わない）
                continue
            for j in range(max(b.k, 0), len(b.plan)):
                if b.plan[j] is step:
                    if j > b.k or b.mode != "stop" or t < b.until:
                        return True
                    break
        return False

    def _join_leader_path(self, a, p, step, target):
        """グループの仲間（先導の人でない人）が、先導の人がもう歩き始めた同じ段取り step を歩き始めるとき、自分で引いた経路の代わりに、
        先導の人の経路の今いる所の先へ合流し、その経路に沿って歩く（終わりだけ自分の行き先へ）（motion_model "cfsm"）。
        仲間がそれぞれ自分の位置から経路を引くと、受付の別々の立ち位置から EV まで、島の反対側を 7 m 離れて 50 秒歩いた
        （hospital_gate_ev の種 7、2026-11-12。持ち場へ寄るのは先導の人から FORM_NEAR の中だけ）。"""
        if self.model != "cfsm" or a.group is None:
            return
        gi = self.group_info.get(a.group)
        if not gi or gi["leader"] in (None, a.name):
            return
        b = self.by_name[gi["leader"]]
        if b.mode != "walk" or b.k < 0 or b.plan[b.k] is not step or b.path is None or b.no_walls:
            return
        lp = b.path
        j = int(np.searchsorted(lp.cum, min(lp.length, b.s + 1.0)))
        if j >= len(lp.p) - 1 or float(np.hypot(*(lp.p[j] - np.asarray(p)))) > 15.0:
            return
        # 合流するのは、先導の人の 1 m 先から先の経路の点のうち、自分にいちばん近い点（先導の人の少し先の点に合流すると、その点が自分より後ろのとき、
        # 経路が後ろへ 0.4 m 戻ってから折り返し、目指す向きが毎コマ入れ替わってその場で 20 分揺れた。office_lunch の種 11、2026-11-16）
        q0 = np.asarray(p, float)
        j = j + int(np.argmin([float(np.hypot(*(lp.p[i] - q0))) for i in range(j, len(lp.p) - 1)]))
        head = self.space.route(tuple(p), tuple(lp.p[j]))
        end = tuple(lp.p[-1])
        tail = [tuple(target)] if math.hypot(end[0] - target[0], end[1] - target[1]) < 0.3 else list(self.space.route(end, tuple(target)))
        pts = _no_fold(list(head) + [tuple(q) for q in lp.p[j + 1:]] + tail[1:])
        if len(pts) >= 2:
            a.path, a.s = Path(pts), 0.0

    def mates_before(self, a, step):
        """グループの仲間で、段取り step（ゲートなど）をまだ済ませていない人がいるか（その段取りの途中の人も入れる）。"""
        if a.group is None:
            return False
        for name in self.group_info.get(a.group, {}).get("members", ()):
            b = self.by_name[name]
            if b is a or b.mode in ("done",):
                continue
            for j in range(max(b.k, 0), len(b.plan)):
                if b.plan[j] is step:
                    return True
        return False

    def reroute_pts(self, p, path):
        """今の位置 p から path の終わりまでの経路の点。終わりが歩ける所の外なら、歩ける所の最後の点まで探し、その先の元の点を足す。"""
        end = path.at(path.length)[0]
        if self.space.walkable(*end):
            return self.space.route(tuple(p), tuple(end))
        ok = [k for k, q in enumerate(path.p) if self.space.walkable(*q)]
        if not ok:
            raise ValueError("経路に歩ける点がない")
        j = ok[-1]
        return list(self.space.route(tuple(p), tuple(path.p[j]))) + [tuple(q) for q in path.p[j + 1:]]

    def respot(self, a, p):
        """EV の待つ場所を、今いる所の近くの空いた所に選び直して歩き出す（motion_model "cfsm"）。"""
        if a.spot is not None:
            self.free[a.spot] = True
            a.spot = None
        self.alloc.pop(a.name, None)
        self.walk_to(a, p, self.overflow_spot(a, p), a.state, mode="to_spot", taper=True, l0=0.0)

    def crowded(self, a, p):
        """p に、グループの仲間以外の人が体の幅（2 × 半径）より近くにいるか。"""
        r2 = 2 * self.C["radius"]
        for b in self.agents:
            if b is a or b.mode in ("pending", "done") or (a.group is not None and b.group == a.group):
                continue
            q = self.where(b)[0]
            if math.hypot(q[0] - p[0], q[1] - p[1]) < r2:
                return True
        return False

    def alighting(self, car):
        """その EV から降りる途中の人（かごの中か、扉から 1 m 以内）がいるか。乗る人と扉ですれ違えず止まった（2026-11-05）。"""
        for b in self.agents:
            if b.info.get("stream") == "alight" and b.info.get("origin") == car.name and b.mode == "walk" and b.xy is not None:
                if not self.space.walkable(*b.xy) or math.hypot(b.xy[0] - car.door[0], b.xy[1] - car.door[1]) < 1.0:
                    return True
        return False

    def _wall(self, p):
        """p から壁までの距離（m、格子の壁からの距離を補ったもの − 格子の半分）と、壁から離れる向き。"""
        sp = self.space
        fi, fj = (p[1] - sp.y0) / sp.res, (p[0] - sp.x0) / sp.res
        i0, j0 = int(math.floor(fi)), int(math.floor(fj))
        if not (0 <= i0 < sp.ny - 1 and 0 <= j0 < sp.nx - 1):
            return 0.0, np.zeros(2)
        u, v = fi - i0, fj - j0
        w = np.array([(1 - u) * (1 - v), (1 - u) * v, u * (1 - v), u * v])

        def bil(g):
            return float(w @ np.array([g[i0, j0], g[i0, j0 + 1], g[i0 + 1, j0], g[i0 + 1, j0 + 1]]))
        c = bil(sp.clear) - sp.res / 2
        n = np.array([bil(self.wall_n[0]), bil(self.wall_n[1])])
        nn = float(np.hypot(*n))
        return c, (n / nn if nn > 1e-9 else np.zeros(2))

    def _update_formation(self, active, P, XY, groups):
        """このコマのグループの組み方（cfsm）。歩いているグループごとに、周りの密度（0.5 m 角のセルの人数を FORM_RHO_TAU でならした値、中心の周り 1.5 m 角）から
        横の広がりの比を出し（Zanlungo ら 2015）、歩いている仲間の持ち場を決める。知らない人がよける、仲間どうしを結ぶ線も作る。"""
        self.formation = {}
        self._taken_xy = [(float(P[id(b)][0][0]), float(P[id(b)][0][1]), b.group) for b in active]
        c, (x0, y0) = FORM_RHO_CELL_M, self.occ0
        k_dt = min(1.0, self.dt / FORM_RHO_TAU)
        self.occ *= 1.0 - k_dt
        if len(XY):
            ix = np.clip(((XY[:, 0] - x0) / c).astype(int), 0, self.occ.shape[0] - 1)
            iy = np.clip(((XY[:, 1] - y0) / c).astype(int), 0, self.occ.shape[1] - 1)
            np.add.at(self.occ, (ix, iy), k_dt)
        for g, mem in groups.items():
            gi = self.group_info.get(g)
            walking = [b for b in mem if b.mode == "walk"]
            if not gi or not walking:
                continue
            order = {n: k for k, n in enumerate(gi["members"])}
            walking.sort(key=lambda b: order.get(b.name, 99))
            cen = np.mean([P[id(b)][0] for b in walking], axis=0)
            i, j = int((cen[0] - x0) / c), int((cen[1] - y0) / c)
            win = self.occ[max(i - 1, 0):i + 2, max(j - 1, 0):j + 2]
            r = float(win.mean()) / (c * c) if win.size else 0.0
            self.group_rho[g] = r
            scale = group_lateral_scale(len(walking), r)
            slots = group_slots(len(walking), gi["relation"], self.group_lateral_m, scale)
            file_ = len(walking) > 1 and all(abs(sl[0]) < 1e-9 for sl in slots)
            # 前後の揺らぎ（先導の人以外。縦 1 列のときは入れない）: 平均 0・標準偏差 sd の Ornstein-Uhlenbeck。2 人連れの前後の差の平均 |y| が
            # 文献の値になるように sd = |y| √(π/2)（半正規分布）。揺らぎなしでは |y| が 0.09 m（文献 0.31〜0.50 m）で、横に並びすぎた
            y_rel = (GROUP_RELATIONS.get(gi["relation"]) or GROUP_RELATIONS["friends"])["dyad"]["y"]
            sd, kk = y_rel * math.sqrt(math.pi / 2), self.dt / FORM_LON_TAU
            out = {}
            for b, (lat, lon) in zip(walking, slots):
                if b.name != gi["leader"] and not file_:
                    b.form_dy = getattr(b, "form_dy", 0.0) * (1 - kk) + sd * math.sqrt(2 * kk) * b.rng.gauss(0.0, 1.0)
                    lon += b.form_dy
                out[b.name] = (lat, lon)
            self.formation[g] = {"slots": out, "rank": {b.name: k for k, b in enumerate(walking)}, "rho": r, "scale": scale}
        la, lb, lg = [], [], []
        by_g = {}
        for b in active:
            if b.group is not None and b.mode in ("walk", "stop", "meet"):
                by_g.setdefault(b.group, []).append(P[id(b)][0])
        for g, pts in by_g.items():
            for u in range(len(pts)):
                for w in range(u + 1, len(pts)):
                    if float(np.hypot(*(pts[w] - pts[u]))) < LINK_M:
                        la.append(pts[u])
                        lb.append(pts[w])
                        lg.append(g)
        for S in self.services.values():  # 窓口の列（components.py）: 前後に並んで待つ人どうしも結ぶ（知らない人が列の間を通り抜けないように。
            # 列の人の間 0.65 m を歩く人がすり抜けて重なった、hospital_outpatient、2026-11-13）
            qs = [P[id(b)][0] for b in S.queue if b.mode == "stop" and id(b) in P]
            for u in range(len(qs) - 1):
                if float(np.hypot(*(qs[u + 1] - qs[u]))) < 1.0:
                    la.append(qs[u])
                    lb.append(qs[u + 1])
                    lg.append(f"queue:{S.name}")
        self.links = (np.array(la, float).reshape(-1, 2), np.array(lb, float).reshape(-1, 2), lg)

    def _link_points(self, a, p):
        """ほかのグループの仲間どうしを結ぶ線の上で、p にいちばん近い点（線の両端の近くは除く。両端は仲間の体そのもの）。→ (p からの向き, 距離)"""
        A, B, G = self.links
        empty = (np.zeros((0, 2)), np.zeros(0))
        if not len(G):
            return empty
        mine = getattr(a, "link_key", None)
        keep = np.array([g != a.group and g != mine for g in G], bool)
        A, B = A[keep], B[keep]
        if not len(A):
            return empty
        AB = B - A
        tt = np.clip(((p - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0.0, 1.0)
        rel = A + tt[:, None] * AB - p
        dist = np.hypot(*rel.T)
        ok = (tt > 0.1) & (tt < 0.9) & (dist < self.C["cutoff"]) & (dist > 1e-9)
        return rel[ok], dist[ok]

    def _form_target(self, a, p, s, L, P):
        """グループの仲間（先導の人でない人）が寄る持ち場の向きと速さ（cfsm）。→ (向き, 速さ) か、寄らないとき None。
        先導の人と同じ段取りを歩いていて、近く（FORM_NEAR）にいて、どちらも行き先の手前（FORM_END_M）でないときだけ。
        持ち場 = 先導の人の位置 + 先導の人の向きに直した（自分の持ち場 − 先導の人の持ち場）。持ち場が壁の中・壁の向こうなら、横を半分に、
        それでも駄目なら先導の人の後ろに縦に並ぶ（通路が狭い所）。速さは、持ち場との前後のずれ 1 m あたり FORM_GAIN m/s 足し引きする
        （自分の速さの 1.3 倍まで）。前は仲間がそれぞれ自分の経路を歩き、2 人連れが 2〜4 m 横に離れて並んで歩いた（validity.md の 5.6）。"""
        g = a.group
        if g is None or a.mode != "walk" or a.no_walls or L - s < FORM_END_M or self.t < getattr(a, "form_off_until", -1.0):
            return None
        if self.t - getattr(a, "best_t", self.t) >= FORM_STALL_S:  # 進めずにいる: しばらく持ち場へ寄らず、自分の経路でよける
            # （混んだ EV の前で、知らない人の立つ所を持ち場として向かい続け、15 秒たって安全弁を使った。hospital_gate_ev で 60 → 104 回、2026-11-12）
            a.form_off_until = self.t + FORM_OFF_S
            return None
        fm = self.formation.get(g)
        gi = self.group_info.get(g)
        if not fm or not gi or a.name not in fm["slots"] or gi["leader"] == a.name or gi["leader"] not in fm["slots"]:
            return None
        b = self.by_name[gi["leader"]]
        if b.mode != "walk" or b.no_walls or b.k < 0 or a.k < 0 or b.plan[b.k] is not a.plan[a.k] or b.path.length - b.s < FORM_END_M:
            return None
        hp = P[id(b)][0]
        if float(np.hypot(*(hp - p))) > FORM_NEAR:
            return None
        # 向きは先導の人の経路の向き（今の所から 1 m 先までの弦）。先導の人の位置から 1 m 先の点への向きにすると、先導の人は経路から横に
        # ずれて歩く（l_pref）ので向きが 15 度ほど傾き、持ち場も回って、2 人連れの横が 0.66 m のところ 0.94 m になった（2026-11-12）
        h = b.path.at(min(b.s + 1.0, b.path.length))[0] - b.path.at(b.s)[0]
        nh = float(np.hypot(*h))
        h = h / nh if nh > 1e-6 else b.path.at(b.s)[1]
        nrm = np.array([-h[1], h[0]])
        (lat_a, lon_a), (lat_b, lon_b) = fm["slots"][a.name], fm["slots"][b.name]
        sp, rad = self.space, self.C["radius"]
        tgt = None
        for k in (1.0, 0.5):
            q = hp + nrm * (lat_a - lat_b) * k + h * (lon_a - lon_b)
            if sp.walkable(*q) and sp.clearance(*q) >= rad and sp.los(tuple(hp), tuple(q), 0.0):
                tgt = q
                break
        if tgt is None:  # 通路が狭い: 先導の人の後ろに縦に並ぶ
            tgt = hp - h * FORM_FILE_GAP * fm["rank"].get(a.name, 1)
            if not sp.walkable(*tgt):
                return None
        for o in self._taken_xy:  # 持ち場に知らない人がいる: 寄らない
            if o[2] != g and math.hypot(o[0] - tgt[0], o[1] - tgt[1]) < FORM_TAKEN_M:
                return None
        aim = tgt + h * self.C["look_m"]
        if not (sp.walkable(*aim) and sp.los(tuple(p), tuple(aim), 0.0)):
            aim = tgt
            if not sp.los(tuple(p), tuple(tgt), 0.0):
                return None
        e = aim - p
        ne = float(np.hypot(*e))
        if ne < 1e-6:
            return None
        lon_err = float((tgt - p) @ h)
        # 基準は先導の人の今の速さ（決めた速さにすると、先導の人が遅くしている間、持ち場より前に出た。V 字の真ん中が前に出ていた）
        v = float(np.clip(getattr(b, "v_now", b.speed) + FORM_GAIN * lon_err, 0.0, 1.3 * a.speed))
        return e / ne, v

    def _cfsm_step(self, a, i, p, tan, active, XY, groups, P):
        """motion_model "cfsm" の 1 コマ（CFSM の説明は上）。→ (新しい位置, 経路の向き, 進んだ長さ)"""
        C, dt = self.C, self.dt
        r2 = 2 * C["radius"]
        L, s = a.path.length, a.s
        lane = a.mode == "gate_pass" or (a.mode == "to_gate" and L - s < 2.0)  # 列・ゲートの中は経路の上をまっすぐ（扉の向こうへは壁だけ見ない）
        # 壁を見ないのは、扉の向こうとの行き来のうち、自分か目指す点が歩ける所の外にあるときだけ（ホールの中では、待つ人をよけて扉まで歩く。
        # EV に乗る人が待つ場所から扉までまっすぐな線を外れられず、線の上の待つ人にふさがれて動けなかった、2026-11-05）
        nw = (a.no_walls and not (self.space.walkable(*p) and self.space.walkable(*a.path.at(min(s + C["look_m"], L))[0]))) or not self.space.walkable(*p)
        rel = XY - p
        d = np.hypot(rel[:, 0], rel[:, 1])
        near = d < C["cutoff"]
        near[i] = False
        if self.seatsets or self.rooms:  # 座っている人は席（歩ける所の外、家具）の中: 人としてはよけない（席の列の端で、座っている人から離れる向きと
            # 行き先の向きが打ち消し合って止まり、動けなくなった、hospital_outpatient の種 13、2026-11-13）。部屋の中の点で扉を待つ人も（後から入る仲間が
            # よけて着けなかった、2026-11-16）
            near &= ~np.array([b.sitting or b.room_wait for b in active], bool)
        mate = np.array([a.group is not None and b.group == a.group for b in active], bool)
        # 自分の速さ: グループのまとまり（前のモデルと同じ）。密度で遅くなるのは、前の人までの距離の規則から出るので、
        # Weidmann の式（speed_density）は掛けない（掛けると 2 重に遅くなり、ボトルネックで 1.43 人/(m·s)、2026-11-05）
        factor, boost = 1.0, 1.0
        if self.sd and self.sd.get("apply_in_cfsm") and a.mode != "gate_pass":
            front = int((near & ~mate & (d < self.sd["radius"]) & ((rel @ tan) > 0)).sum())
            if front:
                vv = weidmann_speed(front / self.sd_area, self.sd["v0"], self.sd["gamma"], self.sd["rho_max"])
                factor = max(0.1, vv / self.sd["v0"])
        if a.group is not None and a.mode == "walk":
            # 仲間との前後のずれ（持ち場の前後の差を引く。V 字の真ん中・縦 1 列の後ろの人は、後ろにいるのが持ち場）
            slots = (self.formation.get(a.group) or {}).get("slots", {})
            mine = slots.get(a.name)
            offs = [float((P[id(b)][0] - p) @ tan) - (slots[b.name][1] - mine[1] if mine and b.name in slots else 0.0)
                    for b in groups.get(a.group, ()) if b is not a and np.hypot(*(P[id(b)][0] - p)) < 12.0]
            if offs:
                m = sum(offs) / len(offs)
                if m < -GROUP_GAP:
                    factor = min(factor, max(0.3, 1.0 + 0.5 * (m + GROUP_GAP)))
                elif m > GROUP_GAP and factor >= 0.95:
                    boost = min(1.3, 1.0 + 0.4 * (m - GROUP_GAP))
        v0 = a.speed * factor * boost
        # 行き先の向き: 経路の look_m 先（歩くときは好みの横のずれ。止まる所の手前では 0 へ）
        # 扉の向こうとの行き来（straight の段取り、no_walls）は扉の線そのものを歩くので、横のずれは付けない（2 人連れの東側の人が、
        # 扉の向こうの歩ける所で東へずれて扉の柱の外へ出て、回り込んだ、office_gate_ev、2026-11-06）
        ld = a.l_pref if (a.mode == "walk" and not lane and not a.no_walls) else 0.0
        if a.taper:
            ld *= min(1.0, max(0.0, L - s))
        for look in (C["look_m"], C["look_m"] / 2, C["look_m"] / 4, C["look_m"] / 10, None):  # 壁の向こうになる点は目指さない（出入口の横の角で動けなくなった）
            if look is None:  # 少し先のどの点も見通せない（角を回り込んだ所）: 今の位置から経路を引き直す。
                # 経路の真横の点を目指すと、角の前で前後に行ったり来たりした（2026-11-05）
                # 行き先が歩ける所の外（かごの中・扉の向こう）なら、歩ける所の最後の点まで引き直し、その先は元の経路のまま足す
                # （行き先までの経路を探すと歩ける所の手前で終わり、EV に乗る人が扉の外で「乗った」ことになって消えた、office_ev_hall、2026-11-06）
                try:
                    a.path = Path(self.reroute_pts(p, a.path))
                except ValueError:
                    break
                a.s, s, L = 0.0, 0.0, a.path.length
                q, tq = a.path.at(min(C["look_m"], L))
                break
            q, tq = a.path.at(min(s + look, L))
            if lane or nw or self.space.los(tuple(p), tuple(q), 0.0):
                break
        # 横の好みの位置は、今いる所の経路の向きで決める（目指す点の向きで決めると、曲がり角の手前で目指す点が角の前後を行き来し、
        # 3 人組の端の人（横 1.08 m）の向きが毎コマ入れ替わって動けなかった、2026-11-05）
        ts = a.path.at(s)[1]
        nq = np.array([-ts[1], ts[0]])
        # 横のずれを壁の手前で減らしたら、すぐには戻さず LD_RECOVER_PER_S でゆっくり戻す（ずらした点が歩けるか歩けないかが一歩ごとに入れ替わり、
        # 扉の角の前で 2 人連れの西側の人が東西に行き来して 12 秒動けなかった、office_gate_ev、2026-11-06）
        ld_full, scale = ld, getattr(a, "ld_scale", 1.0)
        ld = ld_full * scale
        for _ in range(3):
            if not ld or self.space.walkable(*(q + nq * ld)):
                break
            ld *= 0.5
        else:
            ld = 0.0
        if ld_full:
            up = scale + LD_RECOVER_PER_S * self.dt
            a.ld_scale = min(abs(ld / ld_full), up) if abs(ld) < abs(ld_full * scale) - 1e-9 else min(1.0, up)
        e0 = q + nq * ld - p
        n0 = float(np.hypot(*e0))
        e0 = e0 / n0 if n0 > 1e-6 else tan
        form = self._form_target(a, p, s, L, P)
        if form is not None:  # グループの持ち場へ寄る（先導の人の位置と向きから）
            e0, v0 = form
        e = e0.copy()
        # 安全弁: 行き先に UNSTICK_S 秒近づけない人は、SQUEEZE_S 秒だけ周りの人を無視して半分の速さで通り抜ける（壁は見る）。
        # 込み入った所（扉の角・EV の扉・列の後ろ）で、人どうしが互いによけきれず止まったままになるのを防ぐ（そのぶん少し重なる、docs/validity.md の 5）
        car = getattr(a, "board_car", None)
        waiting = (a.mode == "board" and car is not None and self.space.walkable(*p)  # まだ扉の外にいる人だけ（かごに入った人は進む）
                   and math.hypot(p[0] - car.door[0], p[1] - car.door[1]) > 0.8 and self.alighting(car))
        if waiting:  # 降りる人を待っている間は、止まっていても安全弁を使わない
            a.best_t = self.t
        if a.mode == "to_gate" and getattr(a, "blocker", None) is not None and (a.blocker.state == "gate_queue" or a.blocker.mode in ("gate_wait", "to_gate")):
            a.best_t = self.t  # 列の後ろで待っている（安全弁は使わない）
        # ゲートへ向かう人も、ゲートの手前 2 m より外なら安全弁を使う（EV から降りて退館のゲートへ向かう人が、EV を待つ人たちのあいだで
        # 押される向きが毎コマ変わって 28 秒進めなかった、素材の A 組の office の EV 前、2026-11-06）
        if a.mode in ("walk", "to_spot", "board", "to_gate") and not lane and getattr(a, "best_path", None) is a.path and self.t - a.best_t >= UNSTICK_S:
            if a.mode == "to_spot":  # EV の待つ場所に着けない: 通り抜けず、今いる所の近くの空いた所を選び直す（待つ人の上に立たないように）
                self.respot(a, p)
                a.best_t = self.t
                return p, tan, 0.0
            a.squeeze_until, a.best_t = self.t + SQUEEZE_S, self.t
            self.squeezes += 1
        squeeze = self.t < getattr(a, "squeeze_until", -1.0)
        ne = 1.0
        if not lane and not squeeze:
            k = np.flatnonzero(near & (d > 1e-9))
            if len(k):
                # グループの仲間どうしは近くを並んで歩く（横 0.66 m、Zanlungo ら 2017）ので、離れる向きは JuPedSim の既定の距離 0.1 m だけ
                # （0.25 m だと 2 人連れの間隔が 1.21 m に広がった、2026-11-05）
                rng = np.where(mate[k], C["mate_range"], C["neighbor_range"])
                push = C["neighbor_strength"] * np.exp((r2 - d[k]) / rng)
                e -= (push[:, None] * rel[k] / d[k, None]).sum(0)
                # 真正面の人: 離れる向きが進む向きと重なるので、決まった側へ少しずらす（向かい合って止まらないように）
                ahead, side = rel[k] @ e0, rel[k] @ np.array([-e0[1], e0[0]])
                head_on = (ahead > 0) & (np.abs(side) < 0.05) & (d[k] < 1.5)
                if head_on.any():  # よける側は全員そろえる（人ごとに決めると、向かい合う 2 人が同じ側へよけて止まった）
                    e += PASS_SIDE * 0.3 * np.array([-e0[1], e0[0]])
            lrel, ld_ = self._link_points(a, p)
            if len(ld_):  # ほかのグループの仲間を結ぶ線: 線の上のいちばん近い点を、人と同じようによける（仲間の間を通らない）
                e -= ((C["neighbor_strength"] * np.exp((r2 - ld_) / C["neighbor_range"]))[:, None] * lrel / ld_[:, None]).sum(0)
                if ((lrel @ e0 > 0) & (np.abs(lrel @ np.array([-e0[1], e0[0]])) < 0.05) & (ld_ < 1.5)).any():
                    e += PASS_SIDE * 0.3 * np.array([-e0[1], e0[0]])
                # 手前から（2.5 m）線の端の外側へ回り込む向きも試したが、混んだ所で安全弁が増えた（office_ev_hall の種 17〜32 で 11 → 34 回、
                # 2026-11-12）。混んだ所の 2 人連れは 0.5〜0.7 m の間隔で、体の幅でもともと間を通れない
            if not nw:
                c, n = self._wall(p)
                if c < C["radius"] + 5 * C["wall_range"]:
                    e += C["wall_strength"] * math.exp((C["radius"] - c) / C["wall_range"]) * n
            ne = float(np.hypot(*e))
            e = e / ne if ne > 1e-9 else e0
        # 速さ: 進む向きの、体の幅の帯の中で一番近い人まで（グループの仲間も体は重ならない）
        ahead = rel @ e
        lat = np.abs(rel @ np.array([-e[1], e[0]]))
        cone = near & (ahead > 0) & (lat < r2)
        if a.mode == "to_gate" and a.lane is not None and cone.any():
            # 同じレーンで列の順が自分より後ろの人が真横（横に 0.3 m 以上）にいても、前の人として見ない（グループの仲間も）。横に並んで同じレーンに
            # 加わった 2 人が、互いを前の人とみて止まり、レーンが 150 秒止まった（verify_gate_capacity の種 2、2026-11-06。仲間どうしは 0.355 m で、
            # 離れる一歩の対象でもなかった）。横に 0.3 m 以上なら、前へ出ても 0.3 m より近づかない
            for j in np.flatnonzero(cone):
                b = active[j]
                if b.lane is a.lane and (b.gate_slot or 0) > (a.gate_slot or 0) and lat[j] >= 0.3:
                    cone[j] = False
        if a.mode == "walk" and not lane and not squeeze:
            # 合流で譲る: 斜め前の近く（YIELD_D 以内・横 YIELD_LAT 以内）に、自分より長く進めずにいる人（YIELD_S 秒以上）がいれば、前の人とみて
            # 減速し、先に入れる（出入口の手前の角の人が、真ん中の流れに割り込めず 15 秒たって安全弁で通り抜けていた。verify_bottleneck で
            # 1 回に 20 回ほど、2026-11-06）。進めずにいる時間の長い順に譲るので、譲り合って止まらない
            mine = self.t - getattr(a, "best_t", self.t)
            for j in np.flatnonzero(near & ~mate & ~cone & (ahead > 0) & (lat < YIELD_LAT) & (d < YIELD_D)):
                b = active[j]
                waited = self.t - getattr(b, "best_t", self.t)
                if b.mode == "walk" and waited >= YIELD_S and (waited, b.name) > (mine, a.name):
                    cone[j] = True
        if squeeze:
            cone = np.zeros(len(d), bool)
            v0 = 0.5 * v0
        gap = float(d[cone].min()) if cone.any() else np.inf
        a.blocker = active[int(np.flatnonzero(cone)[np.argmin(d[cone])])] if cone.any() and gap < r2 + 0.3 else None
        # 前の人がグループの仲間なら、ついていく間隔を mate_time_gap に（混んで 1 列になった 2 人連れが 1.6 m ほど離れた、2026-11-05）
        tg = np.where(mate, C["mate_time_gap"], C["time_gap"])
        # ゲートの列へ向かう人は、列に並ぶ人の後ろでは QUEUE_GAP（0.65 m）あけて止まる（体が触れる 0.36 m まで詰めると、
        # 列の後ろの人どうしが 0.45 m 未満になった、2026-11-05）
        gap_min = np.full(len(d), r2)
        if a.mode == "to_gate" or (a.k + 1 < len(a.plan) and a.plan[a.k + 1][0] == "gate"):
            queued = np.array([b.state == "gate_queue" or b.mode in ("gate_wait", "to_gate") for b in active], bool)
            gap_min[queued & ~mate] = QUEUE_GAP
        v = min(v0, max(0.0, float(((d[cone] - gap_min[cone]) / tg[cone]).min()))) if cone.any() else v0
        if not lane and not squeeze:  # 仲間を結ぶ線が前にあれば、人が前にいるのと同じに遅くする
            lrel, ld_ = self._link_points(a, p)
            if len(ld_):
                lc = (lrel @ e > 0) & (np.abs(lrel @ np.array([-e[1], e[0]])) < r2)
                if lc.any():
                    v = min(v, max(0.0, float((ld_[lc].min() - r2) / C["time_gap"])))
        prev = getattr(a, "e_prev", None)
        damped = self.t < getattr(a, "chatter_until", -1.0)
        # 前のコマの向きから 90 度より大きく変わった（行ったり来たり）か、遅くしている間に和がまだ短い（釣り合ったまま）: 遅くし続ける
        # （逆になったときだけ遅くすると、釣り合う所へゆっくり寄る間に 0.5 秒たち、速さを戻した 1 コマで 4.5 cm 跳んで、また逆になった）
        if (prev is not None and float(e @ prev) < 0.0) or (damped and ne < BALANCE_E):
            a.chatter_until = self.t + CHATTER_S
        a.e_prev = e
        damp = CHATTER_S <= 0 or self.t < getattr(a, "chatter_until", -1.0)
        if not lane and not squeeze and damp:
            # 行き先へ引く向きと、周りの人・壁から離れる向きが打ち消し合う（和が短い）と、和の向きは位置が 1 cm 動くだけで逆になる。
            # その向きの前の空きで速さを決めていたので、待つ人の手前などで毎コマ前後に 1〜5 cm 跳ね、歩く姿勢のままその場で揺れた
            # （素材 v5 の EV の前で、揺れのコマの 9 割がこれ。和の長さの中央値 0.1、2026-11-08）。和の長さが BALANCE_E より短ければ、
            # 長さに比例して遅くする（釣り合う所では止まる）。行き先と逆向きに押し戻される一歩は BACK_M_S まで（前は空いていれば 1.4 m/s で戻った）。
            # 行ったり来たりしている間だけにする（いつも遅くすると、向かい合ってすれ違う人も遅くなり、verify_counterflow の自由に歩く速さが
            # 種 9 のうち 9 → 2 で合い、所要が 41 → 49 秒。2 乗で遅くする・上限を付けると揺れはもっと減るが、
            # 混んだ所で止まったままの人が出た。docs/validity.md の 5.5）
            v *= min(1.0, ne / BALANCE_E)
            if float(e @ e0) < 0:
                v = min(v, BACK_M_S)
        a.waiting_alight = waiting
        if waiting:  # 降りる人が出るまで、扉の前で待つ
            v = 0.0
            if getattr(a, "nudge", None) and self.t < a.nudge[1]:
                # 降りる人に頼まれたら、横へよけて道をあける（立って待つ人と同じ。前は扉の前で降りる人の前に立ったままで、降りる人が揺れながら
                # 抜けていた。揺れをなくすと、降りるのに 20〜50 秒かかり、乗る人も待ち続けた。hospital_gate_ev の種 13、2026-11-08）
                e, v = a.nudge[0], NUDGE_M_S
        # すでに体の幅より近い人がいる（安全弁で通り抜けた後など）: 前の人までの距離の規則では速さが 0 になり、重なったまま離れられない。
        # その人たちから離れる向き（近いほど強く）に SEPARATE_M_S で歩く（office_ev_hall で、安全弁の後に 2 人が 19 秒重なったまま。
        # 一番近い 1 人から離れる向きだけでは、2 人に挟まれたとき、もう 1 人に近づく一歩になって取り消された、2026-11-06）
        # ゲートの手前（経路の上をまっすぐ歩く所）でも離れる（横に並んだ 2 人が 0.35 m で互いにふさいだまま止まった、verify_gate_capacity の種 8）
        if (not lane or a.mode == "to_gate") and not squeeze and v < 0.05:
            k = np.flatnonzero(near & ~mate & (d < r2) & (d > 1e-9))
            if len(k):
                away = -(rel[k] / d[k, None] * (r2 - d[k])[:, None]).sum(0)
                na = float(np.hypot(*away))
                if na > 1e-9:
                    e, v = away / na, SEPARATE_M_S
        b = a.blocker
        yielders = ("stop", "meet", "wait", "board_wait")  # 道をあけてもらえる立つ人
        def yields(o):  # 立つ人と、扉の前で降りる人を待つ乗る人（座っている人・座る立つ動作の人は除く）
            return (o.mode in yielders and not o.sitting and o.script is None) or (o.mode == "board" and getattr(o, "waiting_alight", False))
        if v < 0.05 and b is not None and yields(b):  # 立っている人にふさがれたら、その人に横へよけてもらう
            side = np.array([-e[1], e[0]])
            sgn = 1.0 if float((self.where(b)[0] - p) @ side) >= 0 else -1.0
            b.nudge, b.nudge_by = (side * sgn, self.t + 1.5), a
        elif not lane and a.mode in ("walk", "to_spot", "board", "to_gate") and self.t - getattr(a, "best_t", self.t) >= NUDGE_ASK_S:
            # 前の人はいないのに進めない（周りの立って待つ人に押される向きが毎コマ変わる）: 行き先の向きの前側の近くに立つ人に、横へよけてもらう
            # （EV を待つ人たちのあいだで、降りた人が 28 秒進めなかった、2026-11-06）
            side = np.array([-e0[1], e0[0]])
            for j in np.flatnonzero(near & ~mate & (d < NUDGE_ASK_M) & ((rel @ e0) > -0.1)):
                b = active[j]
                if yields(b) and not (getattr(b, "nudge", None) and self.t < b.nudge[1]):
                    b.nudge, b.nudge_by = (side * (1.0 if float(rel[j] @ side) >= 0 else -1.0), self.t + 1.5), a
        if self.cars and not squeeze and CLEAR_AHEAD_M > 0 and (a.mode == "board" or (a.mode == "walk" and a.info.get("stream") == "alight")):
            # EV に乗る人・降りた人の扉までの道に立って待つ人は、先に横へよける（前は 3 秒進めずにいてから 0.9 m 以内の人に頼んだので、
            # 乗らずに待つ人の中を扉まで歩く乗る人が 10 秒より長くかかった（8〜19%）。降りた人も、1 m 先に立つ人と釣り合って止まり、
            # そのあいだ乗る人は扉の前で待った。docs/validity.md の 5.13、2026-11-16）
            car = a.board_car if a.mode == "board" else next((c for c in self.cars if c.name == a.info.get("origin")), None)
            if car is not None and (a.mode == "board" or math.hypot(p[0] - car.door[0], p[1] - car.door[1]) < CLEAR_DOOR_M):
                side = np.array([-e0[1], e0[0]])
                lat = rel @ side
                for j in np.flatnonzero(near & ~mate & (d < CLEAR_AHEAD_M) & ((rel @ e0) > 0.1) & (np.abs(lat) < CLEAR_W_M)):
                    b = active[j]
                    if yields(b) and not (getattr(b, "nudge", None) and self.t < b.nudge[1]):
                        sgn = (1.0 if lat[j] > 0 else -1.0) if abs(lat[j]) > 0.02 else tie_side(b.name)
                        b.nudge, b.nudge_by = (side * sgn, self.t + 1.5), a
        step = e * v * dt
        p2 = p + step
        if not nw and not self._can_step(p, p2):  # 壁に当たる一歩は、壁に沿う向きだけにする
            _, n = self._wall(p)
            into = float(step @ n)
            if into < 0:
                step = step - into * n
            p2 = p + step
            if not self._can_step(p, p2):  # 格子の角に当たるなら、縦だけ・横だけの一歩を試す
                for cand in (np.array([step[0], 0.0]), np.array([0.0, step[1]])):
                    if float(np.hypot(*cand)) > 1e-9 and self._can_step(p, p + cand):
                        step, p2 = cand, p + cand
                        break
                else:
                    step, p2 = np.zeros(2), p.copy()
        if not lane and not squeeze and float(np.hypot(*step)) > 0:  # 念のため: グループ以外の人の min_sep 以内に入り、さらに近づく一歩は取り消す
            k = np.flatnonzero(near & ~mate)
            if len(k):
                dn = np.hypot(*(XY[k] - p2).T)
                if ((dn < C["min_sep"]) & (dn < d[k])).any():
                    step, p2 = np.zeros(2), p.copy()
        if nw:  # 扉の向こうとの行き来は壁を見ないので、まっすぐな線から横へ NO_WALL_LAT_M までにする（隣の区画に入らないように）
            sq = a.path.project(p2, s - 0.5, s + C["look_m"] + 1.0)
            q0, tq0 = a.path.at(sq)
            nrm = np.array([-tq0[1], tq0[0]])
            off = float((p2 - q0) @ nrm)
            if abs(off) > NO_WALL_LAT_M:
                # 一歩のうち、線から離れる向きの分だけを除く。前は線の点から横へ NO_WALL_LAT_M の所へ置き直していて、
                # 曲がり角（EV の扉からかごの奥へ）の内側では置き直した所が元の位置に重なり、扉の前で 7 人が 50 秒動けなかった（2026-11-06）
                out = float(step @ nrm) * math.copysign(1.0, off)
                if out > 0:
                    step = step - nrm * math.copysign(out, off)
                    p2 = p + step
                off2 = float((p2 - q0) @ nrm)
                if abs(off2) > NO_WALL_LAT_M + 0.2:  # 大きく外れた: 線の近くへ、1 コマに自分の速さの半分ずつ戻す
                    # （前は線から NO_WALL_LAT_M の所へ 1 コマで置き直していた。待つ人をよけて線から離れたまま扉の向こうを見始めた乗る人が、
                    # 1 コマで最大約 1 m 跳んだ。EV の前の 3 つのテンプレートの 48 回で 198 回、2026-11-12）
                    p2 = p2 - nrm * math.copysign(min(abs(off2) - NO_WALL_LAT_M, NO_WALL_BACK * a.speed * dt), off2)
                    step = p2 - p
                k = np.flatnonzero(near & ~mate) if not squeeze else np.zeros(0, int)
                if len(k):  # 戻した位置でも、ほかの人に近づきすぎないか
                    dn = np.hypot(*(XY[k] - p2).T)
                    if ((dn < C["min_sep"]) & (dn < d[k])).any():
                        step, p2 = np.zeros(2), p.copy()
        a.xy = p2
        a.v_now = float(np.hypot(*step)) / dt  # 今の速さ（グループの仲間が持ち場へ寄るときの基準）
        a.s = a.path.project(p2, s - 2.0, s + C["look_m"] + 1.0)  # 押し戻されたら進み具合も戻す
        if not lane and not nw and float(np.hypot(*(p2 - a.path.at(a.s)[0]))) > REROUTE_M:  # 経路から離れすぎたら、今の位置から引き直す
            try:
                a.path, a.s = Path(self.reroute_pts(p2, a.path)), 0.0  # 行き先が歩ける所の外なら、その先は元の経路のまま
            except ValueError:
                pass
        return p2, a.path.at(a.s)[1], float(np.hypot(*step))

    def _out_motion(self, a, d, raw_moving):
        """書き出す「歩いているか」と、体を向ける向きの速さ（d はこのコマの一歩）。描画は「歩いているか」の間だけ進んだ距離で歩く姿勢を進め、
        体を速さの向きへ回す。1 コマの一歩で決めると、前後に 1 cm ほど跳ねる人の印が毎コマ入れ替わり、体が 90〜150 度振れて、
        歩く姿勢と立つ姿勢が入れ替わった（その場で揺れて見える、2026-11-08）。OUT_TAU 秒でならした速さで決め、歩き始めは MOVE_ON_M_S、
        止まるのは MOVE_OFF_M_S（2 コマ続けてほとんど動かなければすぐ止まる。止まった人が歩く途中の姿勢で固まらないように）。"""
        if OUT_TAU <= 0:
            return raw_moving, d
        vel = d / self.dt
        vs = getattr(a, "vel_s", None)
        vs = vel.copy() if vs is None else vs + min(1.0, self.dt / OUT_TAU) * (vel - vs)
        a.vel_s = vs
        a.still_n = getattr(a, "still_n", 0) + 1 if float(np.hypot(*d)) < 0.05 * self.dt else 0
        if a.still_n >= 2:  # 止まった: ならした速さも 0 に（残ったままだと、止まる・歩き始めるが毎コマ入れ替わった）
            vs = a.vel_s = np.zeros(2)
        sp = float(np.hypot(*vs))
        mv = (sp > MOVE_OFF_M_S and a.still_n < 2) if getattr(a, "moving_out", False) else sp > MOVE_ON_M_S
        a.moving_out = mv
        return mv, vs

    def step_agents(self, f, t):
        dt = self.dt
        active = [a for a in self.agents if a.mode in ("walk", "to_spot", "board", "stop", "meet", "wait", "to_gate", "gate_wait", "gate_pass", "board_wait")]
        P = {id(a): self.where(a) for a in active}
        groups = {}
        for a in active:
            if a.group is not None and a.mode in WALKING:
                groups.setdefault(a.group, []).append(a)
        if self.model == "cfsm":  # 全員の位置（このコマの始め。全員を同じ時刻の位置から動かす）
            XY = np.array([P[id(b)][0] for b in active], float).reshape(-1, 2)
            idx = {id(b): k for k, b in enumerate(active)}
            self._update_formation(active, P, XY, groups)
        for a in active:
            p, tan = P[id(a)]
            if a.mode == "board_wait" and t >= a.until:
                if a.spot is not None:
                    self.free[a.spot] = True
                self.alloc.pop(a.name, None)
                car = a.board_car  # 扉まで歩き、かごの中（cabin）へ入ってから消える
                door, cabin = np.asarray(car.door, float), np.asarray(car.cabin, float)
                if self.model == "cfsm":  # 乗る順に左右へ分け、2 列で入る（1 列だと続けて乗る間隔が 1.8 秒に延びた、2026-11-05）
                    d_in = np.asarray(car.inside, float) - door  # 扉からかごの向き
                    n_in = float(np.hypot(*d_in))
                    side = np.array([-d_in[1], d_in[0]]) / n_in * getattr(a, "board_side", 0.0) if n_in > 1e-9 else np.zeros(2)
                    door, cabin = door + side * BOARD_LANE_M[0], cabin + side * BOARD_LANE_M[1]
                pre = []
                if self.model == "cfsm" and BOARD_FRONT_M > 0 and n_in > 1e-9:
                    # 扉の横から乗る人は、扉の前の点を通る（かごの箱の横の角へまっすぐ向かい、壁から離れる向きと釣り合って
                    # その場で揺れた。hospital_gate_ev の EV の扉の脇、2026-11-16）
                    u_in = d_in / n_in
                    front = door - u_in * BOARD_FRONT_M
                    if float((door - p) @ u_in) < BOARD_FRONT_M - 0.1 and float(np.hypot(*(p - front))) > 0.2:
                        pre = [tuple(front)]
                pts = [tuple(p)] + pre + [tuple(door)] + ([tuple(cabin)] if car.depth_m > 0 else [])
                a.path, a.s, a.l, a.mode, a.state, a.taper = Path(pts), 0.0, 0.0, "board", "ev_wait", True
                a.no_walls = True  # 扉の向こう（かごの中）は歩ける所の外
                a.events["board_start"] = round(t, 2)
            if a.mode == "stop" and a.script is not None:  # 座る・立つ動作（components.play）: 決まった軌跡どおりに 1 コマずつ
                sc = a.script
                k = min(max(0, f - sc["f0"]), len(sc["pts"]) - 1)
                x, y, yaw = sc["pts"][k]
                q = np.array([x, y], float)
                self.here[a.name], a.xy, a.yaw, a.dir = q, q.copy(), yaw, None
                a.vel_s, a.moving_out, a.still_n = np.zeros(2), False, 2  # 動作のあと歩き出すときは、止まった人として始める
                a.frames.append((f, x, y, yaw, False))
                a.states.append(a.state)
                if k >= len(sc["pts"]) - 1:
                    a.script = None
                    sc["then"](a, t, q)
                continue
            if a.mode in ("stop", "meet", "wait", "gate_wait", "board_wait"):
                a.dir = None
                nudged = False
                if self.model == "cfsm" and a.mode in ("stop", "meet", "wait", "board_wait") and getattr(a, "nudge", None) and t < a.nudge[1]:
                    q = p + a.nudge[0] * NUDGE_M_S * dt  # 歩く人に道をあける（ほかの人・壁に当たるならやめる）
                    others = XY[np.arange(len(XY)) != idx[id(a)]]
                    # 動いた先で体の幅より近づく人がいればやめる。もう近い人から離れる一歩はよい（重なった相手がいると、道をあけられなかった、2026-11-06）
                    dq, dp = (np.hypot(*(others - q).T), np.hypot(*(others - p).T)) if len(others) else (np.zeros(0), np.zeros(0))
                    if getattr(a, "nudge_home", None) is None:
                        a.nudge_home = p.copy()  # 道をあけ終わったら戻る所
                    # 窓口で応対を受けている人も道をあける。道をあけるのを止める・0.4 m までにすると、受付の前を通る人が押し合い、
                    # 安全弁 168 → 368・330 回に増えた（応対中の人が机から離れるのは残り。通る人の経路が受付の前を避けるようにするのが次の手、
                    # docs/validity.md の 5.10、2026-11-16）
                    if self._can_step(p, q) and not ((dq < 2 * self.C["radius"]) & (dq < dp)).any():
                        self.here[a.name] = q
                        a.xy, p, nudged = q.copy(), q, True
                    else:
                        a.nudge = None
                elif self.model == "cfsm" and a.mode in ("stop", "meet", "wait", "board_wait") and getattr(a, "nudge_home", None) is not None:
                    # 道をあけ終わった: 歩く人が離れたら、元の立つ場所へ戻る（よけた先で隣の人と体が触れたまま 30 秒立っていた、
                    # hospital の EV 前 mid の v4、2026-11-07）。戻る一歩で誰かに体の幅より近づくなら、その場で待つ
                    h = a.nudge_home
                    dh = h - p
                    n = float(np.hypot(*dh))
                    me = idx[id(a)]
                    # 戻る所に、ほかの立つ人（仲間でない）が SPACE_M より近く立っていれば、戻らずにここで待つ（戻る一歩のたびに体が触れ、
                    # 混んだ待つ場所の端で 2 人が触れたまま 70 秒立った。hospital_gate_ev の種 10、2026-11-16）
                    taken = any(j != me and active[j].mode in ("wait", "board_wait", "stop", "meet")
                                and not (a.group is not None and active[j].group == a.group)
                                and float(np.hypot(*(XY[j] - h))) < SPACE_M for j in range(len(XY)))
                    if n < 0.03 or taken:
                        a.nudge_home = None
                    else:
                        movers = [b for b in active if b is not a and b.mode in ("walk", "to_spot", "board", "to_gate")]
                        busy = movers and min(float(np.hypot(*(P[id(b)][0] - h))) for b in movers) < HOME_CLEAR_M
                        # 頼んだ人がまだ近く（道をあけてもらう距離の中）で歩く途中なら戻らない（戻るとまた頼まれ、よける・戻るを 20 秒くり返した。
                        # 戻るのは歩く人が HOME_CLEAR_M より離れたとき、頼むのは NUDGE_ASK_M の中、office_ev_hall の種 13、2026-11-17）
                        asker = getattr(a, "nudge_by", None)
                        if (not busy and asker is not None and id(asker) in P and asker.mode in ("walk", "to_spot", "board", "to_gate")
                                and float(np.hypot(*(P[id(asker)][0] - h))) < max(NUDGE_ASK_M, CLEAR_AHEAD_M) + 0.2):
                            busy = True
                        if not busy:
                            q = p + dh / n * min(n, NUDGE_M_S * dt)
                            others = XY[np.arange(len(XY)) != idx[id(a)]]
                            dq, dp = (np.hypot(*(others - q).T), np.hypot(*(others - p).T)) if len(others) else (np.zeros(0), np.zeros(0))
                            if self._can_step(p, q) and not ((dq < 2 * self.C["radius"]) & (dq < dp)).any():
                                self.here[a.name] = q
                                a.xy, p, nudged = q.copy(), q, True
                if (self.model == "cfsm" and not nudged and a.mode == "wait" and not (getattr(a, "nudge", None) and t < a.nudge[1])
                        and len(XY) > 1):
                    # EV を待つ人は、隣の知らない立つ人と SPACE_M より近ければ、空いていれば少し離れる（前へ詰めたあと・自分の場所まで行けず途中で
                    # 立ったあとに、隣の人と体が触れたまま立っていた。hospital の EV 前 mid の v4 で、待つ人の 17% が 0.45 m 未満、2026-11-07）。
                    # 道をあけたあと元の場所へ戻れずにいる人も（前は戻る所がある人は離れず、混んだ待つ場所の端で道をあけた 2 人が触れたまま
                    # 50〜70 秒立った。hospital_gate_ev の種 10、2026-11-16）。立った所（戻る所）からは、今より遠くへは離れない
                    me = idx[id(a)]
                    rel_s = XY - p
                    d_s = np.hypot(*rel_s.T)
                    k = [j for j in np.flatnonzero((d_s < SPACE_M) & (d_s > 1e-9)) if j != me and active[j].mode in ("wait", "board_wait", "stop", "meet")
                         and not (a.group is not None and active[j].group == a.group)]
                    if k:
                        away = -(rel_s[k] / d_s[k, None] * (SPACE_M - d_s[k])[:, None]).sum(0)
                        na = float(np.hypot(*away))
                        home = a.nudge_home if getattr(a, "nudge_home", None) is not None else getattr(a, "stand_xy", p)
                        if na > 1e-9:
                            q = p + away / na * SPACE_M_S * dt
                            others = np.delete(XY, me, axis=0)
                            dq, dp = np.hypot(*(others - q).T), np.hypot(*(others - p).T)
                            if (self._can_step(p, q) and float(np.hypot(*(q - home))) <= max(SPACE_MAX_M, float(np.hypot(*(p - home))) + 1e-9)
                                    and not ((dq < SPACE_M) & (dq < dp - 1e-9)).any()):
                                self.here[a.name] = q
                                a.xy, p, nudged = q.copy(), q, True
                if a.glance and t >= a.next_glance:
                    a.glance_i += 1
                    a.next_glance = t + a.rng.uniform(1.5, 3.5)
                goal = a.base_yaw + a.glance * (0, 1, 0, -1)[a.glance_i % 4]
                cur = a.yaw if a.yaw is not None else goal
                a.yaw = cur + max(-TURN_DEG_S * dt, min(TURN_DEG_S * dt, _wrap(goal - cur)))
                a.frames.append((f, float(p[0]), float(p[1]), a.yaw, self._out_motion(a, p - P[id(a)][0], nudged)[0]))
                a.states.append(a.state)
                if a.mode == "stop" and getattr(a, "regroup", None) is not None:  # ゲートの先で仲間を待つ: 全員が通ったか、最長の秒数で次へ
                    if t >= a.until or not self.mates_before(a, a.regroup):
                        a.events["regroup"][-1][1] = round(t, 2)
                        self.next_step(a, t, p)
                elif a.mode == "stop" and t >= a.until and not (t < a.until + GROUP_STOP_WAIT_S and (a.comp is None or a.comp.get("kind") == "seat")
                                                                  and self.mates_behind(a, t)):  # 窓口の先導の人は仲間を待たない（仲間が待つ）
                    if a.comp is not None and a.comp.get("kind") == "seat":  # 席から立ってから次へ（次も同じ席の場所で待つなら座ったまま）
                        if self.next_waits_on_seat(a):
                            self._finish(a, t, p)
                        else:
                            self.leave_seat(a, t, p, self._finish)
                    else:
                        self.next_step(a, t, p)
                elif a.mode == "meet":
                    m = a.plan[a.k][1]
                    if not m.done and m.arrived >= m.members:
                        m.done = True
                        for name in sorted(m.members):
                            b = self.by_name[name]
                            b.events["meet_end"] = round(t, 2)
                            self.next_step(b, t, self.here[b.name])
                continue
            if getattr(a, "direct", False):  # 席への出入り（components.py）: 決まった速さでまっすぐ
                step = min(SEAT_MOVE_M_S * dt, max(0.0, a.path.length - a.s))
                a.s += step
                p2, tan2 = a.path.at(a.s)
                a.xy = np.asarray(p2, float).copy()
            elif self.model == "cfsm":
                p2, tan2, step = self._cfsm_step(a, idx[id(a)], p, tan, active, XY, groups, P)
                self.queue_state(a, step)
            else:  # 前のモデル（lane）: 経路に沿って進み、横へずれてよける
                nrm = np.array([-tan[1], tan[0]])
                factor, dl = 1.0, (a.l_pref - a.l) * 0.8 * dt if a.mode == "walk" else -a.l * 2.0 * dt
                front = 0
                close = []  # 0.8 m 以内の、同じ向きに歩く前の人（追いついて体が重ならないように確かめる）
                R = self.sd["radius"] if self.sd else 0.0
                for b in active:
                    if b is a:
                        continue
                    mate = a.group is not None and a.group == b.group
                    reach = 0.7 if mate else 1.4
                    rel = P[id(b)][0] - p
                    r = float(np.hypot(*rel))
                    if r < R and not mate and float(rel @ tan) > 0:
                        front += 1
                    if r > max(reach, 2.0):
                        continue
                    ahead, lat = float(rel @ tan), float(rel @ nrm)
                    bdir = b.dir if b.dir is not None else (P[id(b)][1] if b.mode in WALKING else None)  # 詰まって止まっている人も同じ向きとみる
                    same = bdir is not None and float(bdir @ tan) > 0.5
                    if r < 0.8 and not mate and same and ahead > 0 and b.mode in WALKING:
                        close.append(P[id(b)][0])  # 同じ向きに歩く前の人だけ（向かい合う人・立って待つ人は、横へよけてすれ違う）
                    queued = (a.mode == "to_gate" and b.lane is a.lane and b.mode in ("to_gate", "gate_wait")
                              and (b.gate_slot or 0) < (a.gate_slot or 0) and abs(lat) < 0.45)  # 同じレーンの列で自分より前の人の 0.6 m 手前で止まる
                    follow = False
                    if mate and same and 0 < ahead < 0.8 and abs(lat) < 0.35:
                        factor = min(factor, max(0.0, (ahead - 0.5) / 0.5))
                    elif not mate and (same or queued) and 0 < ahead < 2.0 and abs(lat) < FOLLOW["lateral"]:
                        cap = max(0.0, (ahead - FOLLOW["a"]) / FOLLOW["b"])
                        factor = min(factor, cap / max(a.speed, 0.1))
                        follow = cap < a.speed and not queued
                        # 追い越しを強める（0.8 m/s）・遅い人のときだけにする、は廊下の速さを変えず、ゲートの列の近くで詰まりを生んだので入れない（2026-10-22）
                    elif 0 < ahead < 0.6 and abs(lat) < 0.45:
                        factor = min(factor, 0.3)
                    if a.mode == "gate_pass" or (a.mode == "to_gate" and a.path.length - a.s < 2.0):
                        continue  # ゲートを通る間と、列の場所の 2 m 手前からは横へよけない
                    side = -1.0 if lat > 0 else 1.0 if lat < 0 else tie_side(a.name)
                    if follow:  # 前の遅い人に詰まったら、横へ出て追い越す
                        dl += side * FOLLOW["overtake_m_s"] * dt
                    if r <= reach:
                        dl += side * (reach - r) / reach * 2.0 * dt
                if self.sd and front and a.mode != "gate_pass":  # 前の人の密度で遅くなる（Weidmann 1993）
                    v = weidmann_speed(front / self.sd_area, self.sd["v0"], self.sd["gamma"], self.sd["rho_max"])
                    factor = min(factor, max(0.1, v / self.sd["v0"]))
                boost = 1.0
                if a.group is not None and a.mode == "walk":  # グループのまとまり: 仲間より前なら待ち、後ろなら追いつく（ゲートで離れたあとなど）
                    offs = [float((P[id(b)][0] - p) @ tan) for b in groups.get(a.group, ()) if b is not a and np.hypot(*(P[id(b)][0] - p)) < 12.0]
                    if offs:
                        m = sum(offs) / len(offs)
                        if m < -GROUP_GAP:
                            factor = min(factor, max(0.3, 1.0 + 0.5 * (m + GROUP_GAP)))
                        elif m > GROUP_GAP and factor >= 0.95:
                            boost = min(1.3, 1.0 + 0.4 * (m - GROUP_GAP))
                a.l = float(np.clip(a.l + dl, -self.lmax, self.lmax))
                step = a.speed * factor * boost * dt
                a.s += step
                p2, tan2 = self.pos(a)
                if close and a.mode != "gate_pass":  # 体が重なる一歩は取り消す（ほかの人の MIN_SEP 以内に入り、さらに近づくなら進まない）
                    for q in close:
                        d_new, d_old = np.hypot(*(p2 - q)), np.hypot(*(p - q))
                        if d_new < MIN_SEP and d_new < d_old:
                            a.s -= step
                            step = 0.0
                            p2, tan2 = self.pos(a)
                            break
            moving = step > 0.2 * dt
            d = p2 - p
            a.dir = d / np.hypot(*d) if moving and np.hypot(*d) > 1e-6 else None
            moving, dv = self._out_motion(a, d, moving)
            if moving and np.hypot(*dv) > 1e-6:
                want = math.degrees(math.atan2(dv[1], dv[0]))
                cur = a.yaw if a.yaw is not None else want
                a.yaw = cur + max(-3 * TURN_DEG_S * dt, min(3 * TURN_DEG_S * dt, _wrap(want - cur)))
            if a.yaw is None:
                a.yaw = math.degrees(math.atan2(tan2[1], tan2[0]))
            if a.state == "alight" and self.space.walkable(*p2) and self.space.zone_of(*p2) not in a.info.get("alight_zones", ()):  # かごの中は降りる途中
                a.state = "pass"
            a.frames.append((f, float(p2[0]), float(p2[1]), a.yaw, moving))
            a.states.append(a.state)
            if self.model == "cfsm":  # 経路の終わりの横を過ぎたか、終わりの点に着いたか、終わりの近くで進めない
                to_end = float(np.hypot(*(p2 - a.path.at(a.path.length)[0])))
                goal = tuple(np.round(a.path.at(a.path.length)[0], 2))
                if getattr(a, "best_goal", None) != goal:  # 行き先が変わった: 進み具合を数え直す（経路を引き直しただけなら続ける。
                    # 引き直すたびに数え直すと、引き直しを繰り返す人に安全弁が働かず、動けないままだった、2026-11-05）
                    a.best_goal, a.best_end, a.best_rem, a.best_t = goal, np.inf, np.inf, t
                a.best_path = a.path
                # 進み具合は行き先までの直線距離で測り、大回りの経路（残りの長さが直線距離より DETOUR_M 以上長い）では、経路に沿った残りの長さが
                # 縮んでも進んだとみる（直線距離だけでは、ロビーから東へ大回りして廊下に入る人が、ふつうに歩いているのに安全弁を使った
                # （hospital_outpatient）。いつも残りの長さも見ると、押し合いの中で経路への当てはめが揺れて進んだようにみえ、
                # verify_bottleneck で動けない人が出た、2026-11-13）
                rem = a.path.length - a.s
                # 残りの長さで見るのは、この 1 秒で実際に DETOUR_MOVED_M 以上動いたときだけ（扉の手前でその場で前後に揺れる人の経路を引き直すたびに
                # 残りの長さがわずかに縮んで「進んだ」ことになり、安全弁が働かずに 150 秒動けなかった、office_ev_hall の種 13、2026-11-13）
                if t - getattr(a, "moved_t", -1e9) >= 1.0:
                    a.moved_ok = float(np.hypot(*(p2 - getattr(a, "moved_xy", p2)))) >= DETOUR_MOVED_M
                    a.moved_xy, a.moved_t = np.asarray(p2, float).copy(), t
                if to_end < a.best_end - 0.05 or (rem - to_end > DETOUR_M and getattr(a, "moved_ok", False)
                                                  and rem < getattr(a, "best_rem", np.inf) - 0.05):
                    a.best_end, a.best_rem, a.best_t = min(to_end, a.best_end), min(rem, getattr(a, "best_rem", np.inf)), t
                stall = (to_end < GOAL_NEAR_M and t - a.best_t >= GOAL_STALL_S and a.mode not in ("gate_pass", "to_gate", "board")
                         and not a.no_walls and self.space.walkable(*p2))  # 歩ける所の外（かごの中など）では使わない
                arrived = a.s >= a.path.length - 0.05 or to_end < self.C["arrive_m"] or stall
                if getattr(a, "direct", False):  # 席への出入りは最後まで動いてから（手前 0.15 m で着いたことにすると、席の点へ跳んだ）
                    arrived = a.s >= a.path.length - 1e-6
            else:
                arrived = a.s >= a.path.length - 1e-6
            if a.until_zone and self.space.zone_of(*p2) == a.until_zone:
                arrived = True
            if not arrived:
                continue
            if a.mode == "to_spot" and self.model == "cfsm" and self.crowded(a, p2):  # 着いた所に人がいる: そこには立たない
                self.respot(a, p2)
                continue
            if a.mode == "to_spot":
                a.mode = "wait"
                self.stand(a, t, p2, "ev_wait", self.nearest_door(p2), a.wait_glance)
                if not a.requeue:
                    a.events["wait_start"] = round(t, 2)
                    self.queue.append(a)
                a.requeue = False
            elif a.mode == "board":
                a.mode = "done"
                a.events["board"] = round(t, 2)
                a.events["end"] = round(t, 2)
            elif a.mode == "to_gate":
                a.mode = "gate_wait"
                self.stand(a, t, p2, "gate_queue", tuple(a.lane.center + a.gate_dir), 0.0)
            elif a.on_arrive is not None:  # 部品の歩き（列・席・扉・応対の場所）の着いた先で
                fn, a.on_arrive = a.on_arrive, None
                fn(a, t, p2)
            elif a.mode == "gate_pass":
                a.lane = None
                gstep = a.plan[a.k]
                if self.model == "cfsm" and a.group is not None and self.mates_before(a, gstep) and a.k + 1 < len(a.plan):
                    # 仲間がまだ通っていない（別のレーン・列の後ろ）: 通った先 REGROUP_M で待ってから、元の段取りを続ける
                    # （流れの脇へ 1 m ずらすのも試したが、揺れが減るテンプレートと増えるテンプレートがあり、安全弁は増えた。2026-11-12）
                    a.plan[a.k + 1:a.k + 1] = [("walk", tuple(p2 + a.gate_dir * REGROUP_M), "pass"), ("regroup", gstep, REGROUP_MAX_S)]
                self.next_step(a, t, p2)
            else:
                self.next_step(a, t, p2)


def state_runs(states, first_frame):
    """1 コマずつの状態を [始まりのコマ, 終わりのコマ, 状態] の列に縮める。"""
    runs = []
    for k, s in enumerate(states):
        if runs and runs[-1][2] == s:
            runs[-1][1] = first_frame + k
        else:
            runs.append([first_frame + k, first_frame + k, s])
    return runs
