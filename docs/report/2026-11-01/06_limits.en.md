<a id="top"></a>

# What we can and cannot say

[Contents](README.en.md#toc) ｜ [← Issues and people flow](05_issues.en.md) ｜ [What comes next →](07_next.en.md) ｜ [Glossary](glossary.en.md) ｜ [日本語](06_limits.md)

**On this page**: [What we can say](#can) · [What we cannot say](#cannot) · [Difference from the October values](#october)

<a id="can"></a>

## What we can say

- The procedure runs from video through tracking and the VLM to evaluation, and every metric in the evaluation spec comes out.
- In the two virtual scenes, the VLM's facing answer wins only where position does not tell.
- The current VLM ([Qwen3-VL-8B](glossary.en.md#qwen)) cannot give stop times.

<a id="cannot"></a>

## What we cannot say

| What we cannot say | Why |
|---|---|
| Performance at Takeshiba | There is no real footage yet |
| Whether facing is a useful cue for real people | Virtual companion waiters are set to face where the other person will come from; the scene's author decided that |
| Whether the VLM understands companions | Its answer is the observation "facing neither the door nor the sign"; people chose the [mapping](glossary.en.md#facing-map) |
| Whether the position rule's value holds in reality | The virtual scenes have almost nobody stopping for other reasons, such as a phone call or a chat |
| Variability | Two virtual scenes, one VLM, one generation |
| Effects of light, belongings and clothing | No backlight or lighting change; 10 character models |

<a id="october"></a>

## Difference from the October values

| | Hall A position rule | Hall A facing | Hall B position rule | Hall B facing |
|---|---|---|---|---|
| October preliminary | 0.80 | 0.78 | 0.64 | 0.70 |
| This report | 0.59 | 0.53 | 0.42 | 0.49 |

The ranking is the same (the position rule leads in Hall A, facing in Hall B). Values look lower because the unit changed (clip → [person × 0.5 s](glossary.en.md#person-step)) and so did the states averaged (six → five), so the two cannot be compared directly.
The [other](glossary.en.md#other) state, which no method gets right, also pulls the mean down.

---

[Contents](README.en.md#toc) ｜ [← Issues and people flow](05_issues.en.md) ｜ [What comes next →](07_next.en.md) ｜ [Glossary](glossary.en.md) ｜ [Back to top](#top)
