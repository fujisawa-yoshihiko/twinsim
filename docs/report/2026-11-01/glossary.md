<a id="top"></a>

# 用語集

[目次](README.md#toc) ｜ [← 補足](08_appendix.md) ｜ [English](glossary.en.md)

**このページ**: [EV 待ち](#ev-wait)・[同行者待ち](#companion-wait)・[案内確認](#sign-check)・[通過](#pass)・[その他](#other)・[不明](#unknown)・[位置のルール](#position-rule)・[評価仕様どおりのルール](#spec-rule)・[VLM に状態を聞く](#vlm-state)・[ルール＋VLM の向き](#rule-plus-facing)・[向きの対応](#facing-map)・[VLM](#vlm)・[Qwen3-VL-8B](#qwen)・[追跡](#tracking)・[MOPF](#mopf)・[QAQS](#qaqs)・[QUBO](#qubo)・[BoostTrack](#boosttrack)・[twinsim](#twinsim)・[Isaac Sim](#isaac-sim)・[F1](#f1)・[95% 区間](#ci)・[受理率](#accept-rate)・[人 × 0.5 秒](#person-step)・[有効期限](#ttl)・[根拠の区間](#evidence)・[人数の誤差](#mae)・[GPU 枚分](#gpu-cards)・[広間 A](#hall-a-term)・[広間 B](#hall-b-term)・[条件確定](#conditions)・[基準評価](#baseline)・[比較検証](#comparison)・[研究課題 2](#rq2)

<a id="g-states"></a>

## 状態

<a id="ev-wait"></a>

### EV 待ち

エレベーターを待って止まっている状態。英語の状態名は `ev_wait`。→ [3 つの方式](02_method.md#methods)

<a id="companion-wait"></a>

### 同行者待ち

連れの人を待って止まっている状態。`companion_wait`。→ [当たりの例](03_results.md#hits)

<a id="sign-check"></a>

### 案内確認

案内板を見るために止まっている状態。`sign_check`。→ [当たりの例](03_results.md#hits)

<a id="pass"></a>

### 通過

止まらずに通り過ぎる状態。`pass`。

<a id="other"></a>

### その他

上のどれでもない状態。仮想の場面ではとても少なく、どの方式もほとんど当たらない。`other`。→ [10 月の値との違い](06_limits.md#october)

<a id="unknown"></a>

### 不明

決められない状態。正解の側では手前の人に隠れているときなど。方式が不明と答えると、評価では誤りに数える。`unknown`。

<a id="g-methods"></a>

## 方式

<a id="position-rule"></a>

### 位置のルール

止まった場所で状態を決める方式。EV 待ちエリアなら EV 待ち、案内板の前なら案内確認、それ以外で止まれば同行者待ち。10 月の予備実験のルールと同じ考え方。→ [比べる相手のルール](03_results.md#fair-rule)

<a id="spec-rule"></a>

### 評価仕様どおりのルール

決まった待ち合わせ場所がなければ、エリアの外で止まった人を「その他」と答えるルール。この場面には待ち合わせ場所がないので同行者待ちを答えられない。→ [比べる相手のルール](03_results.md#fair-rule)

<a id="vlm-state"></a>

### VLM に状態を聞く

6 秒の映像と軌跡を見せて、状態を VLM に直接答えさせる方式。→ [3 つの方式](02_method.md#methods)

<a id="rule-plus-facing"></a>

### ルール＋VLM の向き

位置のルールで止まっている人だけ VLM に向きを聞き、状態の内訳を決める方式。→ [3 つの方式](02_method.md#methods)

<a id="facing-map"></a>

### 向きの対応

VLM の答えた向きを状態に直す決まり。扉 → EV 待ち、案内板 → 案内確認、それ以外 → 同行者待ち。人が決めたもので、広間 A の結果を見て決めた。

<a id="g-tech"></a>

## 技術

<a id="vlm"></a>

### VLM

映像を見て文章で答える AI（Vision Language Model）。ここでは人の向きや状態を答えさせる。

<a id="qwen"></a>

### Qwen3-VL-8B

今回使った VLM。ローカルの GPU で動かした。

<a id="tracking"></a>

### 追跡

映像の中の人に番号を付けて、コマをまたいで追うこと。足元の位置から速さや止まった時間が分かる。

<a id="mopf"></a>

### MOPF

検出と追跡の仕組み。今回は YOLO11m（検出）・QAQS・BoostTrack の組み合わせ。

<a id="qaqs"></a>

### QAQS

重なった人の枠のうち、残す組み合わせを [QUBO](#qubo) で選ぶ処理。MOPF の既定。仕組みは[検知の説明](../../methods.md)。

<a id="qubo"></a>

### QUBO

0 か 1 の変数の 2 次の式を最小にする形の最適化問題。研究計画では、VLM に入れる映像の選び方にも使う。

<a id="boosttrack"></a>

### BoostTrack

コマの間で検出をつなぐ追跡の方法。

<a id="twinsim"></a>

### twinsim

建物の人流のシミュレータ（このリポジトリ）。人の動きを計算し、Isaac Sim で映像にする。

<a id="isaac-sim"></a>

### Isaac Sim

NVIDIA の 3D シミュレータ。仮想のカメラの映像を描くのに使う。

<a id="g-eval"></a>

## 評価

<a id="f1"></a>

### F1

見逃しと誤りの両方を見る指標。1 が満点。この報告の「状態の F1」は 5 つの状態の F1 の平均（マクロ平均）。

<a id="ci"></a>

### 95% 区間

値のばらつきの目安。60 秒ごとのかたまりで作り直して計算した（ブートストラップ）。かたまりが 6 個しかないので幅は目安。

<a id="accept-rate"></a>

### 受理率

方式が不明と答えなかった割合。

<a id="person-step"></a>

### 人 × 0.5 秒

評価の単位。一人ひとりについて 0.5 秒ごとに判定を正解と比べる。

<a id="ttl"></a>

### 有効期限

VLM の答えを使い続ける時間。8 秒で切れ、切れたらルールの判定に戻る。

<a id="evidence"></a>

### 根拠の区間

方式が「この時間にこう見えたので、こう判定した」と示す時間の区間。→ [止まった時刻](04_timing_cost.md#timing)

<a id="mae"></a>

### 人数の誤差

正解の人数との差の絶対値の平均（MAE）。

<a id="gpu-cards"></a>

### GPU 枚分

映像 1 時間の処理に要る GPU の秒数を 3,600 で割った値。実時間で動かすのに要る枚数の目安。

<a id="g-plan"></a>

## 場面と計画

<a id="hall-a-term"></a>

### 広間 A

同行者が EV 待ちエリアの外で待ち、案内板が待ち列から少し離れている場面。位置で状態が分かりやすい。→ [2 つの場面](02_method.md#scenes)

<a id="hall-b-term"></a>

### 広間 B

同行者が EV 待ちエリアの中で待ち、案内板が待ち列のすぐ隣にある場面。位置で状態が分かりにくい。→ [2 つの場面](02_method.md#scenes)

<a id="conditions"></a>

### 条件確定

状態の定義と評価仕様を決めること。計画では 10 月末。→ [予定と今の状況](01_status.md#schedule)

<a id="baseline"></a>

### 基準評価

竹芝の映像で、比べる元になる数値を取ること。計画では 11 月。

<a id="comparison"></a>

### 比較検証

方式を同じ条件で比べること。計画では 12 月。

<a id="rq2"></a>

### 研究課題 2

限られた計算を、どの映像に使うかという問い。等間隔・ランダム・不確実性の上位・QUBO を同じ予算で比べる。

---

[目次](README.md#toc) ｜ [← 補足](08_appendix.md) ｜ [ページの先頭へ](#top)
