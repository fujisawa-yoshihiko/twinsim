# twinsim 1.1

[日本語](release-1.1.md)

This version replaces the movement with "movement in which people do not collide" and can produce ground truth from rendered video for training and evaluating detection and tracking (visible-part boxes and occlusion ratios).
It summarises the implementation and changes since 1.0 (2026-11-02) and the results of the checks.

## What 1.1 includes

### Movement (sections 5.1–5.5 of docs/validity.en.md)

- The default movement is now the Collision-Free Speed Model (Tordeux et al. 2016) (`people.motion_model: cfsm`). The 1.0 movement is available as `people.motion_model: lane`.
  Speed is set from the free space up to the person ahead, and the walking direction adds a push away from nearby people and walls. Bodies overlap or pass through each other much less ([5.1](validity.en.md#51-movement-in-which-people-do-not-collide-2026-11-05-peoplemotion_model-cfsm)).
- No more people stuck at doors, gates and elevator doors: traffic through a door uses two lines, one for people entering and one for people leaving; when people block each other in front of a gate, queue order and lanes are swapped;
  a person who cannot move asks standing people ahead to make way; a safety valve (after 15 s without progress, walk for 2 s without avoiding people) ([5.2](validity.en.md#52-no-more-people-stuck-at-doors-gates-and-elevator-doors-2026-11-06), [5.3](validity.en.md#53-entrance-order-a-second-entering-line-gate-queues-crowding-in-front-of-elevators-and-how-the-checks-measure-evening-of-2026-11-06)).
- First-come order at entrances and a second entering line (`motion.entry_alt`); people stop 0.65 m behind the end of a gate queue; group members wait at the place where they stop; elevators are boarded in two files.
- When the waiting area is full, people wait where they are at least 0.6 m from others. People waiting for an elevator move away from an unrelated neighbour closer than 0.45 m ([5.4](validity.en.md#54-people-waiting-for-an-elevator-standing-in-contact-with-a-neighbour-and-destinations-on-the-near-side-of-a-gate-2026-11-07)).
- Walkers no longer shake back and forth in place. The `moving` flag and body direction written out are decided from the speed smoothed over 0.3 s ([5.5](validity.en.md#55-walkers-shaking-back-and-forth-in-place-2026-11-08)).
- New configuration errors: cameras above the ceiling (the space's `ceiling_m`), and destinations that cross a gate line again after passing the gate.

### Rendering and ground truth (Isaac Sim)

- `twinsim.render(..., labels=True)` writes ground truth `labels/<camera>.csv` for the same frames that were rendered ([formats.en.md, section 4](formats.en.md#4-camera-boxes)):
  the box around the visible pixels, the full-body box, visibility, occlusion, the share outside the image, entrance/exit areas, state, and the share behind frosted glass.
- The occlusion ratio is counted from the visible pixels and the full-body pixels re-rendered without the background and other people (Replicator's `occlusionRatio` is not computed for these character models).
  Occlusion behind frosted glass is computed (`twinsim/glass.py`, the space's `glass`). Boxes that Replicator returns under the wrong name are checked against the simulated boxes and renamed (`labels/identity.json`).
- People outside their time on stage are parked under the floor (park, the default). The frames before a segment are discarded (`preroll`), and only people near the camera are placed (`cull`).
- Spaces can place an elevator car and door frame when rendering (`prop: elevator` on an `elevator`, `blocked` in `levels`, `cabin_m`). Entrances and exits can have a `hidden` point (people walk in from, or out to, beyond a door).
- Parallel rendering: `tools/render_farm.sh` starts several rendering-only Isaac Sim instances per GPU, splits one rendering by camera and time (`chunk_s`) and joins the parts when they are complete.
  With 8 instances on one GPU, capture is 4.0 times as fast as with one. Hung receivers are restarted.

### Comparison with the literature (validity)

- Free walking speed is compared with the speeds given to those people. Arrivals include people who arrived but waited outside a blocked entrance. The gate headway is measured while a queue exists.
  Dyads exclude time in gate queues. The spacing check counts only people standing and waiting, and people who went away and came back are not counted as stuck (the measurements were fixed; [5.3](validity.en.md#53-entrance-order-a-second-entering-line-gate-queues-crowding-in-front-of-elevators-and-how-the-checks-measure-evening-of-2026-11-06)).
- Checks are skipped or widened when samples are small ([5.6](validity.en.md#56-checks-with-few-samples-2026-11-12)).
- A tool for comparing movement before and after a change, `tools/crowd_check.py` (runs the templates with the same seeds and summarises verdicts, overlap and run time).

### Changes in output formats ([formats.en.md](formats.en.md))

- `labels/` (the rendered ground truth above) was added.
- How `moving` in `ground_truth.json` is decided (from the speed smoothed over 0.3 s; walking starts above 0.2 m/s and stops below 0.1 m/s).
- `summary.json` has `motion` (such as the number of safety-valve uses) and `outside_at_end` (people still waiting outside an entrance at the end).
- `validity.json` has more items (`given_all` for free walking speed, `n_pairs` for dyads, `standing_spacing`, `gridlock` and others).

## Differences from 1.0

- **The same configuration and seed give different movement from 1.0** (the default movement changed). Use `people.motion_model: lane` for the 1.0 movement.
- 1.0 configurations load unchanged (checked with the 13 templates and the example configuration). However, a camera at or above the space's ceiling − 0.05 m is now an error (the office ceiling is 3.0 m).
- The `mot/` boxes of 1.0 (projected boxes, an approximation) are still written. Use `labels/` for ground truth of rendered video (the 1.0 check found the `mot/` boxes about 1.4 times wider than detector boxes).

## What was verified

### Automated checks (`tools/release_check.sh` and others)

- Style (ruff) and automated tests (pytest, 180 tests). GitHub CI (Python 3.10 and 3.13, installing from the wheel)
- The wheel installed into clean environments (Python 3.10 and 3.13) gives the same ground truth (`ground_truth.json`) for the same configuration and seed across Python versions and across processes
- 1.0 configurations load unchanged (the 13 templates of 1.0 and the example configuration)
- Same movement as corpus v6 (two v6 cases rerun with 1.1 give identical trajectories and `moving`)
- No secrets (the working tree and the diff of all commits since 1.0, with detect-secrets). No known vulnerabilities in the 40 dependencies (pip-audit, versions from `uv.lock`)
- No specific company or building names (the diff since 1.0)

### Comparison with 1.0 (same templates and seeds, both counted with the 1.1 checks)

1.0 (b5c7af1) and 1.1 ran the nine templates (`verify_*` with seeds 0–8, the three elevator scenes with seeds 1–16; 102 runs each).
Results and tools are in the developer's local data area (`~/dt-data/twinsim/crowd_check/release_1.1/`, not in the repository).

| Template | Runs | Stuck people (total) | Pairs with centres closer than 0.3 m (per 1,000 person-frames) | Shaking in place (per 1,000 person-seconds) | Dyads pass | Spacing of waiting people passes | Arrivals pass |
|---|---:|---:|---:|---:|---|---|---|
| `verify_bottleneck` | 9 | 810 → 0 | 2.593 → 0.157 | 44.1 → 5.6 | — | — | 8/9 → 9/9 |
| `verify_gate_capacity` | 9 | 24 → 0 | 11.491 → 0 | 0.8 → 2.5 | 7/8 → 7/9 | 9/9 → 9/9 | 6/9 → 9/9 |
| `verify_counterflow` | 9 | 0 → 0 | 0.121 → 0 | 0 → 3.1 | — | — | 9/9 → 9/9 |
| `verify_corridor_speed`, `verify_fundamental_diagram`, `verify_groups` | 27 | 0 → 0 | 0.000 → 0.001 | 0 → 0.1 | 9/9 → 9/9 | — | 27/27 → 27/27 |
| `office_gate_ev` | 16 | 0 → 0 | 2.928 → 0.042 | 0.3 → 2.8 | 15/16 → 11/16 | 16/16 → 16/16 | 16/16 → 16/16 |
| `office_ev_hall` | 16 | 4 → 0 | 3.669 → 0.020 | 0.5 → 4.8 | 15/16 → 13/16 | 15/16 → 16/16 | 16/16 → 16/16 |
| `hospital_gate_ev` | 16 | 0 → 0 | 7.180 → 0.156 | 0.3 → 5.6 | 14/16 → 13/16 | 13/16 → 16/16 | 16/16 → 16/16 |

- Better: stuck people 838 → 0 (seed 1 of `verify_bottleneck` jammed in 1.0 and took 23 minutes to compute). Overlap fell to 1/16–1/180 of 1.0 or to 0 (only `verify_groups` went 0.001 → 0.004).
  Steps larger than 0.2 m in one frame: 0–0.21% → 0 in `verify_*`, and 0.05–0.08% → 0.003% in the three elevator scenes (the rest is listed under known limitations).
  The `verify_bottleneck` flow is 2.10 → 1.91 people/(m·s) (experiments 1.90–2.19).
- Worse: shaking in place (the 1.0 movement does not shake because bodies overlap and pass through each other; apart from `verify_bottleneck`, 0–0.8 → 0–5.6),
  dyads passing 60/65 → 53/66, and free walking speed passing in `verify_bottleneck` 9/9 → 7/9.
- The difference in arrivals (four "caution" verdicts in 1.0) is because 1.0 does not write out people waiting outside an entrance (counted with the 1.1 checks).

### Checks of a rendered corpus (corpus v6: 6 cases × 9 cameras × 60 s, matched with YOLO11m and ByteTrack)

- 0 rendering failures, 0 annotations outside people's time on stage
- Median IoU of correctly found people 0.97. Share of rows labelled "hidden" that the detector finds: 0% (198 rows). Detections without ground truth: 2.8 per 1,000 frames (none where nobody is)
- Detection AP50 0.94 and AP 0.84; tracking (h25p25) MOTA 0.85 and IDF1 0.70
- Compared with v5 (before the shaking fix), shaking in the rendered 60 s summed over the six cases is 761.6 → 94.9 person-seconds, and pairs × frames with centres closer than 0.3 m are 76 → 12
- The only "caution" verdict is the dyad distance in office elevator mid (1.13 m)

## Known limitations

- Dyads can walk side by side 2–4 m apart. Groups keep together along the walking direction, but nothing controls how far apart they are sideways
  (5.6; the dyad distance is "caution" in 15 of the 129 template runs).
- In front of a crowded elevator, 8–16% of people take more than 10 s to board. A person heading for the elevator can go into the waiting people through the safety valve and stop among them (5.4, 5.5).
- Inside a crowd of waiting people, a little shaking in place remains (1–3 s per episode in front of elevators in corpus v6; 5.5).
- People boarding an elevator or leaving to beyond a door can jump up to about 1 m in one frame in front of the door (when they are more than 0.55 m away from the line through the door after avoiding people, they are put back near the line;
  205 times in the 48 runs of the three elevator templates, and once, 0.30 m, in the rendered part of corpus v6).
- In front of the office gates with many people, people appearing at and leaving through the south exit block each other head-on and get through by the safety valve.
- The rendered "visible-part box" encloses all visible pixels, so for a person whose legs are visible between other people, a detection around the upper body may not reach IoU 0.5.
- Remaining from 1.0: a camera's `clock_offset_s` and `drop_rate` are only recorded. `gate_events` times are when the head of the queue starts moving. `boarded` includes people who could not board.
  Destinations are place names only.
- Spaces: your own spaces can be used, but the walkable grid (`.txt` or `.npz`) must be made by hand (there is no tool to make it from a floor plan or polygons). Rendering video needs a USD scene. One level only.
  `simple_room` renders black from inside.

## Next versions

Draft goals and decisions to make are in [roadmap.en.md](roadmap.en.md).

- 1.2 (goals to be decided): group features (lateral cohesion of dyads, strangers not passing between members, formation, splitting and rejoining, relations and roles),
  components other than elevators that are the purpose of a trip (counters, called waiting, rooms, seating and others derived from offices, hospitals and warehouses), fixes for the known limitations above, building spaces from polygons
- 1.3: two or more cameras (matching people across cameras at different places, ground truth and evaluation of flows of counts, camera clock offsets and dropped frames)
