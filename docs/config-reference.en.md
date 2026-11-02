# JSON configuration reference

[日本語](config-reference.md) ｜ [Tutorial](config-tutorial.en.md) ｜ **Reference** ｜ [Using Python](library.en.md) ｜ [Output formats](formats.en.md)

Every key you can write in a configuration. If this is your first time, start with the [tutorial](config-tutorial.en.md).
YAML works in the same form. Coordinates are world coordinates (m, Z up), and times are in seconds.

## Contents

| Group | Items |
|---|---|
| Overall | [All keys](#top-level), [how values are combined](#merge) |
| People | [`space`](#space), [`people`](#people), [`demand`](#demand) |
| Streams | [`streams[]`](#streams), [`origin`](#origin), [`rate`](#rate), [`destinations[]`](#destinations), [`meet`](#meet) |
| Facilities | [`elevator`](#elevator), [`schedule`](#schedule), [`alight`](#alight), [`gates`](#gates) |
| Cameras and outputs | [`cameras[]`](#cameras), [`render`](#render), [`outputs`](#outputs) |
| Comparing and checking | [`variants`](#variants), [`validity`](#validity) |
| Others | [`graph` and more](#others) |
| Common | [Distributions](#distributions), [place names](#places), [checks before simulating](#checks) |

<a id="top-level"></a>

## All keys

Only `space` is required. Any key not listed here is an error.

| Key | Type | Default | Contents |
|---|---|---|---|
| [`space`](#space) | string | required | Name of a space, or the path of a space folder |
| `seed` | integer | `0` | Random seed |
| `fps` | positive integer | `30` | Frames per second |
| `duration_s` | number | `120` | Length to simulate (seconds) |
| [`people`](#people) | object | see below | Distribution of people |
| [`demand`](#demand) | object | none | Amount of elevator users |
| [`streams`](#streams) | array | `[]` | Streams of people |
| [`elevator`](#elevator) | object | none | Elevators |
| [`gates`](#gates) | object | `{}` | Service time per gate |
| [`cameras`](#cameras) | array | `[]` | Cameras |
| [`render`](#render) | object | see below | Rendering |
| [`outputs`](#outputs) | array | all | What to write |
| [`variants`, `variant`](#variants) | object, string | none | Comparing conditions |
| [`validity`](#validity) | object | none | Extra checks |
| [`graph`, `mot_stride`, `congestion_levels`](#others) | | | Output details |
| [`name`, `title`, `title_en`, `description`, `calibration`](#others) | | | Names and records |

<a id="merge"></a>

## How values are combined

Values are stacked in this order, and later ones take priority.

1. Default values
2. The values of `people.profile`
3. The configuration file
4. `overrides` (Python) and `--set` (command line)

Objects are combined key by key. Arrays and distributions (objects with `type`) are replaced as a whole. All values used in a run are written to `scenario_resolved.json`.

<a id="space"></a>

## `space`

`twinsim spaces` (`twinsim.list_spaces()` in Python) lists the spaces. For your own space, give the folder path ([your own space](library.en.md)). Place names of the included spaces are in [place names](#places).

<a id="people"></a>

## `people`

| Key | Type | Default | Contents |
|---|---|---|---|
| `profile` | string | none | A group of literature values (table below) |
| `speed` | [distribution](#distributions) | normal 1.34 ± 0.26 m/s (0.8 to 1.9) | Free walking speed |
| `group_size` | [distribution](#distributions) | none (1 person) | Group size when a stream does not set one |
| `group_speed` | object | `{"model": "moussaid2010", "slope_m_s": 0.04}` | Group speed: slower than the average by this much per added person. `{"model": "min"}` matches the slowest member |
| `group_lateral_m` | number | `0.66` | Side-by-side spacing of a pair (m) |
| `lateral_max_m` | number | `1.0` | How far people can step aside from their path (m) |
| `speed_density` | object or `null` | `{"v0": 1.34, "gamma": 1.913, "rho_max": 5.4}` | Slowing with density (Weidmann 1993). `null` turns it off |
| `models` | `"all"` or array | `"all"` | Names of the person models to use (the 10 in `twinsim/characters.py`) |

Values of `profile`:

| Name | Contents |
|---|---|
| `office_commute_jp` | Morning commute to a Japanese office: 82% walk alone, spacing 0.72 m, gate median 2.0 s |
| `leisure_low_density` | Leisure crowd: 46% walk alone, spacing 0.66 m |

Values you write take priority over the group. The sources are in [validity.en.md](validity.en.md).

<a id="demand"></a>

## `demand`

Used by `lift_demand` in `rate` and `alight.count`. Elevator users = population × share ÷ 5 minutes (Peters et al. 2011).

| Key | Type | Default | Contents |
|---|---|---|---|
| `population` | number | required | People in the building |
| `period` | string | `"morning"` | `morning` (85% in, 10% out) or `lunch` (45%, 45%) |
| `peak_pct_5min` | number | `12` | Share in the busiest 5 minutes (%) |
| `level` | number | `1.0` | Multiplier for the whole amount |

<a id="streams"></a>

## `streams[]`

| Key | Type | Default | Contents |
|---|---|---|---|
| `name` | string | `origin` | Stream name, used in the counts. If `origin` is coordinates, `origin.name` is used, or else a name such as `stream1` |
| [`origin`](#origin) | string or object | required | Where people appear |
| [`rate`](#rate) | number or object | required | Arrival rate |
| `group_size` | [distribution](#distributions) | `people.group_size` | How many people appear together |
| `types` | string or `choice` distribution | `"person"` | Type of person, used by `types` in destinations |
| [`destinations`](#destinations) | array | required | Destinations |
| `start_s` | number | `0` | Time when people start to appear (seconds) |

<a id="origin"></a>

### `origin`

| Form | Where people appear |
|---|---|
| `"entrance"` | A [place name](#places) |
| `{"xy": [x, y]}` | That point |
| `{"line": [[x0, y0], [x1, y1]]}` | Somewhere on the line (an entrance with a width) |

The coordinate forms accept `name`, the label used in the counts.

```json
"streams": [
  {"name": "a", "origin": "entrance", "rate": 5, "destinations": ["south_exit"]},
  {"name": "b", "origin": {"xy": [-3.0, 20.0]}, "rate": 5, "destinations": ["south_exit"]},
  {"origin": {"line": [[-4.0, 20.0], [-2.0, 20.0]], "name": "north_door"}, "rate": 5, "destinations": ["south_exit"]}
]
```

Coordinates must be in the walkable area. For a line, both ends and points between them are checked. Any kind of place name is accepted.

<a id="rate"></a>

### `rate`

`per_min` is groups per minute. Adding `unit: "persons"` counts people per minute, divided by the mean group size (`constant`, `piecewise`).

| Form | Contents |
|---|---|
| `20` | Constant rate (groups per minute) |
| `{"type": "constant", "per_min": 20}` | The same |
| `{"type": "piecewise", "per_min": [[0, 5], [30, 30], [60, 5]]}` | `[seconds, rate]` joined by straight lines |
| `{"type": "lift_demand", "flow": "incoming", "share": 0.9}` | Computed from [`demand`](#demand). `flow` is `incoming`, `outgoing` or `interfloor`; `share` defaults to `1.0` |
| `{"type": "times", "times": [3, 10, 25]}` | One group at each given time (for checks) |

Except for `times`, arrival times come from a Poisson process with this rate. `lift_demand` accepts keys of `demand` to change them for this stream only.

<a id="destinations"></a>

## `destinations[]`

Elements of `streams[].destinations` and `elevator.alight.destinations`. A name alone, such as `"south_exit"`, also works.

| Key | Type | Default | Contents |
|---|---|---|---|
| `to` | string | required | Destination (table below) |
| `p` | number | `1.0` | Selection weight |
| `types` | array | none | Types of person who choose this destination. If none match, any destination can be chosen |
| `via` | array | `[]` | Names of gates to pass. The direction comes from the position |
| `dwell` | [distribution](#distributions) | `10.0` | Stop time (seconds) |
| `state` | string | depends on the place | State while stopped: `reception` at reception, `sign_check` at a sign, otherwise `dwell` |
| `glance` | number | stop `0`, elevator `20`, meeting `45` | How far to look around while stopped (degrees) |
| [`meet`](#meet) | object | none | Meeting up |
| `then` | string or object | none | Next destination after stopping (same form, without `meet`) |
| `variant_p` | string | none | Name that replaces `p` in [`variants`](#variants) |

Values of `to`:

| Value | Behavior |
|---|---|
| `"elevator"` | Wait for an elevator and board. Needs the [`elevator`](#elevator) settings |
| A place of kind `exit` or `spawn` | Walk there and leave |
| A place of kind `spot` or `prop` | Walk there and stop |
| The start of a place name (`"reception"`) | One of `reception_*` |

Destinations are place names only; they cannot be coordinates.

<a id="meet"></a>

### `meet`

The person who arrives first waits, and a companion comes later. The state while waiting is `companion_wait`.

| Key | Type | Default | Contents |
|---|---|---|---|
| `p` | number | `1.0` | Probability of meeting up |
| `delay` | [distribution](#distributions) | uniform 8 to 25 s | How late the companion arrives |
| `from` | same forms as [`origin`](#origin) | the stream's `origin` | Where the companion appears |
| `via` | array | `[]` | Gates the companion passes |

<a id="elevator"></a>

## `elevator`

| Key | Type | Default | Contents |
|---|---|---|---|
| `cars` | array | required | Names of the door places |
| `capacity` | integer | `8` | Capacity |
| [`schedule`](#schedule) | object | every 35 to 60 s per car | How elevators arrive |
| [`alight`](#alight) | object | none | People getting off |
| `transfer_s` | number | `1.0` | Time for one person to get on or off (seconds) |
| `door_open_s` | number | `1.0` | Time from arrival until the first person moves (seconds) |

<a id="schedule"></a>

### `schedule`

| `type` | Keys | Contents |
|---|---|---|
| `interval` (default) | `offset` ([distribution](#distributions), default uniform 3 to 30 s), `interval` (distribution, required) | Each car arrives at intervals from the distribution |
| `times` | `times` (`{"EV1": [seconds, ...]}`) | Arrives at the given times |
| `on_demand` | `travel_s` (distribution, default uniform 10 to 40 s), `max_wait_s` (default `60`), `dwell_s` (default `8`) | Calls a car when people are waiting and none is due within `max_wait_s` |

To replace the operation from code, use `twinsim.simulate(elevator_policy=...)` ([replacing elevator operation](library.en.md)).

<a id="alight"></a>

### `alight`

| Key | Type | Default | Contents |
|---|---|---|---|
| `count` | [distribution](#distributions) | Poisson λ = 1 | People getting off per arrival. `{"type": "lift_demand", "flow": "outgoing"}` computes it from [`demand`](#demand) (when `schedule` is `interval` or `times`) |
| `types` | string or `choice` distribution | `"person"` | Type of person |
| [`destinations`](#destinations) | array | required | Destinations |

```json
"elevator": {
  "cars": ["EV1"],
  "schedule": {"type": "times", "times": {"EV1": [10, 40]}},
  "alight": {"count": 2, "destinations": ["south_exit"]}
}
```

<a id="gates"></a>

## `gates`

The keys are gate place names.

| Key | Type | Default | Contents |
|---|---|---|---|
| `service_s` | [distribution](#distributions) | `1.5` (lognormal, median 2.0 s with `office_commute_jp`) | Time to pass one person in a lane (seconds) |

```json
"gates": {"gate": {"service_s": 2.5}}
```

<a id="cameras"></a>

## `cameras[]`

| Key | Type | Default | Contents |
|---|---|---|---|
| `name` | string | required | A candidate name from the space, or a new name |
| `eye` | `[x, y, z]` | candidate's value | Camera position. Required for a new name |
| `target` | `[x, y, z]` | candidate's value | Look-at point. Required for a new name |
| `focal_mm` | number | candidate's value, otherwise `12.0` | Focal length (mm) |
| `h_aperture_mm` | number | `20.955` | Sensor width (mm) |
| `width`, `height` | integer | values in `render` | Image size (pixels) |
| `clock_offset_s`, `drop_rate` | number | none | Clock offset and dropped frames. Only recorded; not applied to the video or labels |
| `note` | string | none | Note |

Values added to a candidate name override only those values.

```json
"cameras": [
  {"name": "CamGate"},
  {"name": "CamEV", "eye": [-8.0, 3.0, 3.0]},
  {"name": "MyCam", "eye": [-6.0, 6.0, 2.7], "target": [-3.0, 14.5, 0.8], "focal_mm": 10.0}
]
```

<a id="render"></a>

## `render`

| Key | Type | Default | Contents |
|---|---|---|---|
| `width`, `height` | integer | `1280`, `720` | Image size (pixels) |
| `tint` | `"per_person"` or `false` | `"per_person"` | Whether to vary clothing colors per person. The argument of `twinsim.render(tint=...)` takes priority |
| `props` | array | `[]` | Objects to place (names of `prop` places) |
| `gate_props` | boolean | `true` | Whether to place the gate machines |

<a id="outputs"></a>

## `outputs`

| Value | Files written |
|---|---|
| `graph` | `graph/` (graphs for GNNs) |
| `mot` | `mot/<camera>.txt`, `mot/ids.json` (detection and tracking labels). Needs `cameras` |
| `aicity` | `aicity/` (multi-camera tracking labels). Also needs `mot` |
| `preview` | `preview.png` (image of the trajectories) |
| `validity` | `validity.json`, `validity.md`, `validity.png` (comparison with the literature) |
| `ground_truth`, `frames`, `tasks` | Always written, whether listed or not |

`summary.json`, `ground_truth.json`, `frames.csv.gz`, `tasks.json` and `scenario_resolved.*` are always written. File formats are in [output formats](formats.en.md).

<a id="variants"></a>

## `variants`, `variant`

`variants` holds `{name: p}` for each condition. The values of the condition selected by `variant` become `p` of the destinations with the same `variant_p`.

```json
"variant": "B",
"variants": {"A": {"sign": 0.05}, "B": {"sign": 0.30}},
"streams": [
  {
    "name": "visitors",
    "origin": "entrance",
    "rate": 10,
    "destinations": [
      {"to": "sign", "p": 0.05, "variant_p": "sign", "dwell": 5, "then": "south_exit"},
      {"to": "south_exit", "p": 0.95}
    ]
  }
]
```

<a id="validity"></a>

## `validity`

Extra checks used by the verification templates.

| Key | Contents |
|---|---|
| `speed_density` | `"judge"` checks speed by density against the Weidmann formula (one-way corridors only) |
| `bottleneck` | Measures the flow through an opening such as `{"x": 30.0, "y": [-0.5, 0.5], "width_m": 1.0}` |

<a id="others"></a>

## Others

| Key | Type | Default | Contents |
|---|---|---|---|
| `name`, `title`, `title_en`, `description` | string | none | Name and description. `name` becomes the folder name when `out_dir` is omitted |
| `graph` | object | `{"cell_m": 2.0}` | Cell size of the grid graph (m) |
| `mot_stride` | integer | `1` | Write MOT boxes every N frames |
| `congestion_levels` | array | `[0.10, 0.20]` | Boundaries of the congestion levels (people/m²) |
| `calibration` | object | none | Record written by `twinsim calibrate` |

<a id="distributions"></a>

## Distributions

Where a time or a number of people is expected, you can write a distribution instead of a number.

| Form | Contents |
|---|---|
| `2.0` | Constant |
| `{"type": "constant", "value": 2.0}` | Constant |
| `{"type": "uniform", "min": 30, "max": 50}` | Uniform |
| `{"type": "normal", "mean": 1.34, "sd": 0.26, "min": 0.8, "max": 1.9}` | Normal |
| `{"type": "lognormal", "median": 20, "sigma": 0.5, "min": 3, "max": 120}` | Lognormal |
| `{"type": "poisson", "lam": 1.5}` | Poisson |
| `{"type": "zero_truncated_poisson", "lam": 0.6}` | Poisson without 0 (group size) |
| `{"type": "choice", "values": {"staff": 0.7, "visitor": 0.3}}` | Weighted choice. `["a", "b"]` gives equal weights |

Except in `uniform`, `min` and `max` clip the value. A literature name in `source` counts the value as literature in the table of sources.

<a id="places"></a>

## Place names

Names for `origin`, `to`, `via`, `cars` and `props`. To see them on a map, run `twinsim show-space <space>` (`annotate.png` in the space folder, or in the current folder if that is not writable). The `corridor` spaces have no top-down image, so it does not work for them.

| Space | Appear and leave | Gates | Elevators | Stops | Candidate cameras |
|---|---|---|---|---|---|
| `office` | `entrance`, `south_exit`, `west_corridor`, `east_room` | `gate` | `EV1`, `EV2` | `reception_w1`, `reception_w2`, `reception_e1`, `lounge_1` to `3`, `sign_view`, `sign` | `CamGate`, `CamEV`, `CamLobby` |
| `hospital` | `lobby_entrance`, `west`, `hall_side`, `west_room` | | `EV` | `reception_1`, `reception_2` | `CamGate`, `CamHall` |
| `warehouse` | `dock` | | | `pick_1` to `12`, `pack_1` to `4`, `staging_1`, `staging_2`, `break_1` | `CamAisles`, `CamPack` |
| `simple_room` | `door_w`, `door_e` | | | `table_1`, `table_2` | `CamRoom` |
| `corridor` | `west`, `start`, `east`, `finish`, `east_narrow` | | | | |
| `corridor_door` | `west`, `east` | | | | |

The office map is in the [tutorial](config-tutorial.en.md#origin).

<a id="checks"></a>

## Checks before simulating

`twinsim.validate`, `twinsim validate` and `twinsim.simulate` check the following before simulating. All errors are reported together in one `ValueError` (unknown spaces and templates raise `FileNotFoundError`).

| Check | Examples |
|---|---|
| Unknown keys | Top-level keys and keys in `cameras[]` |
| Value ranges | `duration_s` is positive, `fps` is a positive integer, `seed` is an integer, `mot_stride`, `graph.cell_m` is a multiple of the space's grid, values of `outputs` and `render.tint` |
| Names | `name` and camera names use only letters, digits, `_` and `-` (they become file names) |
| Place names | `origin`, `to`, `via`, `meet.via`, `cars`, keys of `gates` and `render.props` exist in the space; `via` is a gate; `cars` are elevators |
| Required items | `rate`, `destinations`, and `elevator` with `cars` when `to` is `"elevator"` |
| Spelling of kinds | `type` of `rate` and `schedule`; `variant` exists in `variants` |
| Coordinates | Form of `origin` and `meet.from`; inside the walkable area; destinations reachable, including from both ends of a line |
| Cameras | `name`; form of `eye` and `target`; no duplicate names; `eye` differs from `target` |
| Combinations | `aicity` needs `mot`; `meet` can only be written on a stream's top-level destination |

These are not checked.

- Mistakes inside a distribution. They become errors during the simulation.
- Unknown keys inside `people`, `elevator` and so on. They are ignored.

A group size of 0 is treated as 1 person.

---

[日本語](config-reference.md) ｜ [Tutorial](config-tutorial.en.md) ｜ **Reference**
