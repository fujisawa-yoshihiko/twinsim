"""グループを見つける課題（グループの検出・追跡）の正解と評価（1.2）。

正解: コマごとに、映っている人をグループに分けたもの（1 人の組は数えない）。正解の ground_truth.json の groups（仲間）から作る。
together_only（既定）なら、いちばん近い仲間から APART_M（3 m）より離れている人は、そのコマではグループに入れない（分かれている間）。

評価（Setti ら 2015 の 4.3 節、Cristani ら 2011 の決め方を広げたもの）: 正解のグループ G は、見つけたグループのどれかに
G の人が ⌈T·|G|⌉ 人以上いて、G 以外の人が |G| − ⌈T·|G|⌉ 人以下なら当たり（T = 2/3 なら 2/3 以上が見つかり、まちがいは 1/3 以下。
T = 1 なら過不足なし）。見つけたグループは 1 つの正解にだけ当てる。コマごとに当たり（TP）・見逃し（FN）・誤り（FP）を数え、
全部のコマで足してから適合率・再現率・F1 を出す。あわせて、同じグループと見た 2 人の組（ペア）の適合率・再現率・F1 も出す。

見つけた結果の形（JSON）: {"frames": {"コマ": [[人, 人, ...], ...], ...}}。人は正解の名前（P0001 など）。
追跡の番号で書くときは "id_map": {"追跡の番号": "正解の名前"} を添える（対応しない番号は、正解にいない人として数える）。
評価するのは、結果に書いたコマだけ（書いたコマにグループがなければ [] を書く）。

  python -m twinsim group-eval <結果のフォルダ> <見つけた結果.json>
"""

import json
import math
from pathlib import Path

APART_M = 3.0  # outputs.APART_M と同じ


def load_gt(src):
    if isinstance(src, dict):
        return src
    p = Path(src)
    return json.loads((p / "ground_truth.json" if p.is_dir() else p).read_text())


def gt_groups(gt, frame, together_only=True):
    """そのコマの正解のグループ [set(名前), ...]（2 人以上）。"""
    out = []
    for g in (gt.get("groups") or {}).values():
        here = {}
        for n in g["members"]:
            p = gt["people"].get(n)
            if p is None:
                continue
            k = frame - p["start_frame"]
            tr = gt["tracks"][n]
            if 0 <= k < len(tr):
                here[n] = tr[k][:2]
        if together_only and len(here) >= 2:
            keep = {}
            for n, (x, y) in here.items():
                near = min(math.hypot(x - u, y - v) for m, (u, v) in here.items() if m != n)
                if near <= APART_M:
                    keep[n] = (x, y)
            here = keep
        if len(here) >= 2:
            out.append(set(here))
    return out


def match(truth, found, T=2 / 3):
    """1 コマの当たり・見逃し・誤り (TP, FN, FP)。truth・found は [set, ...]（found の 1 人の組は数えない）。"""
    found = [set(f) for f in found if len(f) >= 2]
    used = set()
    tp = 0
    for G in truth:
        need = math.ceil(T * len(G) - 1e-9)
        best = None
        for j, F in enumerate(found):
            if j in used:
                continue
            hit, extra = len(G & F), len(F - G)
            if hit >= need and extra <= len(G) - need and (best is None or hit - extra > best[0]):
                best = (hit - extra, j)
        if best is not None:
            used.add(best[1])
            tp += 1
    return tp, len(truth) - tp, len(found) - len(used)


def _pairs(groups):
    return {tuple(sorted((a, b))) for g in groups for a in g for b in g if a < b}


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4), "f1": None if f is None else round(f, 4),
            "tp": tp, "fp": fp, "fn": fn}


def evaluate(gt, found, thresholds=(2 / 3, 1.0), together_only=True):
    """gt: 結果のフォルダ・ground_truth.json の場所・その dict。found: 見つけた結果（上の形の dict か JSON の場所）。"""
    gt = load_gt(gt)
    if not isinstance(found, dict):
        found = json.loads(Path(found).read_text())
    id_map = {str(k): v for k, v in (found.get("id_map") or {}).items()}
    frames = found.get("frames") or {}
    counts = {T: [0, 0, 0] for T in thresholds}
    ptp = pfp = pfn = 0
    for f, groups in frames.items():
        f = int(f)
        pred = [{id_map.get(str(x), f"?{x}") if id_map else str(x) for x in g} for g in groups]
        truth = gt_groups(gt, f, together_only)
        for T in thresholds:
            tp, fn, fp = match(truth, pred, T)
            c = counts[T]
            c[0] += tp
            c[1] += fn
            c[2] += fp
        tp_pairs, pr_pairs = _pairs(truth), _pairs([g for g in pred if len(g) >= 2])
        ptp += len(tp_pairs & pr_pairs)
        pfp += len(pr_pairs - tp_pairs)
        pfn += len(tp_pairs - pr_pairs)
    out = {"frames": len(frames), "together_only": together_only, "source": "setti2015 (T = 2/3, 1)",
           "groups": {f"T={T:.3g}": _prf(c[0], c[2], c[1]) for T, c in counts.items()}, "pairs": _prf(ptp, pfp, pfn)}
    return out


def perfect(gt, stride=30, together_only=True):
    """正解そのものを、見つけた結果の形にしたもの（評価の確かめ・形の見本）。stride コマおき。"""
    gt = load_gt(gt)
    return {"frames": {str(f): [sorted(g) for g in gt_groups(gt, f, together_only)] for f in range(0, int(gt["total_frames"]), stride)}}
