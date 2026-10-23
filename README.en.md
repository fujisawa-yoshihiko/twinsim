# twinsim — a people-flow digital-twin simulator for buildings and factories

[日本語](README.md)

A 3D simulator for checking the research plan (Takeshiba VLM × QUBO, 10/4 version) and the digital-twin concept.
The space (USD), the distribution of people, the cameras and the events (elevator (EV), gates) are defined in a scenario file, people's movement is computed on the CPU,
and the ground truth, aggregates, graphs for GNNs and per-camera bounding boxes are written out. When video is needed, it is rendered with Isaac Sim. The specification is in [docs/spec.en.md](docs/spec.en.md).

## Starting

```bash
cd ~/twinsim
./run.sh serve                 # GUI (127.0.0.1:8770). Running ./run.sh serve --url in another terminal prints the URL to open
./run.sh templates             # list the templates
./run.sh run office_gate_ev    # compute (CPU; about 20 s for 5 min with about 100 people)
./run.sh check ~/dt-data/twinsim/runs/office_gate_ev   # check (also writes the comparison with the literature, validity.md, and png files)
./isaac_up.sh 2                # only when rendering: start Isaac Sim on GPU 2 (stop it with isim down)
./run.sh render ~/dt-data/twinsim/runs/office_gate_ev --frames 7395 7544   # test render
./run.sh mopf-process ~/dt-data/twinsim/runs/office_gate_ev   # detect and track people in the videos with MOPF (start MOPF first; GPU)
./run.sh mopf-eval ~/dt-data/twinsim/runs/office_gate_ev      # compare MOPF's tracking with the ground truth; intermediate graph layer
./run.sh calibrate office_gate_ev --gate-log gate_log.csv --ev-log ev_log.csv   # calibrate with real data
./run.sh mopf-sync ~/dt-data/twinsim/runs/office_gate_ev      # video of the 2 cameras synchronized in time, and the ID correspondence table of the same person across cameras
./run.sh mopf-link ~/dt-data/twinsim/runs/office_gate_ev      # infer cross-camera association without ground truth and score it (also the prediction video; re-ID weights via tools/fetch_reid_weights.sh)
```

To open the GUI in a browser on your local PC, keep `ssh -N -L 8770:localhost:8770 ampb` running on your local PC and open the URL printed by `./run.sh serve --url`.
The screen has 3 tabs: "Settings" (scenario, distribution of people, cameras), "Results" (summary, check figures, comparison with the literature, videos, comparison with MOPF, downloads) and "MOPF" (start, live, stop).
The display can be switched between 日本語 and English at the top right (the browser remembers the choice). Text inside the result figures and videos, and validity.md, stays in Japanese.
The structure and the development procedure are in [docs/architecture.en.md](docs/architecture.en.md).

Results go to `~/dt-data/twinsim/runs/<name>/` (the trajectories can be checked in `preview.png`). For rendering, see "Rendering" in docs/spec.en.md.

## Output formats (training data and ground-truth labels)

A summary for people using the data for other purposes (detection, tracking, multi-camera tracking, person re-identification, people-flow prediction, GNNs, VLMs). Details: [docs/formats.en.md](docs/formats.en.md).
Files are under `~/dt-data/twinsim/runs/<run-name>/`. Coordinates are world meters (Z up); simulator frames start at 0 (seconds = frame ÷ 30).

| File | Format | Contents |
|---|---|---|
| `ground_truth.json` | JSON | Per-person trajectories `tracks[name] = [[x, y, yaw], …]`, whether walking, state intervals, events (gate, elevator), attributes (character model, height, type, group), cameras (4×4 matrix and field of view), zones |
| `frames.csv.gz` | CSV | One row per frame per person: `frame, t, person, x, y, yaw, moving, state, zone, group, type` |
| `mot/<camera>.txt`, `mot/ids.json` | MOTChallenge | `frame, id, x, y, w, h, 1, 1, visibility` (frames start at 1; the id is the same across cameras) |
| `aicity/gt.txt` | AI City MTMC | `camera_id obj_id frame_id xmin ymin width height xworld yworld` |
| `video/<camera>.mp4` | H.264 | Rendered video (1280×720, 30 fps). Frame k = `frames[0]` in `render_log.json` + k |
| `tasks.json` | JSON | Ground truth for the six tasks on p. 7 of the research plan (counts, gate crossings, dwelling, groups, congestion, destinations, elevator waits) |
| `graph/` | JSON, CSV, NPZ, GraphML | Zone graph and 2 m grid graph, per-second counts, per-minute flows, what each camera sees |
| `logs/` | CSV | Gate crossing logs and elevator operation logs (the same format as real data) |

States: `pass`, `gate_queue`, `ev_approach`, `ev_wait`, `alight`, `reception`, `dwell`, `sign_check`, `companion_wait` (warehouse: `work`, `wait`).
Notes: boxes are approximate projections of a box around the person (not tight to the silhouette), and visibility is approximate too. There are 10 character models, and each person's clothing color is varied.

## Stopping

The GPUs are shared with other users, so stop things when you are done. After stopping, check with `nvidia-smi` that the GPUs have been freed (`./stop.sh` shows it at the end).

| What to stop | How | Notes |
|---|---|---|
| GUI server (port 8770) | `Ctrl+C` in the terminal where it was started, or `./stop.sh gui` | CPU only. If it was started in the background (e.g. with `setsid`), use `./stop.sh gui` |
| MOPF (uses 1 GPU) | "Stop" on the "MOPF" tab of the GUI, or `./stop.sh mopf` (= `~/MOPF_ALL_video/stop_ampb.sh`) | The data and the images are kept |
| Isaac Sim (rendering, uses 1 GPU) | `./stop.sh isaac` (= `isim down`) | If a render is in progress, it stops too. To render next time, `./isaac_up.sh <GPU>` |
| Overnight rendering and comparison processing (`tools/night_b.sh`) | Look up the process ID with `pgrep -af night_b` and run `kill <PID>` | Rendering (inside Isaac Sim) keeps going, so to stop it also run `./stop.sh isaac`. If rendering has finished, `tools/night_b.sh --resume` continues from where it left off |
| Everything at once | `./stop.sh` (GUI and MOPF), `./stop.sh all` (Isaac Sim too) | |

## Time needed to produce video (measured on 2026-10-23, one RTX PRO 6000 GPU)

| Stage | office_gate_ev (5 min, 94 people, 2 cameras, 1280×720) | Relative to the video length |
|---|---|---|
| Computing people's movement (CPU) | about 15 s | 0.05× |
| Rendering (Isaac Sim, RAY_TRACE) | 42 min for 1 camera, 89 min for 2 (including 1 min of loading; the cameras are rendered one at a time) | about 8.5× per camera |
| Converting to mp4 | about 3 min for 2 cameras | |
| Detection and tracking with MOPF (yolo11m, BoostTrack) | about 3 min per camera | 0.6× |
| Comparison, overlay video, side-by-side video (CPU) | a few seconds; 2–3 min per camera; 3–4 min | |

- Rendering speed differs by space (test-render values): office 3.5–5.7 frames per second, warehouse 1.9 frames (about 16×), hospital 1.1 frames (about 27×; many lights).
- Ways to make it faster: render each camera on a separate GPU at the same time (half the time with 2 GPUs; at most 2 GPUs at a time), lower the resolution, use 15 frames per second (the effect on MOPF's tracking still needs to be checked).

## Structure

| Location | Contents |
|---|---|
| `twinsim/space.py` | Space (grid of the walkable area, semantic map, A* routing) |
| `twinsim/engine.py` | People's movement (itineraries, mutual avoidance, gate queues, multiple elevators (EVs)). An extension of hospital-sim's flow_scene2_lib |
| `twinsim/scenario.py`, `dists.py` | Scenarios and distributions → spawning of people, destinations, EVs, gates |
| `twinsim/literature.py`, `validity.py` | Distributions of people based on the literature (with sources, `people.profile`, `demand`) and the comparison with the literature after a run ([docs/validity.en.md](docs/validity.en.md)) |
| `twinsim/calibrate.py` | Calibrates values with real data (gate passage logs, elevator operation logs). Writes simulator results out in the log format (`export-logs`) |
| `twinsim/mopf/` | Integration with MOPF ([docs/integration.en.md](docs/integration.en.md)): `monitor` (flow monitor settings), `process` (detection and tracking on videos), `evaluate` (comparison with the ground truth), `graph` (intermediate graph layer), `crossings` (how line crossings are counted), `overlay` (overlay video), `identity` (aligning the 2 cameras in time), `linking` (inferring cross-camera association), `control` (start/stop), `synthetic` (for verification), `io` |
| `twinsim/config.py` | Locations and connection targets (can be changed with environment variables such as `TWINSIM_DATA`, `TWINSIM_MOPF_HOME`, `TWINSIM_MOPF_URL`, `TWINSIM_ISAAC_WORK`) |
| `twinsim/outputs.py`, `camera.py`, `quality.py` | Ground truth, aggregates, graphs, bounding boxes, checks |
| `twinsim/api.py`, `__main__.py` | Python API and commands |
| `twinsim/isaac_bridge.py`, `isaac/` | Rendering in Isaac Sim, and components that build a space from USD (`isaac/vendor/` holds the person components copied from hospital-sim) |
| `spaces/` | Spaces (office, hospital, warehouse, simple_room, warehouse_small, corridor (a corridor for verification)) |
| `templates/` | Templates (table below) |
| `tests/` | Operation checks (`uv run --group dev pytest -q`; style check with `uv run --group dev ruff check`) |
| `pyproject.toml`, `uv.lock` | Dependencies (`./run.sh` is `uv run twinsim`; it creates `.venv` on the first run) |

| Template | What it checks |
|---|---|
| `office_smoke` | Operation check (30 s) |
| `office_gate_ev` | Gate → elevator (UC1, UC2; the two-point flow of Research 2). The busiest 5 minutes of the morning (building population 600, distribution of people from literature values), 2 cameras |
| `office_ev_hall` | Ambiguous states in the elevator hall (RQ1 of Research 1). Waiting for an elevator, waiting for companions, checking directions, reception |
| `office_signage_ab` | Signage comparison (UC3). With the same arrivals, the share of people who look at the signage differs between A and B (verifies the method of measuring the effect; the effect itself cannot be verified) |
| `hospital_gate_ev` | Hospital lobby → elevators in the west hall (same layout and cameras as hospital-sim's sim-gate; can be compared with the data of the earlier evaluation) |
| `warehouse_picking` | Warehouse picking ("work, wait, move" in the factory diagram). Receiving → shelf → packing → wait → shelf → packing → leave |
| `simple_room_smoke` | Operation check (small room, 20 s) |
| `verify_corridor_speed`, `verify_fundamental_diagram`, `verify_groups`, `verify_gate_capacity`, `verify_counterflow`, `verify_bottleneck` | Engine verification (walking straight, speed and density, groups, a crowded gate, counterflow, a 1 m wide doorway). The results are in section 5 of docs/validity.en.md |

## Correspondence with the wanted features (the "Simulator" page in Notion) (evening of 2026-10-22)

| Wanted feature | Status |
|---|---|
| A 3D simulator that can check the contents of the PDF | Works end to end through people's movement, ground truth, aggregates and rendering (test renders done for the office, hospital and warehouse) |
| Selectable spaces (office, hospital, warehouse, small room) | The office, hospital and warehouse are usable. The small room is computation only (rendering is pitch black). The small warehouse has assets only |
| Open USD / uploading your own | `export-space` (assets and a skeleton from a USD at a URL or a local path) + `show-space` (a figure that draws the semantic map). Uploading from the screen: not yet |
| Control of the distribution of people | Done (arrival rate, grouping, types, destinations, speed, dwell time). Literature profile (`people.profile`) and elevator users derived from the number of people in the building (`demand`), a comparison with the literature for each run and a ledger of the evidence (`validity.md`). Values without literature are explicitly marked "provisional" |
| Control of cameras, spawning, movement and events (GUI, documents) | Done: scenario files, documents, GUI (drag the cameras on the top-down view, change values, then compute and render) |
| Templates | 7 (table above) |
| API (MOPF, GNN) | Done: REST API, Python API, graph export, automatic creation of MOPF flow monitor settings and the counts it should produce. Detecting and tracking people in videos with MOPF and comparing with the ground truth (`mopf-process`, `mopf-eval`), an intermediate graph layer of the same form from MOPF's tracking, readable from the research code, AI City format. Calibration with real data (`calibrate`). Verification with MOPF running on the GPU: not yet |

GUI: `./run.sh serve` (URL via `./run.sh serve --url`). To check the screen: `uv run --group gui-test python tools/gui_shot.py`.
