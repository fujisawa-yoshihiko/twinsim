# Using twinsim as a Python library

[日本語](library.md)

`twinsim` can be imported and called. Configurations are passed as JSON. No GPU is needed (except for rendering). Installation is in the [README](../README.en.md).

## Shortest example

```python
import twinsim

result = twinsim.simulate("config.json", out_dir="runs/test")
print(result.summary["people"], "people")
labels = result.mot("CamGate")   # ground-truth labels for object detection
```

Start from a template.

```bash
twinsim template office_gate_ev --out config.json
```

```python
config = twinsim.template("office_gate_ev")   # returns a dict
config["duration_s"] = 120
result = twinsim.simulate(config, out_dir="runs/short")
```

## Functions

| Function | What it does |
|---|---|
| `twinsim.simulate(config, out_dir=None, overrides=None, elevator_policy=None)` | Computes the movement, writes the ground-truth labels and other files, and returns a `Result`. Does not render |
| `twinsim.validate(config, overrides=None)` | Checks a configuration and returns a dict with defaults filled in. Raises `ValueError` on errors. Does not simulate |
| `twinsim.load_config(config, overrides=None)` | Same as `validate` (a name for reading) |
| `twinsim.template(name)` | Returns a template as a dict (defaults are not filled in) |
| `twinsim.list_templates()`, `twinsim.list_spaces()` | Names of the templates and spaces |
| `twinsim.open_result(out_dir)` | Open a finished result folder and return a `Result`, without simulating again |
| `twinsim.render(out_dir, frames=None, cameras=None, preset="RAY_TRACE", tint=None, chunk_s=None, keep_frames=True, labels=False, preroll=0, cull=False)` | Renders a result with Isaac Sim and writes `video/<camera>.mp4`. Uses a GPU. Raises `RuntimeError` if Isaac Sim is not running. `frames` is a range of simulator frames (both ends included); `tint=False` keeps the original clothing colors (`None` follows `render.tint` in the configuration). With `chunk_s` (seconds), the work is split per camera and per that length, and every running receiver renders in parallel ([README, "Rendering in parallel"](../README.en.md#parallel)). `keep_frames=False` deletes the working images after encoding the mp4. `labels=True` takes per-person boxes and occlusion from the rendering and writes `labels/<camera>.csv` ([docs/formats.en.md, section 4](formats.en.md); about 1.5 to 3 times as long). `preroll` (frames) renders that many extra frames before each part and discards them (removes the slight difference in the first 1 or 2 frames of a part; 3 is a good value), and `cull=True` places only the people near the camera in each per-camera part (with `chunk_s`; the more people, the faster) |

What `config` accepts:

| Form | Example |
|---|---|
| dict | `{"space": "office", "duration_s": 60, ...}` |
| JSON string | `'{"space": "office", ...}'` |
| File path (`.json`, `.yaml`) | `"config.json"`, `pathlib.Path` |
| Template name | `"office_gate_ev"` |

`overrides` is a dict that replaces part of the configuration, useful for repeated runs with different values.

```python
for seed in range(5):
    r = twinsim.simulate("config.json", out_dir=f"runs/s{seed}", overrides={"seed": seed})
```

Without `out_dir`, results go to `<TWINSIM_DATA>/runs/<the configuration's name>` (`TWINSIM_DATA` defaults to `~/.twinsim`). Running again in the same place replaces the previous result (videos and render records move to `before_<date>/`).

## Result

| Name | Contents |
|---|---|
| `result.out_dir` | The result folder |
| `result.summary` | Summary dict (people, elevators, gates, time per state, `files`, ...); same as `summary.json` |
| `result.config` | The configuration with defaults filled in; same as `scenario_resolved.json` |
| `result.files` | The files written |
| `result.cameras` | Names of cameras with boxes |
| `result.mot(camera)` | Array of ground-truth labels for detection and tracking. Columns: `frame, id, x, y, w, h, conf, class, visibility` (frames start at 1) |
| `result.frames()` | Yields one dict per frame per person (`frame, t, person, x, y, yaw, moving, state, zone, group, type`) |
| `result.videos` | A dict of rendered videos (camera → mp4 path) |
| `result.video_first_frame` | The simulator frame of the video's first frame. When only part was rendered, the video starts partway through |
| `result.video_frames(camera, frames=None, step=1)` | Yields video frames in order as `(simulator frame, height × width × 3 RGB array)`. Uses ffmpeg. `frames` is a range of simulator frames (both ends included) |
| `result.ground_truth()` | `ground_truth.json` (per-person trajectories, states and events; cameras; elevator and gate events) |
| `result.tasks()` | `tasks.json` (aggregates such as counts per place, crossings, dwelling) |
| `result.validity()` | `validity.json` (comparison with the literature), when `outputs` includes `validity` |

File formats are in [formats.en.md](formats.en.md). [examples/](../examples/README.en.md) has worked examples, from simulating to getting videos. As a guide, leave boxes with visibility below 0.4 out of training and evaluation.

## Configuration (JSON)

The smallest example ([examples/minimal.json](../examples/minimal.json)):

```json
{
  "name": "minimal",
  "space": "office",
  "duration_s": 60,
  "seed": 1,
  "people": {"profile": "office_commute_jp"},
  "streams": [
    {
      "name": "commuters",
      "origin": "entrance",
      "rate": {"type": "constant", "per_min": 20, "unit": "persons"},
      "destinations": [{"to": "south_exit", "via": ["gate"]}]
    }
  ],
  "cameras": [{"name": "CamGate"}, {"name": "CamEV"}],
  "outputs": ["ground_truth", "frames", "tasks", "mot", "validity"]
}
```

| Key | Contents |
|---|---|
| `space` | A space name (`twinsim.list_spaces()`) or the folder of your own space. Required |
| `name`, `title` | Names |
| `seed` | Random seed |
| `duration_s`, `fps` | Length (s, default 120) and frames per second (default 30) |
| `people` | Distribution of people: `profile` (a set of literature values: `office_commute_jp`, `leisure_low_density`), `speed`, ... |
| `demand` | Elevator demand (`population`, `period`, `peak_pct_5min`) |
| `streams` | Flows of people (where they appear, arrival rate, destinations). Where they appear is a place name or coordinates |
| `elevator`, `gates` | Elevator operation and gate service times |
| `cameras` | Cameras: a candidate name from the space, or your own `eye`, `target`, `focal_mm`, ... |
| `render` | Render size (`width`, `height`), clothing colors (`tint`), placed objects (`props`) |
| `outputs` | What to write (`ground_truth`, `frames`, `tasks`, `graph`, `mot`, `aicity`, `preview`, `validity`) |

To learn step by step, see the [tutorial](config-tutorial.en.md). Every key and how to write distributions are in the [reference](config-reference.en.md). The sets of literature values are in [validity.en.md](validity.en.md).

To get ground-truth labels for object detection, list cameras in `cameras` and include `mot` in `outputs`.

### Moving where people appear and the cameras

Where people appear (`streams[].origin`) can be a place name or coordinates. Coordinates are world coordinates (m).

```json
"streams": [
  {"name": "a", "origin": "entrance", "rate": 5, "destinations": ["south_exit"]},
  {"name": "b", "origin": {"xy": [-3.0, 20.0]}, "rate": 5, "destinations": ["south_exit"]},
  {"name": "c", "origin": {"line": [[-4.0, 20.0], [-2.0, 20.0]], "name": "north_door"}, "rate": 5, "destinations": ["south_exit"]}
]
```

| Form | Where people appear |
|---|---|
| `"entrance"` | A place in the space (see the image from `twinsim show-space <space>` or the map in the GUI; not available for the `corridor` spaces, which have no top-down image) |
| `{"xy": [x, y]}` | That point |
| `{"line": [[x0, y0], [x1, y1]]}` | Somewhere on the line (an entrance with a width) |

Adding `name` sets the label used in the counts (`flow`, `od_per_min`). Without it, the stream name is used. Coordinates outside the walkable area, or from which the destinations cannot be reached, raise `ValueError` before simulating (the message shows the nearest walkable point). `meet.from` takes the same forms. Destinations are place names only; they cannot be coordinates.

For cameras (`cameras[]`), values added to a candidate name override only those values. A new name requires `eye` and `target`.

```json
"cameras": [
  {"name": "CamGate", "eye": [-1.0, 8.0, 2.8]},
  {"name": "MyCam", "eye": [-6.0, 6.0, 2.7], "target": [-3.0, 14.5, 0.8], "focal_mm": 10.0}
]
```

A complete example is [examples/07_move_origin_and_camera.py](../examples/07_move_origin_and_camera.py).

### How the GUI maps to the configuration

The GUI settings edit this same JSON. The "Advanced settings" box shows it, and "Export settings" saves it to a file. Everything the GUI can change can be written in JSON.

| GUI field | JSON key |
|---|---|
| Duration, random seed | `duration_s`, `seed` |
| Literature profile | `people.profile` |
| Building population, time of day, share in the busiest 5 min | `demand.population`, `period`, `peak_pct_5min` |
| Streams: appears at | `streams[].origin` |
| Streams: arrivals, group size λ | `streams[].rate`, `group_size` |
| Streams: destination weights | `streams[].destinations[].p` |
| Elevator: arrival interval, capacity, people alighting | `elevator.schedule.interval`, `capacity`, `alight.count` |
| Gates | `gates.<name>.service_s` |
| Cameras: use, position, look-at point, focal length | `name`, `eye`, `target`, `focal_mm` in `cameras[]` |
| Placed objects | `render.props` |

Actions that are not settings correspond to functions.

| GUI action | Code |
|---|---|
| Choose a template | `twinsim.template(name)` |
| Run simulation | `twinsim.simulate(config)` |
| Render all | `twinsim.render(out_dir)` |
| Test render of the busiest 5 s | `twinsim.render(out_dir, frames=(a, b))`; see [examples/04_get_video.py](../examples/04_get_video.py) for finding the part |

JSON only (in the GUI, write these in the "Advanced settings" box): the space (`space`), `fps`, distributions such as walking speed (`people`), adding and removing streams and destinations, gates on the way (`via`), stop time (`dwell`), the next destination (`then`), meeting (`meet`), the elevator schedule type (`schedule`) and transfer times, outputs (`outputs`), A/B comparison (`variants`), render size and clothing colors (`render`), camera image size (`width`, `height`), the graph (`graph`), and more.

### Errors

Unknown keys are errors, so a misspelling never runs silently with the default value.

```python
>>> twinsim.validate({"space": "office", "duraton_s": 60})
ValueError: シナリオの誤り:
  知らないキー duraton_s（使えるのは ...）
```

A `ValueError` is also raised when a destination, gate or camera name is not in the space, when `duration_s` is not positive, or when `outputs` has an unknown name. JSON syntax errors report the line and column. Messages are in Japanese.

## Same input, same result

The same configuration and `seed` give the same result on every run. Keep `result.config` or `scenario_resolved.json` to repeat a run later.

```python
again = twinsim.simulate(result.out_dir / "scenario_resolved.json", out_dir="runs/again")
```

## Your own space

Put the folder path in `space`, or place the folder under the location in the `TWINSIM_SPACES` environment variable and use its name. The folder holds `space.yaml` or `space.json` and the walkable map. The format is in section 1 of [spec.en.md](spec.en.md); `twinsim export-space` builds one from USD.

## Replacing the elevator operation

`elevator_policy(sim, t)` is called every second. Adding a time to `car.arrivals` makes the elevator arrive then. Use this to try dispatch optimization.

```python
def policy(sim, t):
    if sim.queue and not any(x >= t for c in sim.cars for x in c.arrivals):   # call one when people wait and none is due
        sim.cars[0].arrivals.append(round(t + 10.0, 2))

result = twinsim.simulate("config.json", out_dir="runs/ev", elevator_policy=policy)
```

## Environment variables

| Name | Contents |
|---|---|
| `TWINSIM_DATA` | Default location of results (default `~/.twinsim`) |
| `TWINSIM_SPACES` | Location of your own spaces (searched before the bundled spaces) |
| `TWINSIM_ISAAC_WORK` | Exchange folder with Isaac Sim (default `~/isaac-sim-work/twinsim`) |
| `TWINSIM_TOKEN_FILE` | The GUI token file (default `~/.config/twinsim/token`) |
