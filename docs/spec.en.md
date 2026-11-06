# twinsim specification

[日本語](spec.md)

A simulator for people-flow digital twins of buildings and factories. It is an environment for checking people-flow analysis methods and the digital-twin concept diagram (Observe → Understand → Predict & simulate → Optimize).
People's movement is computed on the CPU (a few seconds to a few tens of seconds), and Isaac Sim renders it only when video is needed (GPU, a few minutes to a few hours).

```
Scenario (JSON or YAML) ──> people-movement computation (CPU) ──> ground truth, tables, aggregates, graphs, boxes ──> training and evaluating detection, tracking, GNNs
   Space (space pack)                               └──> rendering in Isaac Sim (GPU) ──> video ──> detection, tracking, VLM
```

## 1. Space (twinsim/spaces/<name>/space.yaml or space.json)

One USD scene. The "meaning" that is not in the USD (entrances, gates, elevator doors, waiting areas, zones) is written here.

| Key | Contents |
|---|---|
| `usd` | URL of the scene (e.g. an Isaac Sim asset) |
| `license` | Terms of use of the asset (check them when producing data for distribution) |
| `navmesh_region` | Region in which the navmesh is baked `[x0, x1, y0, y1, z0, z1]` (one floor) |
| `glass` | Occlusion by glass (optional). `occluding` lists the glass materials (MDL names) through which people are not visible in the rendered video. The glass panes are in `glass.json` in the same folder (oriented boxes extracted inside Isaac Sim by `twinsim/isaac/probe_materials.py`). Used for the `glass` column and visibility of the rendered label table (`labels/`) |
| `levels[]` | Floors: `z`, `walkable` (grid of the walkable area; `.txt` or `.npz`), `blocked` (optional; list of polygons `{polygon, note}` made not walkable, where rendered objects are placed), `top_image`, `top_view` (top-down image and its viewpoint) |
| `pois` | Places (table below) |
| `zones` | Zones (polygons). Used for ground-truth aggregation and as graph nodes. Matched in order from the top |
| `cameras` | Candidate cameras (`eye`, `target`; a scenario uses them by name) |

Kinds of places (`pois`):

| kind | Meaning | Keys |
|---|---|---|
| `spawn` | Where people appear and disappear (e.g. a building entrance) | `xy` or `line` (somewhere on the line), `hidden` (optional; a point no camera sees. People appear here and walk straight to `xy`; people leaving walk from `xy` to here and disappear. It may be outside the walkable area, e.g. behind a door. With `motion_model: cfsm`, people entering and leaving a `spawn` use two lanes: people entering use the line from `xy` to `hidden`, people leaving a line 0.6 m beside it (on the left of the outgoing direction, or the right if the left is a wall). `Space.door_lanes`) |
| `exit` | Where people leave | `xy` or `line`, `hidden` (optional; as for `spawn`) |
| `gate` | Entry gate | `line` (both ends), `lanes`, `lanes_in`, `lanes_out` (lanes used for each direction), `in_dir` (direction of entry) |
| `elevator` | Elevator (EV) door | `xy` (in front of the door), `face` (a point inside the car), `cabin_m` (optional; how far, in m, people boarding walk from the door towards `face` before they disappear; people alighting come out from there. If omitted, people disappear and appear at the door point), `prop: elevator` (optional; for a space whose USD has no elevator, an elevator car and door frame are placed when rendering. Make the car area not walkable with `blocked`) |
| `wait_zone` | Area for waiting for the elevator | `zone`, `spacing` (spacing, m), `door_aisle` (half-width, in m, of the passage kept clear in front of the door). When all waiting spots are taken, the extra people walk to a nearby walkable point at least 0.6 m from everyone else and wait there |

The area around a `spawn`, `exit` or `elevator` (within 0.8 m of the segment from `xy` to `hidden` or into the car; for a `spawn`, the segment midway between the entering and leaving lanes; for an elevator without a car (`cabin_m`), out to 1 m outside the door, where alighting people appear) is a "portal" (`Space.portals`).
It is used for the `portal` column of the rendered label table (docs/formats.en.md, section 4) and as an area excluded from evaluation.
| `spot` | Place where people stop (reception, meeting up, in front of a sign) | `xy`, `face` (point to face). Spots can be grouped into one destination by name prefix (`reception_`, `lounge_`) |
| `prop` | Object placed by the simulator (not in the USD) | `xy`, `face`, `prop` (`signage`) |

To create a new space: `python -m twinsim export-space <name> --usd URL --region ...` (in Isaac Sim, this produces the walkable-area grid, the top-down image and
a list of prims that look like elevators or doors, and puts a space.yaml skeleton in place) → look at the top-down image and the list, and write `pois`, `zones` and `cameras`.

Existing spaces (the `corridor` ones are made for twinsim; the others are bundled with Isaac Sim 6.1, CC BY 4.0):

| Space | Contents | Semantic map | Rendering |
|---|---|---|---|
| `office` | Ground-floor lobby of an office (entrance corridor → gates with 3 lanes → lobby → reception, 2 elevators, meeting-up area, south exit) | Done | Done |
| `hospital` | Ground floor of a hospital (lobby → corridor → west hall; an elevator car placed in front of the stairwell when rendering). Same points and cameras as sim-gate in hospital-sim | Done | Done |
| `warehouse` | Warehouse (aisles between 8 rows of shelves to the north, a work floor to the south; the receiving, packing and waiting areas are assumed) | Done | Done |
| `simple_room` | Small 10 m × 10 m room (floor z = -0.77) | Done (for smoke testing) | Not supported (completely dark when shot from inside; cause not investigated) |
| `warehouse_small` | Small warehouse (shelf, door and gate parts) | Materials only (not done) | Not done |
| `corridor` | Corridor 5 m wide and 50 m long (for checking speed and density) | Done | None (no top-down image) |
| `corridor_door` | Corridor with a 1 m opening partway (for checking bottlenecks) | Done | None (no top-down image) |

Checking a space: `python -m twinsim show-space <name>` produces an image (annotate.png in the space folder) that overlays the walkable area, scale ticks, candidates, places and zones on the top-down image.

## 2. Scenario (JSON or YAML; templates are twinsim/templates/<name>.yaml)

| Key | Contents (default) |
|---|---|
| `space` | Name of the space |
| `seed`, `fps`, `duration_s` | Random seed (0), frames per second (30), length (120 s) |
| `people` | `profile` (literature profile: `office_commute_jp`, `leisure_low_density`; docs/validity.md), `speed` (distribution of walking speed, default 1.34 ± 0.26 m/s, Weidmann 1993), `models` (person models; `all`), `group_size` (group size used when a stream does not specify one), `group_speed` (default `{model: moussaid2010, slope_m_s: 0.04}`; `{model: min}` matches the slowest member), `group_lateral_m` (side-by-side spacing of a pair, default 0.66, Zanlungo et al. 2017), `speed_density` (speed–density relation, default Weidmann 1993; `null` turns it off), `lateral_max_m` (how far a person can step sideways off the path to avoid others, 1.0), `motion_model` (walking model; default `cfsm`, previous model `lane`) |
| `demand` | Volume of elevator users: `population` (building population), `period` (`morning`, `lunch`), `peak_pct_5min` (percentage in the busiest 5 minutes, 12). Used by `rate: {type: lift_demand}` and `alight.count: {type: lift_demand}` (Peters et al. 2011) |
| `streams[]` | Streams of people: `name`, `origin` (where people appear: a place name, or coordinates as `{"xy": [x, y]}` or `{"line": [[x0, y0], [x1, y1]]}`; for a line, somewhere on that line; adding `name` sets the label used in the counts), `rate` (arrival rate), `group_size`, `types`, `destinations[]`, `start_s`. Coordinates must be walkable and connected to the destinations (otherwise an error before simulating) |
| `elevator` | `cars` (door names), `capacity`, `schedule`, `alight` (people getting off: `count`, `types`, `destinations`), `transfer_s` (boarding/alighting time per person, 1.0 s), `door_open_s` (from arrival until the first person moves, 1.0 s, provisional) |
| `gates` | Per-gate `service_s` (interval for passing one person through one lane; seconds or a distribution; default 1.5 s, lognormal with median 2.0 s in `office_commute_jp`) |
| `validity` | `{speed_density: judge}` judges the speed at each density against Weidmann's formula (only for the one-way corridor check). `{bottleneck: {x, y: [low, high], width_m}}` measures the flow through an opening |
| `cameras[]` | `name` (a candidate camera in the space, or a new name) and overrides for `eye`, `target` (both `[x, y, z]`), `focal_mm` (12), `h_aperture_mm` (20.955), `width`, `height`, `clock_offset_s`, `drop_rate` (the last two are only recorded). A new name requires `eye` and `target` |
| `render` | `width`, `height` (1280×720), `tint` (`per_person` varies clothing color per person, `false` does not; the argument of `twinsim.render(tint=...)` takes priority), `props` (names of the places where objects are placed), `gate_props` (place the gate machines, `true`) |
| `outputs` | What to write out (`ground_truth`, `frames`, `tasks`, `graph`, `mot`, `aicity`, `preview`, `validity`) |
| `variants`, `variant` | A/B comparison: `variants: {A: {name: value}}` together with `variant_p: name` in a destination replaces `p` |
| `graph` | `cell_m` (cell size of the grid graph, 2 m) |
| `mot_stride` | Write MOT boxes every N frames (1) |
| `congestion_levels` | Boundaries of the congestion levels (people/m², `[0.10, 0.20]`) |
| `name`, `title`, `title_en`, `description` | Name and description |
| `calibration` | Record written by `twinsim calibrate` |

Destinations (elements of `destinations[]`):

| Key | Contents |
|---|---|
| `to` | `elevator` (wait for and board the elevator), a place name (leave if it is an `exit` or `spawn`; stop if it is a `spot`), a place-name prefix (`reception` → one of `reception_*`) |
| `p` | Weight for being chosen |
| `types` | Types of people who choose this destination (e.g. `[visitor]`; everyone if omitted) |
| `via` | Gates passed on the way (`[gate]`). The direction (entry/exit) is determined from the positions |
| `dwell` | Stop duration (distribution, s) |
| `state` | State while stopped (defaults: reception `reception`, meeting up `dwell`, sign `sign_check`) |
| `glance` | How far to look around while stopped (degrees) |
| `variant_p` | Name that replaces `p` in an A/B comparison (`variants`) |
| `meet` | Meeting up: `p`, `delay` (how late the companion arrives), `from` (where the companion appears; same forms as `origin`), `via`. The state while waiting is `companion_wait` |
| `then` | Destination after stopping (same format) |

Elevator operation (`elevator.schedule`):
- `{type: interval, offset: distribution, interval: distribution}` each car arrives at intervals drawn from the distribution
- `{type: times, times: {EV1: [s, ...]}}` specifies the arrival times
- `{type: on_demand, travel_s: distribution, max_wait_s: 60}` calls a car when someone is waiting and none is scheduled (a simple example)
- Your own operation can be plugged in through the API's `elevator_policy(sim, t)` (optimizing the operation)

## 3. Writing distributions (twinsim/dists.py)

`1.34` (constant), `{type: normal, mean, sd, min, max}`, `{type: uniform, min, max}`, `{type: lognormal, median, sigma, min, max}`,
`{type: poisson, lam}`, `{type: zero_truncated_poisson, lam}` (Poisson without 0; for group sizes), `{type: choice, values: {name: weight}}`.
Arrival rates (`per_min` is groups per minute; with `unit: persons` it is persons per minute, divided by the mean group size before use): `{type: constant, per_min: 8}`,
`{type: piecewise, per_min: [[s, rate], ...]}` (a Poisson process that varies by time period; sampled by thinning), `{type: lift_demand, flow: incoming, share: 0.9}` (persons per minute from `demand`),
`{type: times, times: [s, ...]}` (fixed times; for verification). Writing `source: <literature name>` on any distribution makes it count as literature in the validity ledger.

## 4. States (per-frame ground truth)

| State | Meaning |
|---|---|
| `pass` | Walking through / heading to a destination |
| `gate_queue` | Queuing at a gate |
| `ev_approach` | Heading to the elevator waiting area (inside the elevator-waiting zone) |
| `ev_wait` | Waiting for the elevator (including walking in to board) |
| `alight` | Getting off the elevator (within 3 m of the door, inside the elevator-waiting zone) |
| `reception` | Stopped at reception |
| `dwell` | Stopped at another place |
| `sign_check` | Looking at a sign / signage |
| `companion_wait` | Waiting for a companion |

## 5. Outputs (location of results; default <TWINSIM_DATA>/runs/<scenario name>, TWINSIM_DATA defaults to ~/.twinsim, and to ~/dt-data/twinsim with ./run.sh)

| File | Contents |
|---|---|
| `ground_truth.json` | Ground truth that tracking evaluation and similar tools can read (`tracks`, `moving`, `people`, `cameras`), plus state intervals (`people[].states`), groups, elevator and gate events, and zones |
| `frames.csv.gz` | One row per person per frame (frame, t, person, x, y, yaw, moving, state, zone, group, type) |
| `tasks.json` | Ground-truth aggregates for the 6 tasks: 1 people count (per second, per zone, per state), 2 gate passages (per minute, by direction), 3 lingering (intervals stopped for 3 s or more), 4 groups, 5 congestion (zone density and level), 6 origin → destination (per minute), and elevator waiting time |
| `graph/` | For GNNs: `graph.json` (zone graph, 2 m grid graph, nodes visible from each camera), `zone_counts.csv` (people per zone per second), `zone_flows.csv` (movement between zones per minute), `grid_counts.npz` (counts[second, cell]), `zone_graph.graphml` |
| `mot/<camera>.txt` | Bounding boxes in MOTChallenge format (frame, id, x, y, w, h, 1, 1, visible fraction). The visible fraction is approximate (walls are counted as lines on the floor, people by overlap with the boxes in front of them) |
| `preview.png` | Check image overlaying people's trajectories (colored by stream), zones and camera directions on the top-down image |
| `summary.json` | People count, time per state, elevator waiting time, gate passage directions, run time, `inputs` (arrival rates, elevator boarding/alighting and gate times determined from the literature), `motion` (safety valve `squeezes`, swaps in front of the gate `lane_swaps`, people who entered on the leaving line `entry_alt`), `outside_at_end` (people who arrived but were still waiting outside at the end, per stream) |
| `validity.json`, `validity.md`, `validity.png` | Comparison with literature values (reproduction of inputs, emergent quantities) and a ledger of the basis for each scenario value (docs/validity.md) |
| `aicity/gt.txt` | Multi-camera tracking format (AI City Challenge MTMC). Person IDs are the same across cameras |
| `logs/` | Log format (export-logs) |
| `video/<camera>.mp4` | Rendered video (after `render`) |

## 6. Usage (API)

```bash
twinsim templates                                              # list templates
twinsim run office_gate_ev --set duration_s=120 --out runs/test   # compute (CPU); --set overrides scenario values
twinsim check runs/test                                        # check
twinsim render runs/test --frames 3000 3149                    # test render (GPU)
```

From Python: `twinsim.simulate("office_gate_ev", out_dir="runs/test", overrides={...}, elevator_policy=f)` ([library.en.md](library.en.md)).

## 7. GUI and REST API

`python -m twinsim serve` (listens only on 127.0.0.1:8770; run `ssh -N -L 8770:localhost:8770 ampb` on your local PC and
open the URL shown by `python -m twinsim serve --url`). Because other users share the machine, it checks a token (~/.config/twinsim/token, readable only by the owner).

- Screen: on the left, the top-down image of the space (zones, places, gate lines, camera positions, look-at points and fields of view; where streams appear; cameras and stream origins can be moved by dragging); on the right, the settings
  (length, random seed, per-stream arrival rate, group size and destination weights, elevators, gates, cameras, placed objects, and a JSON field in which the whole scenario can be written) and the results
  (summary, check images, test render and rendering (started only after reviewing the estimate and confirming), videos, files).
- API (from programs, `Authorization: Bearer <token>`): `GET /api/spaces`, `/api/spaces/<name>`, `/api/spaces/<name>/top`,
  `GET /api/templates`, `/api/templates/<name>`, `POST /api/runs {scenario, overrides, name}` → `{id}`, `GET /api/runs`, `/api/runs/<id>`,
  `/api/runs/<id>/file?path=...`, `POST /api/runs/<id>/render {frames | window: "busy", seconds, cameras, confirm}`, `GET /api/isaac`.
- Checking the screen: `tools/gui_shot.py` (takes screenshots of the settings and results tabs with Playwright's Firefox, and checks camera dragging and browser errors).

## 8. Rendering (Isaac Sim, GPU)

```bash
isim up --gpu N --enable omni.anim.navigation.core --enable omni.kit.capture.viewport --kit-arg "--exec /workspace/twinsim/isaac/agent_runner.py"
```

(As of 2026-10-22, the host driver is 615.71.10 and the `--vnc` display cannot be created. It works with the WebRTC method above.)
`render` places the computed people as person models (10 kinds, with clothing color varied per person), renders each camera, and writes mp4 files.
Rendering speed (test renders on 2026-10-22, 1280×720, 1 GPU): about 5.7 frames per second for the office with 30 people, about 1.9 frames for the warehouse with 15 people, about 1.1 frames for the hospital with 24 people
(the hospital is slow because it has many lights). Rough estimates for 5 minutes (9,000 frames) × 2 cameras: office about 1.5 hours, warehouse about 2.6 hours, hospital about 4.5 hours.
Placed objects: gate machines (boxes separating the lanes; automatic), signage (`render.props`), an elevator car and door frame (elevators with `prop: elevator`; NVIDIA's office parts, CC BY 4.0, with a light gray outer wall), lights (the space's `lights`; for USDs with no lights inside the rooms).
For long renders, state the expected duration and the GPUs and get confirmation before starting (the GPUs are shared with other users).

## 9. Validity

The distributions of people are built from literature values, and every run is compared with the literature values (`validity.*`). The list of values and sources, the verification criteria, the engine verification results,
and the values without literature (provisional) and how to calibrate them with real data are in [validity.en.md](validity.en.md). Verification templates: `verify_corridor_speed` (equivalent to RiMEA test 1),
`verify_fundamental_diagram` (speed and density), `verify_groups` (groups), `verify_gate_capacity` (a crowded gate), `verify_counterflow` (passing in opposite directions), `verify_bottleneck` (an opening).

## 10. Known limitations

- By default, walking uses the Collision-Free Speed Model (Tordeux et al. 2016, `people.motion_model: cfsm`) with added rules for group cohesion, gate queues, elevator boarding and alighting, and entrances
  (sections 5.1–5.3 of [validity.en.md](validity.en.md)). Pushing (forces between bodies) is not modelled; a person who cannot progress passes through with the safety valve (2 s of passing through after 15 s without progress),
  so bodies overlap a little only then. In crowded configurations the gate queue fills the passage and people walking the other way have trouble getting past. The previous model (`lane`, stepping sideways off the path) can still be chosen.
  Corners, stairs and evacuation have not been checked (passing in opposite directions and openings have; see section 5 of [validity.en.md](validity.en.md)).
- If the entrance (spawn place) is blocked, people wait outside until it clears (`events.spawn_wait_s`). When a queue extends outside the building, those people are counted as waiting outside.
  Waiting people enter each entrance in order of arrival (a group together; each member waits until the previous member has moved 0.4 m). People entering from behind a door (`hidden`, `motion_model: cfsm`)
  also use the leaving people's line when the entering line is blocked, but only when nobody leaving through it is within 5 m (`motion.entry_alt` in `summary.json`).
  The second person of a pair enters side by side on the other line when it is free. People who arrived but were still waiting outside at the end are in `outside_at_end` of `summary.json` (per stream).
- The visible fraction (9th column of MOT) is approximate. Exact values would be taken from the rendered depth (not implemented).
- Single floor only. Elevators only make people disappear and appear at the doors; there are no cars and no other floors. Door open/close animations are not used (one of the office elevators has an open/close animation).
- The hospital's walkable area was built with the room doors closed, so people cannot enter the rooms. The small room renders completely dark (cause not investigated).
- There are 10 person models (clothing colors make people distinguishable). There is no luggage, wheelchairs, children, robots or carts.
- Camera clock offsets and frame drops (`clock_offset_s`, `drop_rate`) are only recorded; they are not yet reflected in the video or the ground truth.
