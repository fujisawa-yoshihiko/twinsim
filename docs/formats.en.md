# Output formats (training data and ground-truth labels)

[日本語](formats.md)

The formats of the files written out by twinsim's computation, rendering, and integration. Intended for people who use them for other purposes, such as detection, tracking, multi-camera tracking, person re-identification, people-flow prediction, graph learning, and state classification (VLM).
This is the 2026-10-23 version (v0.4).

## 0. Common conventions

| Item | Convention |
|---|---|
| Location | `~/dt-data/twinsim/runs/<run-name>/` (can be changed with the environment variable `TWINSIM_DATA`). Not put in git |
| Coordinates | World coordinates (m). Z is up. The floor height is the space's `levels[0].z` (0 for office). x and y are the same as in `spaces/<space>/space.yaml` |
| Heading (yaw) | Degrees. Counterclockwise from +X (`atan2(dy, dx)`). −180 to 180. While walking, the direction of travel; while stopped, the direction the person is facing |
| Time | Simulator frames start at 0; seconds = frame ÷ fps (default 30). Times in `events` and elsewhere are in seconds |
| Frame number offset | The MOT and AI City formats are 1-based (= simulator frame + 1). Frame k of the video = simulator frame `frames[0]` of `render_log.json` + k (identical when all frames are rendered) |
| Person names | `P0001`… (reassigned for each run). The numeric IDs in MOT and AI City map to names via `mot/ids.json` (the same across cameras) |
| Groups | Ground-truth groups are `G001`… (sets of people who walk together). Global IDs from inference are `M001`… (`links.json`; a different thing) |
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
`h_fov_deg`, `tilt_down_deg`, `fps`. `Camera` in `twinsim/camera.py` and `cctv_eval_lib.Camera` in the research code can read them as is.

## 1. List of files

| File | Contents | Main uses |
|---|---|---|
| `ground_truth.json` | Per-person trajectories, states, events, and attributes; cameras; elevator (EV) and gate events; zones | Source of all ground truth |
| `frames.csv.gz` | A table with one row per person per frame | Trajectory prediction, aggregation, spreadsheets |
| `mot/<camera>.txt` and `mot/ids.json` | Per-camera person boxes (MOTChallenge format) | Training and evaluating detection and single-camera tracking |
| `aicity/gt.txt` and `aicity/cameras.json` | Multi-camera boxes and world positions (AI City Challenge MTMC format) | Multi-camera tracking, person re-identification |
| `video/<camera>.mp4` and `render_log.json` | Rendered videos (H.264, same fps as the ground truth) and the rendered range | Image-based training together with the boxes above |
| `tasks.json` | Ground-truth aggregates for the six tasks on p. 7 of the research plan | Evaluating counts, flows, dwelling, and congestion |
| `graph/` | Zone graph and grid graph, and time series of counts and flows | GNN and time-series prediction |
| `logs/` | Gate passage logs and elevator operation logs (same format as real data) | Example for calibrating with real data (`calibrate`) |
| `summary.json` and `scenario_resolved.yaml` | Summary, and the scenario with defaults filled in (including the random seed) | Regeneration, logging |
| `validity.*` and `preview.png` | Comparison with the literature, figures for checking | Validity of the people distribution |
| `mopf/`, `mopf_tracks/`, `mopf_eval/`, `mopf_graph/` | MOPF configuration, tracking, and comparison ([integration.en.md](integration.en.md)) | Evaluating MOPF |

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

`aicity/gt.txt` (same as AI City Challenge MTMC, space-separated): `camera_id obj_id frame_id xmin ymin width height xworld yworld`.
`camera_id` comes from `aicity/cameras.json` (`{"CamEV": 1, …}`), `obj_id` is the same as in `mot/ids.json`, `frame_id` is 1-based, and `xworld yworld` are the world coordinates of the feet (m).

## 5. `tasks.json` (the six tasks on p. 7 of the research plan)

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

Files of the same format built from MOPF tracking are in `mopf_graph/<camera>/` (the intermediate graph layer when building from video).

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

## 10. Ward layout and walking distances (`ward_layout.json`)

`./run.sh ward-layout [--space hospital]` → `~/dt-data/twinsim/ward/hospital_ward_layout.json`. From the space's `ward.yaml` (beds and nurse-station layouts),
it computes the shortest walkable distances. The "ward execution delays" of the workbench in `~/digitaltwin` (`workbench/bridge/ward.py`) use them for nurses' walking times.

| Key | Contents |
|---|---|
| `space`, `source`, `note` | Space name, source of the layout, description |
| `beds` | `[{name, ward, xy}]`. The walkable point nearest to each bed (the corridor in front of the room) |
| `layouts` | `{layout: {station: [x, y]}}` (e.g. `reception`, `best1`, `best2`) |
| `points`, `names` | `{name: [x, y]}` (bed names and `layout:station`) and their order |
| `dist_m` | `dist_m[i][j]` = shortest walkable distance from `names[i]` to `names[j]` (m, Dijkstra on a 0.25 m grid) |

## 9. Caveats for training (limitations of the current version)

- The boxes are approximations obtained by projecting a box enclosing the person, and are not tight to the rendered outline. Visibility is also approximate (no depth or masks are output). Training a detector requires outputting tight boxes, masks, and depth with Isaac Sim's Replicator at rendering time (not implemented).
- There are 10 character models, and people are told apart by giving each person a different clothing color. Training person re-identification on this data alone risks learning the shortcut of distinguishing people by clothing color alone.
- Distortion, noise, compression, lighting changes, camera clock offsets, and frame drops are not included (`clock_offset_s` and `drop_rate` are only recorded).
- There are no 3D boxes, poses (keypoints), faces, etc. Only a single floor.
- Asset license terms: the spaces (office, hospital, warehouse) are CC BY 4.0 (NVIDIA Isaac Sim assets; give credit). The terms for the character models have not been confirmed, so check them before releasing generated data outside.
  Anything made from the actual Takeshiba video or floor plans is kept separate from this data location (NDA).
