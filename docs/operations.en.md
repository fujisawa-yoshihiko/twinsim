# Start and stop procedures

[日本語](operations.md)

How to run twinsim, MOPF and Isaac Sim on ampb (the shared GPU server) and view them in a browser on your local PC. Version of 2026-10-23.

## 0. Rules

- The GPUs (RTX PRO 6000 ×4) are shared with other users. Check what is free before use (`./status.sh` or `nvidia-smi`), and use at most 2 at the same time.
- Decide the expected time and the GPU before starting long jobs such as rendering. Stop things when you are done.
- Do not put results or videos in git (they go under `~/dt-data/twinsim/`). Keep anything made from Takeshiba's real video or drawings in a separate place.

## 1. Viewing from your local PC

```bash
# On your local PC (keep it running. 8770 = twinsim GUI, 5174 = MOPF GUI)
ssh -N -L 8770:localhost:8770 -L 5174:localhost:5174 ampb
```

```bash
# On ampb: print the URL to open (it contains a token; do not share it)
cd ~/twinsim && ./run.sh serve --url
```

Open the printed `http://localhost:8770/?token=…` (afterwards `http://localhost:8770` alone is enough). Switch between 日本語 and English at the top right.

## 2. Checking what is running

```bash
cd ~/twinsim && ./status.sh     # GUI server, MOPF (GPU, live or not), Isaac Sim (GPU), free GPUs
```

## 3. Starting and stopping

| Component | Start | Stop | GPU |
|---|---|---|---|
| twinsim GUI server | `./run.sh serve` (to keep it running after closing the terminal: `setsid nohup ./run.sh serve > ~/dt-data/twinsim/serve.log 2>&1 &`) | `Ctrl+C` in the terminal that started it, or `./stop.sh gui` | none |
| MOPF | In the GUI's "MOPF" tab, choose a GPU and press "Start for video processing" or "Start live with the selected video". From the command line: `cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu 3 --no-llm --no-vc3` | "Stop" in the "MOPF" tab, or `./stop.sh mopf` | 1 |
| Isaac Sim (rendering) | `./isaac_up.sh <GPU>` (e.g. `./isaac_up.sh 2`) | `./stop.sh isaac` (= `isim down`) | 1 |
| Everything at once | - | `./stop.sh` (GUI and MOPF), `./stop.sh all` (Isaac Sim too) | - |

Run the commands in `~/twinsim` (only the MOPF start command runs in `~/MOPF_ALL_video`).

## 4. Common tasks

| What you want | Steps | Time (5 min, 2 cameras) |
|---|---|---|
| View results | Choose a result in the GUI's "Results" tab | - |
| Compute people's movement | Change values in "Settings" and press "Run simulation (CPU)", or `./run.sh run office_gate_ev` | 15 s (CPU) |
| Render | Start Isaac Sim → "Test render of the busiest 5 s" or "Render all" in the GUI, or `./run.sh render <run>` | test render 2–3 min, everything 42 min per camera (GPU) |
| Detect, track with MOPF and compare | Start MOPF "for video processing" → "Detect and track the videos with MOPF (GPU)" in the GUI, or `./run.sh mopf-process <run>` → `./run.sh mopf-eval <run>` | 3 min per camera (GPU) + a few seconds |
| Infer cross-camera association | "Infer and score" in the GUI, or `./run.sh mopf-link <run>` | about 30 s (CPU) + 3–4 min for the prediction video |
| Overnight: render through comparison | `setsid nohup tools/night_b.sh <run> > /dev/null 2>&1 &` (if it stops after rendering, add `--resume`) | about 1.5 h |

`<run>` is `~/dt-data/twinsim/runs/<run-name>` (e.g. `~/dt-data/twinsim/runs/office_gate_ev`).

## 5. Troubleshooting

| Symptom | What to do |
|---|---|
| The GUI does not open | Check that `ssh -N -L …` on your local PC is still connected, and that the GUI server is running (`./status.sh`) |
| "Token required" | Reopen the URL from `./run.sh serve --url` on ampb |
| "Address already in use" from `./run.sh serve` | It is already running (`./status.sh`). To restart: `./stop.sh gui`, then start again |
| "Isaac Sim is not accepting jobs" | Start it with `./isaac_up.sh <free GPU>` and check with `./status.sh` |
| MOPF does not start (GPU in use) | Another user's job. Pick a free GPU with `./status.sh` |
| New GUI sections do not appear | The GUI server runs old code. `./stop.sh gui` → `./run.sh serve` → reload the browser |
| BrokenPipeError in the server log | The browser just closed a video or the live stream midway. Harmless |

More: [README.en.md](../README.en.md) (structure, output formats, time to produce video), [integration.en.md](integration.en.md) (integration with MOPF).
