<a id="top"></a>

# Issues and people flow

[Contents](README.en.md#toc) ｜ [← Timing and compute](04_timing_cost.en.md) ｜ [What we can and cannot say →](06_limits.en.md) ｜ [Glossary](glossary.en.md) ｜ [日本語](05_issues.md)

**On this page**: [Issues found](#issues) · [People flow](#flow)

<a id="issues"></a>

## Issues found

| Issue | Value (virtual hall) | What is happening |
|---|---|---|
| Counts when crowded | [Error](glossary.en.md#mae) 3.97 people (mean 10.8) | On average 4.5 people are hidden behind others, and each miss becomes count error. The VLM does not fix this |
| Groups | Found 0 of 26 | People walk together only briefly, and tracking ID switches break the pairs |
| Sign check (Hall B) | [F1](glossary.en.md#f1) 0.29 | Mixed up with people waiting for the EV right next to the sign |
| Companions inside the wait area | 3 of 13 clips | Not separated when the answer is "door" ([failures](03_results.en.md#misses)) |
| Judgement delay | 4.5–4.75 s | Answers come at the end of a clip ([gaps and delay](04_timing_cost.en.md#coverage)) |

<a id="flow"></a>

## People flow

"How many people at the entrance appear at the EV lobby, and how many minutes later?" was checked in a virtual office (5 min, 94 people, 2 cameras, [twinsim](glossary.en.md#twinsim)). This checks the procedure and is not a forecast for Takeshiba.

| Metric | Value |
|---|---|
| Gate count [error](glossary.en.md#mae) | 0.63 people (mean 2.3) |
| Gate direction [F1](glossary.en.md#f1) | 0.93 |
| EV lobby count error | 0.60 people (mean 4.5) |
| EV wait count error | 1.03 people |
| Share reaching the EV lobby within 5 min of entering | Truth 0.90, estimate 0.85 |
| Seconds until appearing (median) | Truth 12.4, estimate 12.4 |

For the scene and how it works, see the [10/24 report](../2026-10-24/README.en.md) and [how detection and linking work](../../methods.en.md).

---

[Contents](README.en.md#toc) ｜ [← Timing and compute](04_timing_cost.en.md) ｜ [What we can and cannot say →](06_limits.en.md) ｜ [Glossary](glossary.en.md) ｜ [Back to top](#top)
