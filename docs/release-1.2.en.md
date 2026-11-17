# twinsim 1.2

[日本語](release-1.2.md)

This version adds groups (relations, formation, splitting and rejoining) and components other than elevators that are the purpose of a trip (counters, called waiting, seating, rooms and work points),
with templates for a hospital outpatient clinic, office lunchtime and a warehouse shift start. It also includes the remaining movement fixes from 1.1 and building a space by writing the walkable area as polygons.
It summarises the implementation and changes since 1.1 (2026-11-12) and the results of the checks.

## What 1.2 includes

### Groups (section 5.8 of docs/validity.en.md)

- Each group has a relation (colleagues, friends, family or companion; `people.group_relation`), and each member has a slot relative to the leader (the first to appear).
  Dyads walk abreast at the spacing of their relation, triads in a V, four or more in two rows (provisional). The lateral spread narrows with the surrounding density as in the literature formula (Zanlungo et al. 2015), and members walk in file where it is narrow
  ([5.8](validity.en.md#58-group-formation-12-2026-11-12)).
- Followers join the leader's route. Strangers avoid the line between members (they do not pass between members).
- At gates, members prefer the lane their mates queue in, and those through first wait for the rest just beyond the gate (state `group_wait`). A group boards the same elevator car and waits for the next one together if not everyone fits.
  People waiting for an elevator wait next to their mates.
- The ground truth has `groups` (members, relation, leader, intervals apart), a per-person `relation` and the event `regroup`. The judgements add the dyad distance by relation, the lateral spread by density and
  the number of times a stranger crossed between members (reference).
- Evaluation for the group-finding task (group detection and tracking): `python -m twinsim group-eval` (precision, recall and F1 with the criterion of Setti et al. 2015, and the F1 of pairs;
  [library.en.md](library.en.md#evaluating-a-group-finding-task)).

### Components that are the purpose of a trip (5.9, 5.11, 5.12)

- Counters (`services`): a queue (`line`), first come first served in an area (`area`) or calling (`call`: people sit and wait and are called as places free up). The number of service places and the service time go in the configuration.
  A place where people work standing (the packing tables of the warehouse) can be written as a counter with a state name (`state: work`) ([5.9](validity.en.md#59-components-that-are-the-purpose-of-a-trip-12-2026-11-13),
  [5.12](validity.en.md#512-warehouse-shift-start-work-points-with-a-capacity-and-a-queue-and-the-state-while-walking-to-a-queue-12-2026-11-16)).
- Seating (`seats` in a space): people walk to a free seat and sit; if all are taken they stand nearby. Seats can be made on furniture (`furniture`).
- Rooms (`rooms`): a door, a capacity and a time inside. People inside are not seen (their ground-truth boxes stop too) and come out with the same person number.
- `visits` in a destination: choose n places from the candidates with a name prefix and visit them in the order of their numbers (warehouse shelves).
- Routes of people going elsewhere avoid the front of counters where possible ([5.11](validity.en.md#511-routes-avoiding-the-front-of-counters-office-lunchtime-coffee-counter-and-folds-when-members-join-the-leaders-route-12-2026-11-16)).
- Three new templates: `hospital_outpatient` (hospital outpatients, 30 min: reception → waiting area → consultation room → cashier → pharmacy; consultation times from the MHLW Patient's Behavior Survey),
  `office_lunch` (office lunchtime, 30 min: gates, elevators, a queue at a coffee counter and sofas), `warehouse_shift` (warehouse shift start, 20 min: a queue at the time clock, waiting for instructions, visiting shelves and packing tables).
  Values without literature (service times, arrival volumes and others) are provisional (the ledger in section 6 of validity.en.md).
- Added to the spaces: in the hospital, reception, cashier, pharmacy, benches in the waiting areas, five consultation rooms and cameras `CamClinic` and `CamWaiting`; in the office, a coffee counter, sofas and camera `CamCafe`;
  in the warehouse, a time clock, packing tables, break benches and camera `CamDock`.

### Rendering (5.10–5.12)

- Sitting motion (NVIDIA Isaac Sim People's `SitAndStandChair` retargeted to the character skeleton). The simulation sits down and stands up along the body trajectory of the asset, so the ground-truth position and the rendered body agree
  ([5.10](validity.en.md#510-checking-the-rendering-sitting-benches-consultation-room-doors-and-people-inside-rooms-12-2026-11-16)).
- Furniture: benches, sofas (`sofa3`), counters (`counter2`) and packing tables (`pack_table`). Furniture not in the USD is placed by the renderer.
- Consultation-room doors open only when someone passes (`door_prim`). People inside rooms are put under the floor and do not appear in the rendered ground truth (`labels/`).
- The ground-truth box of a seated person uses the seated height and includes the knees and feet that stick out in front.

### Remaining movement fixes from 1.1 (5.7, 5.13)

- The step that put people back near the line through a door could jump up to about 1 m in one frame; fixed ([5.7](validity.en.md#57-the-step-that-puts-people-back-near-the-line-through-a-door-jumped-2026-11-12)).
- The boarding tail at crowded elevators: people standing on the way to the door of someone boarding or alighting step aside before being asked. The distance at which a blocked person asks others to make way is 0.9 → 1.2 m
  ([5.13](validity.en.md#513-remaining-movement-fixes-from-11-the-boarding-tail-at-elevators-shaking-among-waiting-people-and-the-south-exit-12-2026-11-16-to-17)).
- Shaking among waiting people: two fixed repeating patterns were removed (a person boarding from beside the door heading for the corner of the car box; a person making way repeatedly stepping aside and back).
- An exit (`kind: exit`) that is also the origin of a stream now has two lines, one for people coming in and one for people going out (the jam at the south exit of the office).
- Detecting being stuck: people walking a long detour were treated as stuck while walking normally and used the safety valve. Now a shrinking remaining route length also counts as progress (5.9; affects all templates).

### Building a space ([“Writing polygons” in spec.en.md](spec.en.md#writing-polygons-from-12))

- Writing the walkable area as polygons `{res, outline, holes}` (outline and holes: point lists, `rect` or `circle`) builds the grid. A shape thinner than `res` would vanish from the grid, so it is an error.
- The configuration's `space` can be the space itself (a dict) or the path of a YAML or JSON file describing it. In Python, `twinsim.load_space` reads and checks it before you pass it in
  ([library.en.md](library.en.md#your-own-space), example `examples/08_space_from_polygons.py`).
- If a point of a place in the space (entrance, exit, stop or elevator) is outside the walkable area, it is an error before the simulation.
- `show-space` draws a plan from the grid for a space without a top view. The GUI can use polygon spaces too (the map is shown only for spaces with a top view).

### Changes to the output formats ([formats.en.md](formats.en.md))

- `ground_truth.json`: `groups`, per-person `relation` and `sit` (intervals of the sitting motion), `sit_clip`, and the events `regroup`, `service`, `room`, `seat` and `call`.
  States `group_wait`, `service_queue`, `service`, `call_wait`, `seated` and `in_room` (and names given with a destination's `state`). When the configuration contains the space itself, `space` is its `name`.
- `frames.csv.gz`: a column `pose` (`walk`, `stand`, `sit`, `sit_down`, `stand_up`) is added at the end. Rows inside rooms (`in_room`) are not written.
- `mot/` and `labels/`: a seated person's box uses the seated height. People inside rooms are not written.
- `3_dwell` in `tasks.json`: now every state except the walking states and inside a room (before, it listed stopping states and missed the warehouse's `work` and `wait`; results of `warehouse_picking` change).
- `summary.json`: `inputs.services` and new states in `state_seconds`. `validity.json`: `group_formation` (lateral spread by density, crossings between members) and `by_relation` for dyads.

## Differences from 1.1

- **With the same configuration and seed, the movement can differ from 1.1.** Templates with groups draw a relation, so the order of random numbers changes. Group slots, the elevator fixes (5.13)
  and the furniture added to spaces also change the movement. The four `verify_*` templates without groups and `office_smoke` give exactly the same tracks as 1.1 (comparison below).
- 1.1 configurations are read as they are. The 13 templates of 1.1 are the same files in 1.2 and run unchanged. The 1.1 examples (01–03 and 05–07 in `examples/`; 04 is rendering) were run with 1.2.
  However, the following are now errors before the simulation:
  - a point of a place in the space (entrance, exit, stop or elevator) outside the walkable area (all places of the bundled spaces are inside)
  - candidates chosen by a destination's name prefix that mix places of different kinds (5.9; the bundled spaces are named so that they do not mix)
- Furniture added to the spaces changes the walkable area slightly even for templates that do not use components: the coffee counter along the east wall of the office lobby, benches in the hospital lobby and in front of the consultation rooms,
  and the packing tables and break benches of the warehouse (the floor footprint of furniture placed by the renderer is removed from the walkable area).
- The spaces the GUI accepts from the browser are only the names in the list or spaces written as polygons (dicts) (in 1.1, a folder path on the server could also be given).
- The output formats only gain items, and the meaning of the 1.1 items is unchanged, except that `3_dwell` in `tasks.json` counts different states (see "Changes to the output formats" above).

## What was checked

### Automatic checks (`tools/release_check.sh` and others)

- Style (ruff) and automatic tests (pytest, 230 tests). GitHub CI (Python 3.10 and 3.13, installing from the wheel and running)
- The wheel installed into clean environments (Python 3.10 and 3.13) and run: with the same configuration and seed, the ground truth (`ground_truth.json`) is the same across Python versions
- 1.1 configurations are read as they are (the 13 templates of 1.1 computed in the comparison below, and the 6 examples run with 1.2)
- No secrets (detect-secrets on the working tree). No known vulnerabilities in the dependencies (pip-audit, the versions in `uv.lock`)
- No names of specific companies or buildings (the changes since 1.1)

### Comparison with 1.1 (same templates and seeds, both counted with the 1.2 judgements)

The 13 templates of 1.1 were computed with 1.1 (v1.1.0) and 1.2 with the same seeds (seeds 0–8 for `verify_*`, 1–16 for the three elevator templates, 1–8 for the others; 134 runs each).
Results and tools are in the developer's local data folder (`~/dt-data/twinsim/crowd_check/release_1.2/`; not in the repository).

- `verify_bottleneck`, `verify_corridor_speed`, `verify_counterflow` and `verify_fundamental_diagram` (36 runs), which have no groups, and `office_smoke` (8 runs) give exactly the same tracks as 1.1.
  `simple_room_smoke` gives the same tracks in 7 of 8 runs; in one, positions drift slightly from 13 s (because 5.13 changed the distance at which a blocked person asks others to make way from 0.9 to 1.2 m; with 0.9 m it is the same).
- Stuck people: 0 → 0 in every template.

| Template | Runs | Safety valve (per run) | Pairs with centres under 0.3 m (per 1,000 person-frames) | Shaking in place (per 1,000 person-seconds) | Taking over 10 s to board | Largest step | Dyads within range | Lateral spread within range | Standing spacing within range |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| `verify_gate_capacity` | 9 | 0.78 → 0.11 | 0 → 0 | 2.5 → 2.8 | — | 0.08 → 0.08 m | 7/9 → 9/9 | 1/9 → 6/9 | 9/9 → 9/9 |
| `verify_groups` | 9 | 0 → 0 | 0.004 → 0.002 | 0 → 0 | — | 0.07 → 0.08 m | 9/9 → 9/9 | 0/9 → 8/9 | — |
| `office_gate_ev` | 16 | 0.88 → 0.38 | 0.042 → 0.000 | 2.8 → 3.6 | 8.2% → 1.4% | 1.01 → 0.08 m | 11/16 → 16/16 | 8/15 → 16/16 | 16/16 → 16/16 |
| `office_ev_hall` | 16 | 1.94 → 0.50 | 0.020 → 0.007 | 4.8 → 4.0 | 17.7% → 7.4% | 1.00 → 0.08 m | 13/16 → 16/16 | 9/16 → 12/16 | 16/16 → 16/16 |
| `hospital_gate_ev` | 16 | 3.75 → 0.31 | 0.157 → 0.000 | 5.6 → 3.9 | 10.9% → 1.9% | 0.93 → 0.08 m | 13/16 → 16/16 | 5/16 → 16/16 | 16/16 → 15/16 |
| `office_signage_ab` | 8 | 0.12 → 0 | 0 → 0 | 1.5 → 2.3 | 3.4% → 0% | 0.84 → 0.07 m | 6/6 → 6/6 | 1/5 → 4/4 | 8/8 → 8/8 |
| `warehouse_picking` | 8 | 1.38 → 1.12 | 0.053 → 0.030 | 1.7 → 1.5 | — | 0.06 → 0.06 m | — | — | — |

- Better: the safety valve is used 1/2 to 1/12 as often at elevators and gates. People taking over 10 s to board: 8–18% → 1–7%. Steps over 0.2 m in one frame are gone (5.7).
  Dyads within range 59/72 → 72/72; lateral spread by density (a 1.2 judgement) within range 24/70 → 62/70.
- Worse: shaking in place rose a little in templates with gates (`office_gate_ev` 2.8 → 3.6, `office_signage_ab` 1.5 → 2.3, `verify_gate_capacity` 2.5 → 2.8).
  As examined in 5.8, most of it comes from the changed order of random numbers and from shaking around people waiting for their mates beyond the gate.
  Standing spacing is "caution" in seed 10 of `hospital_gate_ev` (5.3% under 0.45 m against a criterion of 5%).
- The group-size judgement is 9/9 → 7/9 for `verify_groups` and 16/16 → 15/16 for `office_ev_hall`. Pooled over seeds, the shares of people by group size stay close to the configured distribution in both versions
  (difference 0.036 → 0.010 for `verify_groups`, 0.011 → 0.028 for `office_ev_hall`). Drawing relations changes the order of random numbers, and in some runs the run-to-run variation exceeds the judgement's range.
- Where the lateral spread is out of range, dyads in `office_ev_hall` are 0.04–0.11 m narrower than the literature (5.8). The flow of `verify_bottleneck` is 1.91 → 1.91 persons/(m·s) (experiments: 1.90–2.19).
- During the comparison, a counting error in the crossings between members was fixed: a companion who joined at a meeting point was counted as a stranger even within the same group (in seed 14 of `office_ev_hall`, a person who joined
  walked between two mates for 1.5 s, which counted as 45 crossings). After the fix, strangers crossed between members once in 1.1 (`verify_gate_capacity`) and 0 times in 1.2.

### Added templates

The three templates added in 1.2 were computed with seeds 1–16 (same tools and measures as the comparison above).

| Template | People (per run) | Safety valve (per run) | Pairs with centres under 0.3 m | Shaking in place | Stuck people | Largest step | Judgements |
|---|---:|---:|---:|---:|---:|---:|---|
| `hospital_outpatient` | 112 | 1.94 | 0.041 | 0.3 | 0 | 0.07 m | Free walking speed, group size, dyads and lateral spread 16/16 |
| `office_lunch` | 406 | 1.25 | 0.003 | 2.5 | 0 | 0.08 m | Free walking speed, group size, dyads, standing spacing and arrivals 16/16, lateral spread 14/16, gate headway 2/2. Taking over 10 s to board 1.0% |
| `warehouse_shift` | 21 | 1.94 | 0.006 | 2.5 | 0 | 0.06 m | Free walking speed and arrivals 16/16 |

What happens at counters, seats, rooms and work points (waiting times, seats, shares of time) is in 5.9–5.12.

### Rendering

- The outpatient clinic (seed 1), office lunchtime (`CamCafe`, 40 s) and the warehouse (seed 1, three cameras) were rendered on one GPU and checked by eye: the sitting motion, benches, consultation-room doors, people inside rooms, the counter, packing tables
  and the ground-truth boxes overlaid (5.10–5.12).
- A check that matches rendered material against a detector and tracker, like corpus v6 for 1.1, was not done for 1.2.

## Known limitations

- In front of crowded elevators, people taking over 10 s to board remain: 7% in `office_ev_hall` and 20% in the office of corpus set A. Much of the time is spent walking slowly through the crowd,
  and some people still stop balanced inside a ring of standing people (safety valve after 15 s; 5.13). A late boarder can board a car that has already left (the rendered elevator door stays open).
- Shaking in place remains at 2–6 per 1,000 person-seconds (people walking to the waiting area, people passing through crowds). In `warehouse_shift` it rose from 1.9 to 2.7 with the fixes (people working at shelves now make way).
- Groups: formation for four or more (two rows), the spacing of companions and the time spent waiting beyond a gate (30 s) are provisional. Dyads in `office_ev_hall` are a little narrower than the literature.
- Components: values without literature (reception, cashier, pharmacy, time clock and packing times, arrival volumes and others) are provisional (section 6 of validity.en.md). Hospital reception is calling only (numbered tickets; a queue along the desk became a dead end, 5.9).
  Shelves have no capacity.
- Rendering:
  - Around the benches added along the south windows of the hospital lobby, waiting companions and passers-by can appear to overlap (5.10).
  - The coffee counter has no staff and no coffee machine, so the queue can look like a queue at the reception desk. The time clock is notional and nothing is placed for it in rendering.
  - The rendered ground-truth boxes (`labels/`) of seated people have not been checked yet (the `mot/` boxes were checked against the rendered body).
- Spaces: spaces written as polygons have no USD and cannot be rendered (simulation and ground truth only). The GUI map is shown only for spaces with a top view. One level only. `simple_room` renders black from inside.
- Remaining from 1.1: the rendered "visible-part box" encloses all visible pixels, so for a person whose legs are visible between other people, a detection around the upper body may not reach IoU 0.5.
- Remaining from 1.0: a camera's `clock_offset_s` and `drop_rate` are only recorded. `gate_events` times are when the head of the queue starts moving. `boarded` includes people who could not board.

## Next versions

Draft goals and decisions to make are in [roadmap.en.md](roadmap.en.md).

- 1.3: two or more cameras (ground truth and evaluation for matching people across cameras at different places and for flows of counts; camera clock offsets and dropped frames).
  A simple scene for rendering (floor and walls) from a space written as polygons (candidate).
- 1.3 or later: moving things other than people (wheelchairs, stretchers, carts, AGVs, forklifts).
