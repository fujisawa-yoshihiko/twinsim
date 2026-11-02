# Architecture (for developers)

[日本語](architecture.md)

## Data flow

```
JSON, dict or template ──→ scenario.load_scenario (defaults → literature profile literature.PROFILES → scenario → overrides)
twinsim/spaces/<name>/ ──→ space.load_space (grid of the walkable area, semantic map, A* routing)
                         │
                         ▼
                 scenario.Builder ──→ engine.Sim (frame by frame: walk, avoid, queue, EV, groups)  ← CPU
                         │
                         ▼
                 outputs.write_all (ground truth, aggregates, graphs, boxes, AI City, check figures) → validity.evaluate (comparison with the literature)
                         │                                                   <TWINSIM_DATA>/runs/<name>/
                         ├─→ isaac_bridge.render (request to Isaac Sim → mp4)                      ← GPU
                         └─→ calibrate (gate and EV logs → scenario with sources)
```

## Modules

| Location | Role | Main entry points |
|---|---|---|
| `twinsim/config.py` | Locations and connection targets (changed with environment variables) | `RUNS`, `USER_SPACES`, `ISAAC_WORK` |
| `twinsim/space.py` | Space (grid, zones, places, routes) | `load_space`, `Space.route` |
| `twinsim/dists.py` | How distributions are written, and sampling, means, arrival times | `sample`, `mean`, `arrival_times` |
| `twinsim/literature.py` | Literature values, sources, literature profiles | `REFS`, `PROFILES`, `weidmann_speed` |
| `twinsim/scenario.py` | Reads a scenario and assembles the spawning of people, destinations, EVs and gates | `load_scenario`, `build`, `resolve_rate` |
| `twinsim/engine.py` | People's movement (itineraries, speed and density, following, overtaking, groups, queues, EVs) | `Sim.run` |
| `twinsim/outputs.py` | Ground truth, aggregates, graphs, MOT, AI City, check figures | `write_all` |
| `twinsim/validity.py`, `quality.py` | Comparison with the literature, ledger / wall and proximity checks | `evaluate`, `check` |
| `twinsim/calibrate.py` | Calibration with real data, writing out in the log format | `calibrate`, `export_logs` |
| `twinsim/camera.py` | Cameras (USD matrices), bounding boxes, visible fraction, projection onto the floor | `Camera` |
| `twinsim/isaac_bridge.py`, `twinsim/isaac/` | Rendering in Isaac Sim, space assets (what runs inside Isaac Sim is `twinsim/isaac/`) | `render`, `finish_render`, `export_space` |
| `twinsim/api.py`, `__init__.py`, `__main__.py` | Python entry point ([library.en.md](library.en.md)), commands (`twinsim <subcommand>`) | `simulate`, `Result`, `run` |
| `twinsim/server.py`, `twinsim/static/` | GUI and REST API (`app.js`: Settings and Results, `i18n.js`: switching between 日本語 and English. On-screen text uses `tr("日本語", "English")` and `data-en` in the HTML. English for templates, spaces and literature profiles is in `title_en`, `license_en`, `note_en` and `notes_en`) | `serve` |

## Development procedure

```bash
cd ~/twinsim-lib
uv run --group dev ruff check          # style (configured in pyproject.toml)
uv run --group dev pytest -q           # operation checks (CPU, about a minute). tests/test_imports.py catches anything missed when splitting or renaming
uv run --group gui-test python tools/gui_shot.py [output] [port]   # screen check (start the server first)
```

- Dependencies are in `pyproject.toml` (pinned with `uv.lock`). `./run.sh` is `uv run twinsim`.
- When pushed to GitHub (private `fujisawa-yoshihiko/twinsim`), `.github/workflows/ci.yml` runs ruff and pytest (no GPU is used).
- The rules (GPU usage, keeping data out of git, NDA) are in `CLAUDE.md`.
