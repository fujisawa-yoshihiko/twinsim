# Output formats (training data and ground-truth labels)

[日本語](formats.md)

The formats of the files written out by twinsim's computation and rendering. Intended for people who use them for other purposes, such as detection, tracking, multi-camera tracking, person re-identification, people-flow prediction, graph learning, and state classification (VLM).


## 0. Common conventions

| Item | Convention |
|---|---|
| Location | `<TWINSIM_DATA>/runs/<run-name>/` or the place set with `out_dir` (`TWINSIM_DATA` defaults to `~/.twinsim`). Not put in git |
| Coordinates | World coordinates (m). Z is up. The floor height is the space's `levels[0].z` (0 for office). x and y are the same as in `twinsim/spaces/<space>/space.yaml` |
| Heading (yaw) | Degrees. Counterclockwise from +X (`atan2(dy, dx)`). −180 to 180. While walking, the direction of travel; while stopped, the direction the person is facing |
| Time | Simulator frames start at 0; seconds = frame ÷ fps (default 30). Times in `events` and elsewhere are in seconds |
| Frame number offset | The MOT and AI City formats are 1-based (= simulator frame + 1). Frame k of the video = simulator frame `frames[0]` of `render_log.json` + k (identical when all frames are rendered) |
| Person names | `P0001`… (reassigned for each run). The numeric IDs in MOT and AI City map to names via `mot/ids.json` (the same across cameras) |
| Groups | Ground-truth groups are `G001`… (sets of people who walk together) |
| Person box | The box obtained by projecting a box centered at the feet, with a radius of 0.25 m and the person's height (`height_m`). Not tight to the rendered person's outline but slightly larger (an IoU of 0.3 is a guideline for matching) |
| Visibility | Approximate. Walls: 0 if the line on the floor from directly below the camera to the feet or head passes through non-walkable area for 1 m or more. People: the fraction overlapped by the boxes of people in front (8×16 points within the box). Rendering depth is not used |

Cameras (`cameras[name]` in `ground_truth.json`) use the same representation as USD cameras: row vector `p_cam = [x, y, z, 1] · M` (`M` = `world_to_camera_rowmajor`, 4×4);
the camera looks along −Z with +Y up. Projection to pixels:

```python
import numpy as np
def project(cam, pts):                       # pts: (N, 3) world coordinates → (N, 2) pixels, depth
    ph = np.c_[np.asarray(pts, float), np.ones(len(pts))] @ np.asarray(cam["world_to_camera_rowmajor"])
    depth = -ph[:, 2]
    u = cam["cx_px"] + cam["fx_px"] * ph[:, 0] / depth
    v = cam["cy_px"] - cam["fy_px"] * ph[:, 1] / depth
    return np.c_[u, v], depth
```

No lens distortion (pinhole). Other values: `eye` and `target` (world coordinates), `focal_mm` and `h_aperture_mm`, `width` and `height` (default 1280×720),
`h_fov_deg`, `tilt_down_deg`, `fps`. `Camera` in `twinsim/camera.py` can read them as is.

## 1. List of files

| File | Contents | Main uses |
|---|---|---|
| `ground_truth.json` | Per-person trajectories, states, events, and attributes; cameras; elevator (EV) and gate events; zones | Source of all ground truth |
| `frames.csv.gz` | A table with one row per person per frame | Trajectory prediction, aggregation, spreadsheets |
| `mot/<camera>.txt` and `mot/ids.json` | Per-camera person boxes (MOTChallenge format; an approximation computed without rendering) | A rough guide for runs that are not rendered |
| `labels/<camera>.csv`, `labels/<camera>_mot.txt`, `labels/ids.json` and `labels/identity.json` | Per-person boxes and occlusion taken from the rendering (with `render(..., labels=True)`; second half of section 4) | Training and evaluating detection and single-camera tracking, evaluation split by how hidden people are |
| `aicity/gt.txt` and `aicity/cameras.json` | Multi-camera boxes and world positions (AI City Challenge MTMC format) | Multi-camera tracking, person re-identification |
| `video/<camera>.mp4` and `render_log.json` | Rendered videos (H.264, same fps as the ground truth) and the rendered range | Image-based training together with the boxes above |
| `tasks.json` | Ground-truth aggregates for the six tasks | Evaluating counts, flows, dwelling, and congestion |
| `graph/` | Zone graph and grid graph, and time series of counts and flows | GNN and time-series prediction |
| `logs/` | Gate passage logs and elevator operation logs (same format as real data). Made with `twinsim export-logs <run>` | Example for calibrating with real data (`calibrate`) |
| `summary.json`, `scenario_resolved.json` and `.yaml` | Summary, and the scenario with defaults filled in (including the random seed) | Regeneration, logging |
| `validity.*` and `preview.png` | Comparison with the literature, figures for checking | Validity of the people distribution |

## 2. `ground_truth.json`

| Key | Contents |
|---|---|
| `fps`, `total_frames`, `seed`, `space`, `scenario` | Number of frames (per 1 s), total number of frames, random seed, space name, scenario name |
| `people[name]` | Person attributes and itinerary (table below) |
| `tracks[name]` | `[[x, y, yaw], …]`. The k-th entry is frame `people[name].start_frame + k` (from appearance until disappearance) |
| `moving[name]` | `[0/1, …]`. Whether the person is walking in that frame (same length as `tracks`) |
| `cameras[name]` | Cameras (representation in section 0) |
| `gate_events` | `[{t, gate, lane, person, dir: in/out}]`. Times at which people passed through a gate |
| `elevator_events` | `[{t, car, boarded: [name], alighted: [name]}]`. Times at which an elevator arrived, and the people who got on and got off |
| `elevator_times`, `cars`, `spots`, `door` | Elevator arrival times, door position and capacity of each car, the spots where people stand while waiting for the elevator |
| `gates[name]` | Lane centers `lanes`, entry direction `in_dir`, time per person `service_s` |
| `zones[name]` | Zone polygon `[[x, y], …]` |

Contents of `people[name]`:

| Key | Contents |
|---|---|
| `model`, `kind`, `height_m`, `tint_index` | Character model (Isaac Sim characters, 10 kinds), sex F/M, height (m), clothing color index (rendering gives each person a different color) |
| `type`, `stream`, `origin`, `destination`, `flow` | Type (staff, visitor, etc.), stream name, where the person appeared, destination, "origin->destination" |
| `group`, `role` | Group name (`G001`; null if alone), `companion` if the person is a companion |
| `start_frame`, `arrive_frame`, `speed_m_s` | Frames at which the person appeared and disappeared, desired walking speed |
| `states` | `[[start frame, end frame, state], …]` (states in the table below) |
| `events` | In seconds. `start` and `end`, `gate_join` and `gate` (joined the queue, passed through), `hall`, `wait_start`, `car`, `board_start`, `board` (elevator), `stops` (intervals while stopped), `meet_start` and `meet_end`, `spawn_wait_s` (seconds spent waiting outside because the entrance was blocked) |

| State | Meaning |
|---|---|
| `pass` | Walking through / heading to the destination |
| `gate_queue` | Queuing at a gate |
| `ev_approach` | Heading to the elevator waiting spot (inside the elevator waiting zone) |
| `ev_wait` | Waiting for the elevator (including the walk in to board) |
| `alight` | Getting off the elevator (within 3 m of the door, inside the elevator waiting zone) |
| `reception` | Stopping at reception |
| `dwell` | Stopping at any other place |
| `sign_check` | Looking at a sign / signage |
| `companion_wait` | Waiting for a companion |
| `work`, `wait` | Working / waiting in the warehouse (warehouse template) |

## 3. `frames.csv.gz`

The first line holds the column names: `frame, t, person, x, y, yaw, moving, state, zone, group, type`.
`t` is in seconds, `moving` is 0/1, `zone` is the zone at the person's feet (empty if none), and `group` is empty or `G…`.

## 4. Camera boxes

`mot/<camera>.txt` (same as MOTChallenge gt.txt, comma-separated): `frame, id, x, y, w, h, conf, class, visibility`.
`frame` is 1-based, `id` is the number in `mot/ids.json`, `x, y, w, h` are in pixels (top-left corner, width, and height), `conf` and `class` are 1, and `visibility` is the visibility (0 to 1, approximate).
Every person with at least 20% of their box inside the image is written, even if occluded (as a guideline, exclude visibility below 0.4 from training and evaluation). Can be thinned out with the scenario's `mot_stride`.

`mot/ids.json`: `{"P0001": 1, …}`. The same person gets the same number across cameras.

**Ground truth from the rendering (`labels/`)**: with `twinsim.render(..., labels=True)` (`twinsim render --labels`), Isaac Sim's Replicator
takes each person's boxes and pixels for the same frames that were rendered, and writes `labels/<camera>.csv` for the rendered frames only. Unlike `mot/`,
it is made from the rendered pixels of each person, so the boxes fit the outline and occlusion counts walls, furniture and other people
(in the check of 2026-11-03, the `mot/` boxes were about 1.4 times wider than detector boxes).

| Column | Contents |
|---|---|
| `frame`, `id`, `name` | Frame (1-based, as in MOT), person number (`labels/ids.json`; numbers in `mot/ids.json` are kept, people not in `mot/` get the next numbers), person name |
| `tight_x0` to `tight_y1` | Box around the visible pixels (pixels, inside the image only; empty if no pixel is visible) |
| `amodal_x0` to `amodal_y1` | Full-body box including hidden parts. Based on Replicator's loose box (cut at the image border); only the sides touching the border are extended to the computed box (so it can extend outside the image) |
| `occlusion` | Share of the full body inside the image that is hidden by other objects, people or occluding glass = 1 − (visible pixels ÷ full-body pixels) × (1 − `glass`) |
| `truncation` | Share of the full-body box outside the image |
| `visibility` | Visible share = (1 − `occlusion`) × (1 − `truncation`) |
| `portal` | 1 if the person is in a portal area (where people appear or disappear; `pois` in docs/spec.en.md). As a guide, exclude these from evaluation |
| `state` | The person's state (`states` in section 2) |
| `visible_px` | Number of visible pixels (excluding the part behind occluding glass) |
| `occ_source` | Where `occlusion` comes from: `silhouette` (a frame where the full-body pixels were measured), `silhouette_interp` (an unmeasured frame; the ratio of full-body pixels to full-body box area is interpolated from that person's measured frames before and after), `fill_median` (no measured frame for that person; the median over everyone), `hidden` (no visible pixel), `unlabeled` (from when the person appeared partway through a rendered chunk until Replicator first returns them, or the body lies inside a box returned under the name of a person who has already left; whether they are visible is unknown, so treat them as ignored in evaluation) |
| `glass` | Share of the body inside the image that is behind occluding glass (0 to 1). 0 if the space has no `glass` (docs/spec.en.md). The `tight` box includes the part behind glass |

The full-body pixels are counted every 30 frames by rendering again with the background (the space USD and placed objects) and the other people hidden,
one group at a time of people whose full-body boxes do not overlap (Replicator's `occlusionRatio` and its occlusion annotator give −1, i.e. not computed, for these character models).
The segmentation sees through glass and counts the pixels of people behind it, but in the rendered video almost nothing can be seen behind frosted or decorative glass. So the share of the body
for which a glass pane listed in the space's `glass` lies between it and the camera is computed (`glass` column, twinsim/glass.py) and included in `occlusion` and `visible_px` (clear glass is not counted).
Making glass opaque while the labels are taken is not used, because Replicator then returned no people (2026-11-04).
Replicator sometimes does not return a newly visible person for a while, or returns them under the name of another person seen before. The names are checked by whether the rendered full-body box
falls inside the computed box, and reassigned to the matching person (dropped if nobody matches). The numbers reassigned and dropped are in `labels/identity.json`.
Taking the labels in the same Isaac Sim right after rendering left out people who appeared midway for a long time, so take the labels in a separate labels-only job (`relabel.py`, 2026-11-04).
`labels/<camera>_mot.txt` has the same contents in the MOTChallenge gt.txt format (`frame, id, full-body box x, y, w, h, 1, 1, visibility`).
Rendering takes about 1.5 to 2 times as long with the labels.

`aicity/gt.txt` (same as AI City Challenge MTMC, space-separated): `camera_id obj_id frame_id xmin ymin width height xworld yworld`.
`camera_id` comes from `aicity/cameras.json` (`{"CamEV": 1, …}`), `obj_id` is the same as in `mot/ids.json`, `frame_id` is 1-based, and `xworld yworld` are the world coordinates of the feet (m).

## 5. `tasks.json` (the six tasks)

| Key | Contents |
|---|---|
| `seconds`, `zones`, `zone_area_m2` | Number of seconds, zone names, zone areas |
| `1_count` | `present` (total number of people per second), `by_zone[zone]` and `by_state[state]` (number of people per second). Counted at the first frame of each second |
| `2_direction` | `gate_per_min["gate:in/out"]` (number of people passing per minute), `gate_events` |
| `3_dwell` | Intervals stopped for 3 s or more `[{person, state, start_s, end_s, zone}]` |
| `4_group` | `{G001: [name, …]}` |
| `5_congestion` | `levels_per_m2` (thresholds between levels, default [0.1, 0.2] people/m²), `density[zone]` and `level[zone]` (per second) |
| `6_trend` | `od_per_min`: `[{minute, origin, destination, count}]` |
| `elevator` | `waits`: `[{person, car, wait_s}]`, `events` |

## 6. `graph/`

| File | Contents |
|---|---|
| `graph.json` | `zone_graph` (`nodes`: `{id, kind: zone, x, y, area_m2}`, `edges`: adjacent zones `{source, target}`), `grid_graph` (grid with `cell_m`, default 2 m; `nodes`: `{id: c<number>, kind: cell, x, y}`, `edges`), `observed[camera]` (`zones`: fraction of each zone's floor visible to the camera, `cells`: cells visible to the camera) |
| `zone_counts.csv` | `t, <zone>…`. Number of people in each zone per second |
| `zone_flows.csv` | `minute, source, target, count`. Movements between zones per minute |
| `grid_counts.npz` | `counts[second, cell]` (cell order follows `grid_graph.nodes`), `t` |
| `zone_graph.graphml` | Zone graph (readable with networkx and similar tools) |


## 7. Video

`video/<camera>.mp4`: H.264, `width`×`height`, same fps as the ground truth. `render_log.json`: `{"frames": [start, end], "cameras": {name: rendering seconds}, "people_placed", "total_s"}`.
Each person is rendered with a different clothing color (`people.tint_index`). The rendering mode is RAY_TRACE.

## 8. Examples of use for training

**Detection and single-camera tracking** (tools that read the MOTChallenge format can be used as is)

```python
import cv2, numpy as np
gt = np.loadtxt(f"{run}/mot/CamGate.txt", delimiter=",")       # frame, id, x, y, w, h, conf, class, vis
cap = cv2.VideoCapture(f"{run}/video/CamGate.mp4")
k = 0
while (ok := cap.read())[0]:
    img = ok[1]
    rows = gt[(gt[:, 0] == k + 1) & (gt[:, 8] >= 0.4)]           # when all frames are rendered: video frame k = MOT frame k+1
    k += 1
```

**Crops for person re-identification (ReID) training**: crop the boxes in `mot/<camera>.txt` from the video, using `id` as the person number and the number in `aicity/cameras.json` as the camera number
(with the Market-1501 naming convention, `{id:04d}_c{camera}s1_{frame:06d}_00.jpg`). Drop boxes with low visibility.

**Multi-camera tracking**: use `aicity/gt.txt` as ground truth (the same person has the same `obj_id` in all cameras, with the world coordinates of the feet).

**Trajectory prediction and graph learning**: `frames.csv.gz` (exact positions of everyone) or `graph/` (counts and flows per zone and per cell). To restrict to what the cameras can see, use `observed` in `graph.json`.

**State classification (VLM, etc.)**: match `people[name].states` with the boxes (`mot`) in the same video frames.

## 9. Caveats for training (limitations of the current version)

- The `mot/` boxes are approximations obtained by projecting a box enclosing the person, and are not tight to the rendered outline. Visibility is also approximate. For training and evaluating detection and tracking, use `labels/` (section 4), produced at rendering time.
  `occlusion` in `labels/` includes frames interpolated between the full-body pixel counts measured every 30 frames (`occ_source`). The share behind glass (`glass`) is an approximation counted on points of the body, and the `tight` box is not shrunk. Masks and depth are not output.
  Replicator sometimes does not return a person who appears partway through a rendered chunk for a while (at worst until the end of the chunk), or returns them under the name of a person who has already left (sometimes two people in one box). Those rows have `occ_source` `unlabeled`.
- There are 10 character models, and people are told apart by giving each person a different clothing color. Training person re-identification on this data alone risks learning the shortcut of distinguishing people by clothing color alone.
- Distortion, noise, compression, lighting changes, camera clock offsets, and frame drops are not included (`clock_offset_s` and `drop_rate` are only recorded).
- There are no 3D boxes, poses (keypoints), faces, etc. Only a single floor.
- Asset license terms: the spaces (office, hospital, warehouse) are CC BY 4.0 (NVIDIA Isaac Sim assets; give credit). The terms for the character models have not been confirmed, so check them before releasing generated data outside.
  Anything made from the video or floor plans of a real building is kept separate from this data location.

## 10. Ward layout and walking distances (`ward_layout.json`)

`twinsim ward-layout [--space hospital]` → `<TWINSIM_DATA>/ward/hospital_ward_layout.json`. From the space's `ward.yaml` (beds and nurse-station layouts),
it computes the shortest walkable distances. The "ward execution delays" of the workbench in `~/digitaltwin` (`workbench/bridge/ward.py`) use them for nurses' walking times.

| Key | Contents |
|---|---|
| `space`, `source`, `note` | Space name, source of the layout, description |
| `beds` | `[{name, ward, xy}]`. The walkable point nearest to each bed (the corridor in front of the room) |
| `layouts` | `{layout: {station: [x, y]}}` (e.g. `reception`, `best1`, `best2`) |
| `points`, `names` | `{name: [x, y]}` (bed names and `layout:station`) and their order |
| `dist_m` | `dist_m[i][j]` = shortest walkable distance from `names[i]` to `names[j]` (m, Dijkstra on a 0.25 m grid) |
| `paths` | `{"layout:station|bed": [[x, y], ...]}`. Points of the shortest walkable path from the station to the bed (the grid path thinned to a 0.2 m tolerance; the way back is the reverse). The workbench uses them to draw the nurses' movements |

## 11. Format of real logs (input of `twinsim calibrate`)

`twinsim calibrate <base scenario> --gate-log a.csv --ev-log b.csv [--ev-mode fit|replay] [--id name] [--out path]`. Results are written to `<TWINSIM_DATA>/calibration/<id>/scenario.yaml` and `report.json`.

| File | Columns |
|---|---|
| `gate_log.csv` | `time_s, gate, lane, direction` (`in`, `out`), optionally `person` |
| `ev_log.csv` | `time_s, car, boarded, alighted` |

Times are aligned so that the earlier of the two logs starts at 0. `twinsim export-logs <run>` writes examples of these files.
