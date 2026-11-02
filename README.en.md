# twinsim — a people-flow simulator for buildings and factories

[日本語](README.md)

Define the space, the distribution of people, cameras and events (elevators, gates) in a **JSON configuration**. twinsim computes how people move on the CPU and writes **ground-truth labels for object detection and tracking**, state labels, aggregates and graphs.
It can be called as a Python library. When video is needed, it is rendered with Isaac Sim.

`main` contains the simulator only (the MOPF detection/tracking integration and person re-identification are on the `with-mopf` branch).

## Installing

```bash
pip install "git+https://github.com/fujisawa-yoshihiko/twinsim.git"   # private repository: read access is required
```

Python 3.10 or later. The dependencies are numpy, scipy, pyyaml, pillow, networkx and matplotlib. No GPU is needed (only rendering needs Isaac Sim and a GPU).
The spaces and templates are included in the package. Reading videos needs ffmpeg. Japanese text in figures uses Noto Sans CJK (`fonts-noto-cjk` on Ubuntu; without it the labels in figures are harder to read).

The examples (`examples/`) and documents are not in the package, so get the repository to run the examples.

```bash
git clone https://github.com/fujisawa-yoshihiko/twinsim.git && cd twinsim && uv sync
```

## Using it from Python

```python
import twinsim

config = {
    "name": "minimal", "space": "office", "duration_s": 60, "seed": 1,
    "people": {"profile": "office_commute_jp"},
    "streams": [{"name": "commuters", "origin": "entrance",
                 "rate": {"type": "constant", "per_min": 20, "unit": "persons"},
                 "destinations": [{"to": "south_exit", "via": ["gate"]}]}],
    "cameras": [{"name": "CamGate"}, {"name": "CamEV"}],
    "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"],
}

result = twinsim.simulate(config, out_dir="runs/minimal")   # a dict, JSON string, JSON file or template name
print(result.summary["people"])
labels = result.mot("CamGate")     # object-detection labels [frame, id, x, y, w, h, conf, class, visibility]
for row in result.frames():        # one row per frame per person (position, heading, state)
    ...
```

The functions and `Result` are in **[docs/library.en.md](docs/library.en.md)**. To write a JSON configuration, see the **[tutorial](docs/config-tutorial.en.md)**; every key is in the **[reference](docs/config-reference.en.md)**. Code examples are in [examples/](examples/README.en.md).

## Commands

```bash
twinsim templates                        # list the templates
twinsim template office_gate_ev --out config.json   # write a template as JSON (a starting point)
twinsim validate config.json             # check a configuration (does not simulate)
twinsim run config.json --out runs/test  # simulate (CPU; about 20 s for 5 minutes and about 100 people)
twinsim check runs/test                  # checks (inside walls, closeness of people) and the comparison with the literature (validity.md, png)
twinsim calibrate config.json --gate-log gate_log.csv --ev-log ev_log.csv   # fit to real data
```

Inside this repository, use `./run.sh <command>` (results go to `~/dt-data/twinsim/runs/` by default).

## GUI

`twinsim serve` starts the GUI (127.0.0.1:8770); `twinsim serve --url` shows the URL to open. From another PC, keep `ssh -N -L 8770:localhost:8770 <server>` running while you open it. Inside the repository, `./run.sh serve` also works (it keeps results in `~/dt-data/twinsim`).
There are two tabs: Settings (scenario, distribution of people, cameras) and Results (summary, check figure, comparison with the literature, videos, downloads). The top right switches between 日本語 and English.

## Rendering (GPU)

```bash
./isaac_up.sh                                      # start Isaac Sim (one-gpu chooses the GPU; stop it with isim down)
./run.sh render runs/test --frames 7395 7544       # a test render (twinsim.render from code)
```

Rendering needs the repository's `./isaac_up.sh` and the Isaac Sim environment `isim`.

| Stage | office_gate_ev (5 min, 94 people, 2 cameras, 1280×720) | Relative to video length |
|---|---|---|
| Computing the movement (CPU) | About 15 s | 0.05× |
| Rendering (Isaac Sim, RAY_TRACE) | 42 min per camera, 89 min for 2 (including 1 min of loading) | About 8.5× per camera |
| Encoding to mp4 | About 3 min for 2 cameras | |

Rendering speed depends on the space (frames per second: office 3.5–5.7, warehouse 1.9, hospital 1.1). See `./stop.sh` and [docs/operations.en.md](docs/operations.en.md) for stopping.

## Output formats (training data and ground-truth labels)

Ground-truth labels for object detection and tracking, and training data for people-flow prediction, GNNs and VLMs. Details are in [docs/formats.en.md](docs/formats.en.md).
Coordinates are world meters (Z up); simulator frames start at 0 (seconds = frame ÷ 30).

| File | Format | Contents |
|---|---|---|
| `scenario_resolved.json` | JSON | The configuration with defaults filled in. Passing it back gives the same run |
| `ground_truth.json` | JSON | Per-person trajectories `tracks[name] = [[x, y, yaw], …]`, whether walking, state intervals, events (gate, elevator), attributes (character model, height, type, group), cameras (4×4 matrix and field of view), zones |
| `frames.csv.gz` | CSV | One row per frame per person: `frame, t, person, x, y, yaw, moving, state, zone, group, type` |
| `mot/<camera>.txt`, `mot/ids.json` | MOTChallenge | `frame, id, x, y, w, h, 1, 1, visibility` (frames start at 1; the id is the same across cameras) |
| `aicity/gt.txt` | AI City MTMC | `camera_id obj_id frame_id xmin ymin width height xworld yworld` |
| `video/<camera>.mp4` | H.264 | Rendered video (1280×720, 30 fps). Frame k = `frames[0]` in `render_log.json` + k |
| `tasks.json` | JSON | Ground truth for the six tasks on p. 7 of the research plan (counts, gate crossings, dwelling, groups, congestion, destinations, elevator waits) |
| `graph/` | JSON, CSV, NPZ, GraphML | Zone graph and 2 m grid graph, per-second counts, per-minute flows, what each camera sees |
| `logs/` | CSV | Gate crossing logs and elevator operation logs (the same format as real data). Made with `twinsim export-logs <run>` |
| `<TWINSIM_DATA>/ward/<space>_ward_layout.json` | JSON | Ward beds, nurse-station layouts, and the walkable distances and paths between them (`twinsim ward-layout`) |

States: `pass`, `gate_queue`, `ev_approach`, `ev_wait`, `alight`, `reception`, `dwell`, `sign_check`, `companion_wait` (warehouse: `work`, `wait`).
Notes: boxes are approximate projections of a box around the person (not tight to the silhouette), and visibility is approximate too. There are 10 character models, and each person's clothing color is varied.

## Basis of the movement

Walking speed, speed versus density, following, groups, elevator demand and gate service times come from the literature, and every run is compared with the literature (`validity.md`).
The sources, the check results and the assumed values are in [docs/validity.en.md](docs/validity.en.md).

## Structure

| Location | Contents |
|---|---|
| `twinsim/api.py`, `__init__.py` | The Python entry points (`simulate`, `Result`, ...) |
| `twinsim/__main__.py` | Commands |
| `twinsim/scenario.py`, `dists.py` | Configuration and distributions → people, destinations, elevators, gates |
| `twinsim/space.py` | Spaces (walkable grid, semantic map, A* routes, walking distances) |
| `twinsim/engine.py` | Movement (plans, avoidance, gate queues, multiple elevators) |
| `twinsim/literature.py`, `validity.py` | Literature-based distributions (with sources) and the comparison with the literature after each run |
| `twinsim/calibrate.py` | Fitting to real data (gate logs, elevator logs) |
| `twinsim/outputs.py`, `camera.py`, `quality.py` | Ground truth, aggregates, graphs, boxes, checks |
| `twinsim/server.py`, `static/` | GUI and REST API |
| `twinsim/isaac_bridge.py`, `isaac/` | Rendering with Isaac Sim and building spaces from USD |
| `twinsim/spaces/` | Spaces (office, hospital, warehouse, simple_room, warehouse_small, corridor, corridor_door) |
| `twinsim/templates/` | Templates (table below) |
| `twinsim/config.py` | Locations (environment variables such as `TWINSIM_DATA`, `TWINSIM_SPACES`, `TWINSIM_ISAAC_WORK`) |
| `examples/` | Tutorial examples (simulating, changing settings, ground-truth labels, getting videos, training data) |
| `tests/` | Checks (`uv run --group dev pytest -q`; lint with `uv run --group dev ruff check`) |

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

## Assets

The images and walkable maps of the spaces `office`, `hospital`, `warehouse`, `warehouse_small` and `simple_room` are made from NVIDIA Isaac Sim assets (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ ). See [NOTICE.md](NOTICE.md).
