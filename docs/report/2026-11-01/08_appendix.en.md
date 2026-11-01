<a id="top"></a>

# Appendix

[Contents](README.en.md#toc) ｜ [← What comes next](07_next.en.md) ｜ [Glossary →](glossary.en.md) ｜ [Glossary](glossary.en.md) ｜ [日本語](08_appendix.md)

**On this page**: [All numbers](#all-numbers) · [Materials and credits](#credits) · [How this report was made](#how-built)

<a id="all-numbers"></a>

## All numbers

F1 is the mean over five states, with [unknown](glossary.en.md#unknown) counted as an error. Bold marks the highest of the four compared methods. [Accepted](glossary.en.md#accept-rate) is the share where the method did not answer unknown. The right five columns are per-state F1.

| Scene | Method | F1 (95% interval) | Accepted | Companion wait | Sign check | EV wait | Pass | Other |
|---|---|---|---|---|---|---|---|---|
| Hall A | Spec rule | 0.434 (0.41–0.45) | 1.00 | 0.00 | 0.65 | 0.90 | 0.61 | 0.03 |
| Hall A | Position rule | **0.594** (0.57–0.61) | 1.00 | 0.83 | 0.65 | 0.90 | 0.61 | 0.00 |
| Hall A | Ask the VLM for the state | 0.403 (0.39–0.42) | 0.99 | 0.00 | 0.50 | 0.90 | 0.62 | 0.00 |
| Hall A | Combined | 0.421 (0.40–0.44) | 0.99 | 0.00 | 0.59 | 0.87 | 0.59 | 0.05 |
| Hall A | Rule + VLM facing | 0.533 (0.51–0.55) | 1.00 | 0.62 | 0.59 | 0.86 | 0.61 | 0.00 |
| Hall A | Rule + facing (video only) | 0.499 (0.47–0.53) | 1.00 | 0.43 | 0.62 | 0.85 | 0.61 | 0.00 |
| Hall B | Spec rule | 0.298 (0.29–0.31) | 1.00 | 0.00 | 0.00 | 0.84 | 0.64 | 0.01 |
| Hall B | Position rule | 0.415 (0.39–0.44) | 1.00 | 0.59 | 0.00 | 0.84 | 0.64 | 0.00 |
| Hall B | Ask the VLM for the state | 0.359 (0.33–0.38) | 0.99 | 0.00 | 0.24 | 0.85 | 0.66 | 0.05 |
| Hall B | Combined | 0.354 (0.33–0.38) | 0.99 | 0.00 | 0.28 | 0.82 | 0.62 | 0.04 |
| Hall B | Rule + VLM facing | **0.487** (0.42–0.53) | 0.99 | 0.62 | 0.29 | 0.83 | 0.64 | 0.05 |

The source file is [data/numbers.json](data/numbers.json).

<a id="credits"></a>

## Materials and credits

- All videos come from a virtual space made with [NVIDIA Isaac Sim](glossary.en.md#isaac-sim). No Takeshiba footage or drawings are used.
- Spaces: Isaac Sim Hospital and Office ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)), with people added and rendered as camera video.
- People: the virtual character models bundled with Isaac Sim (10 types). Only scenes without clothing colour changes appear here.
- The VLM ran on local GPUs; no video was sent to an outside service.

Terms for the character models (as checked on 2026-11-01; this is not a legal review):

- The model folders have no LICENSE file, so they fall under the [NVIDIA Isaac Sim Additional Software and Materials License](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/common/license-isaac-sim-additional.html).
- That license restricts distributing and modifying the materials themselves, and does not mention rendered video.
- The [License FAQ](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/common/license-faq.html) says no additional license is needed for outputs (videos, reports, data) of a simulation run internally.

<a id="how-built"></a>

## How this report was made

`build_github_report.py` in the research folder (`~/MOPF_ALL_video/research/slides/partner_update_2026-11-01/`, local git only) builds the pages from the source text in `github_src/` and the result files.
No number was copied by hand. Video clips are cut from the output of `make_videos.py` in the same folder. Everything runs on the CPU; no GPU is used.

---

[Contents](README.en.md#toc) ｜ [← What comes next](07_next.en.md) ｜ [Glossary →](glossary.en.md) ｜ [Glossary](glossary.en.md) ｜ [Back to top](#top)
