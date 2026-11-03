# Start and stop procedures

[日本語](operations.md)

How to run twinsim and Isaac Sim on ampb (the shared GPU server) and view them in a browser on your local PC. Version of 2026-10-23.

## 0. Rules

- The GPUs (RTX PRO 6000 ×4) are shared with other users. Check what is free before use (`./status.sh` or `nvidia-smi`). When detection and other components run on the same machine, they share one GPU by default (`one-gpu` chooses it; GPU 3 by default). Split them only when needed, and use at most 2 GPUs.
- Decide the expected time and the GPU before starting long jobs such as rendering. Stop things when you are done.
- Do not put results or videos in git (they go under `~/dt-data/twinsim/`). Keep anything made from the video or drawings of a real building in a separate place.

## 1. Viewing from your local PC

```bash
# On your local PC (keep it running. 8770 = twinsim GUI)
ssh -N -L 8770:localhost:8770 ampb
```

```bash
# On ampb: print the URL to open (it contains a token; do not share it)
cd ~/twinsim-lib && ./run.sh serve --url
```

Open the printed `http://localhost:8770/?token=…` (afterwards `http://localhost:8770` alone is enough). Switch between 日本語 and English at the top right.

## 2. Checking what is running

```bash
cd ~/twinsim-lib && ./status.sh     # GUI server, Isaac Sim (GPU), free GPUs
```

## 3. Starting and stopping

| Component | Start | Stop | GPU |
|---|---|---|---|
| twinsim GUI server | `./run.sh serve` (to keep it running after closing the terminal: `setsid nohup ./run.sh serve > ~/dt-data/twinsim/serve.log 2>&1 &`) | `Ctrl+C` in the terminal that started it, or `./stop.sh gui` | none |
| Isaac Sim (rendering) | `./isaac_up.sh` (`./isaac_up.sh 2` to choose another GPU) | `./stop.sh isaac` (= `isim down`) | 1 (the same GPU as detection and the rest) |
| Render-only Isaac Sim (rendering in parallel) | `tools/render_farm.sh up --gpu N --workers K --wait` | `tools/render_farm.sh down` | Several on one GPU; at most 2 GPUs of your own in total ([README](../README.en.md#parallel)) |
| Everything at once | - | `./stop.sh` (GUI), `./stop.sh all` (Isaac Sim too) | - |

Run the commands in the repository folder.

## 4. Common tasks

| What you want | Steps | Time (5 min, 2 cameras) |
|---|---|---|
| View results | Choose a result in the GUI's "Results" tab | - |
| Compute people's movement | Change values in "Settings" and press "Run simulation (CPU)", or `./run.sh run office_gate_ev` | 15 s (CPU) |
| Render | Start Isaac Sim → "Test render of the busiest 5 s" or "Render all" in the GUI, or `./run.sh render <run>` | test render 2–3 min, everything 42 min per camera (GPU) |

`<run>` is `~/dt-data/twinsim/runs/<run-name>` (e.g. `~/dt-data/twinsim/runs/office_gate_ev`).

## 5. Troubleshooting

| Symptom | What to do |
|---|---|
| The GUI does not open | Check that `ssh -N -L …` on your local PC is still connected, and that the GUI server is running (`./status.sh`) |
| "Token required" | Reopen the URL from `./run.sh serve --url` on ampb |
| "Address already in use" from `./run.sh serve` | It is already running (`./status.sh`). To restart: `./stop.sh gui`, then start again |
| "Isaac Sim is not running" | Start it with `./isaac_up.sh`, wait about 1 minute and check with `./status.sh` |
| New GUI sections do not appear | The GUI server runs old code. `./stop.sh gui` → `./run.sh serve` → reload the browser |
| BrokenPipeError in the server log | The browser just closed a video midway. Harmless |

More: [README.en.md](../README.en.md) (structure, output formats, time to produce video), [library.en.md](library.en.md) (using it from Python).
