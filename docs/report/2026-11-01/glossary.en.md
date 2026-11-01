<a id="top"></a>

# Glossary

[Contents](README.en.md#toc) ｜ [← Appendix](08_appendix.en.md) ｜ [日本語](glossary.md)

**On this page**: [EV wait](#ev-wait) · [Companion wait](#companion-wait) · [Sign check](#sign-check) · [Pass](#pass) · [Other](#other) · [Unknown](#unknown) · [Position rule](#position-rule) · [Spec rule](#spec-rule) · [Ask the VLM for the state](#vlm-state) · [Rule + VLM facing](#rule-plus-facing) · [Facing mapping](#facing-map) · [VLM](#vlm) · [Qwen3-VL-8B](#qwen) · [Tracking](#tracking) · [MOPF](#mopf) · [QAQS](#qaqs) · [QUBO](#qubo) · [BoostTrack](#boosttrack) · [twinsim](#twinsim) · [Isaac Sim](#isaac-sim) · [F1](#f1) · [95% interval](#ci) · [Accepted](#accept-rate) · [Person × 0.5 s](#person-step) · [Time to live](#ttl) · [Evidence interval](#evidence) · [Count error](#mae) · [GPUs per camera](#gpu-cards) · [Hall A](#hall-a-term) · [Hall B](#hall-b-term) · [Fixing the conditions](#conditions) · [Baseline evaluation](#baseline) · [Comparison](#comparison) · [Research question 2](#rq2)

<a id="g-states"></a>

## States

<a id="ev-wait"></a>

### EV wait

Stopped to wait for the elevator. State name `ev_wait`. → [The three methods](02_method.en.md#methods)

<a id="companion-wait"></a>

### Companion wait

Stopped to wait for someone. `companion_wait`. → [Successes](03_results.en.md#hits)

<a id="sign-check"></a>

### Sign check

Stopped to read the guide sign. `sign_check`. → [Successes](03_results.en.md#hits)

<a id="pass"></a>

### Pass

Walking through without stopping. `pass`.

<a id="other"></a>

### Other

None of the above. Very rare in the virtual scenes, and no method gets it right. `other`. → [Difference from the October values](06_limits.en.md#october)

<a id="unknown"></a>

### Unknown

Cannot be decided. In the ground truth, for example, when someone is hidden behind others. A method answering unknown counts as an error. `unknown`.

<a id="g-methods"></a>

## Methods

<a id="position-rule"></a>

### Position rule

Decides the state from where someone stopped: EV wait area means EV wait, in front of the sign means sign check, anywhere else means companion wait. Same idea as the October preliminary rule. → [The rule used as the baseline](03_results.en.md#fair-rule)

<a id="spec-rule"></a>

### Spec rule

Without a defined meeting place, answers "other" for people stopped outside the area. These scenes have no meeting place, so it cannot answer companion wait. → [The rule used as the baseline](03_results.en.md#fair-rule)

<a id="vlm-state"></a>

### Ask the VLM for the state

Shows 6 s of video and the trajectory, and has the VLM answer the state directly. → [The three methods](02_method.en.md#methods)

<a id="rule-plus-facing"></a>

### Rule + VLM facing

Asks the VLM which way someone faces, only for people the position rule sees as stopped, and uses that for the breakdown. → [The three methods](02_method.en.md#methods)

<a id="facing-map"></a>

### Facing mapping

The rule turning the VLM's facing answer into a state: door → EV wait, sign → sign check, anything else → companion wait. People chose it, after seeing Hall A.

<a id="g-tech"></a>

## Technology

<a id="vlm"></a>

### VLM

An AI that watches video and answers in text (Vision Language Model). Here it answers which way people face, or their state.

<a id="qwen"></a>

### Qwen3-VL-8B

The VLM used here. It ran on local GPUs.

<a id="tracking"></a>

### Tracking

Giving each person a number and following them across frames. Foot positions give speed and stop durations.

<a id="mopf"></a>

### MOPF

The detection and tracking system. Here it combines YOLO11m (detection), QAQS and BoostTrack.

<a id="qaqs"></a>

### QAQS

Chooses which overlapping person boxes to keep by solving a [QUBO](#qubo). The MOPF default. See [how detection works](../../methods.en.md).

<a id="qubo"></a>

### QUBO

An optimisation problem that minimises a quadratic expression of 0/1 variables. The research plan also uses it to select video for the VLM.

<a id="boosttrack"></a>

### BoostTrack

A tracking method that links detections across frames.

<a id="twinsim"></a>

### twinsim

The people-flow simulator for buildings (this repository). It computes movement and renders video with Isaac Sim.

<a id="isaac-sim"></a>

### Isaac Sim

NVIDIA's 3D simulator, used to render the virtual camera video.

<a id="g-eval"></a>

## Evaluation

<a id="f1"></a>

### F1

A metric that accounts for both misses and errors; 1 is perfect. "State F1" in this report is the macro average over five states.

<a id="ci"></a>

### 95% interval

A guide to the spread of a value, computed by resampling 60-second blocks (bootstrap). There are only 6 blocks, so treat the width as a rough guide.

<a id="accept-rate"></a>

### Accepted

The share where the method did not answer unknown.

<a id="person-step"></a>

### Person × 0.5 s

The evaluation unit: each person's judgement is compared with the ground truth every 0.5 s.

<a id="ttl"></a>

### Time to live

How long a VLM answer stays in use. It expires after 8 s and the rule's judgement takes over.

<a id="evidence"></a>

### Evidence interval

The time span a method cites as "this is what I saw, so this is the judgement". → [Stop times](04_timing_cost.en.md#timing)

<a id="mae"></a>

### Count error

The mean absolute difference from the true count (MAE).

<a id="gpu-cards"></a>

### GPUs per camera

GPU seconds per hour of video divided by 3,600. A guide to how many GPUs real-time use needs.

<a id="g-plan"></a>

## Scenes and plan

<a id="hall-a-term"></a>

### Hall A

Companions wait outside the EV wait area and the sign is a little away from the queue, so position tells the state fairly well. → [The two scenes](02_method.en.md#scenes)

<a id="hall-b-term"></a>

### Hall B

Companions wait inside the EV wait area and the sign is right next to the queue, so position does not tell the state well. → [The two scenes](02_method.en.md#scenes)

<a id="conditions"></a>

### Fixing the conditions

Deciding the state definitions and evaluation spec. Planned for the end of October. → [Schedule and status](01_status.en.md#schedule)

<a id="baseline"></a>

### Baseline evaluation

Obtaining the reference numbers on Takeshiba footage. Planned for November.

<a id="comparison"></a>

### Comparison

Comparing methods under the same conditions. Planned for December.

<a id="rq2"></a>

### Research question 2

Which video should limited compute go to? Compares even spacing, random, most uncertain and QUBO at the same budget.

---

[Contents](README.en.md#toc) ｜ [← Appendix](08_appendix.en.md) ｜ [Back to top](#top)
