# Integration with other applications (MOPF, intermediate graph layer, research code, real data)

[日本語](integration.md)

2026-10-22. How to connect twinsim results with MOPF (`~/MOPF_ALL_video`), graph tasks such as GNNs, research code, and real data.

## 1. Overall flow

```
Scenario (people distributions: literature, real data) ─→ twinsim (CPU) ─→ ground truth (ground_truth, mot, aicity), intermediate graph layer (graph/), log format (logs/)
                                                             │
                                                             └→ rendering with Isaac Sim (GPU) ─→ video/<camera>.mp4
                                                                                                        │
                       MOPF (GPU): detection and tracking ←─────────────────────────────────────────────┘ (mopf-process, or stream live)
                           │
                           ├→ twinsim mopf-eval: compare with ground truth (MOTA, IDF1, counts, foot-point error)
                           └→ intermediate graph layer (mopf_graph/, same format as graph/) ─→ GNN / optimization (MOPF_OPT) ─→ elevator operation etc. (elevator_policy) ─→ twinsim
Real data (gate passage logs, elevator operation logs) ─→ twinsim calibrate ─→ scenario with sources
```

This corresponds to the Notion requirements "integration via API (MOPF, GNN)", "stream the simulator's video into MOPF (a rehearsal for production)" and "graph-based intermediate layer".

## 2. Processing videos with MOPF and comparing (offline)

```bash
cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --no-llm --no-vc3     # start MOPF (GPU; only after getting confirmation; without camera input)
cd ~/twinsim
./run.sh mopf-process ~/dt-data/twinsim/runs/office_gate_ev        # send video/*.mp4 to MOPF and receive the tracks into mopf_tracks/
./run.sh mopf-eval ~/dt-data/twinsim/runs/office_gate_ev           # compare with ground truth (mopf_eval/), intermediate graph layer (mopf_graph/)
```

- The videos are copied to MOPF's `uploads/twinsim-<run-name>-<camera>.mp4` and processed with `POST /api/video/process/<name>?model_name=yolo11m`.
  The result is `outputs/uploads/<name>/tracking.jsonl` (MOPF's format).
- How they are compared: the ground-truth boxes are `mot/<camera>.txt` (approximate boxes obtained by projecting a box enclosing each person, plus the visible fraction). Matching uses IoU ≥ 0.3,
  and ground-truth people with a visible fraction below 0.4 are counted neither as misses nor as false positives. Frame 0 of the video is `frames[0]` in `render_log.json`.
- Outputs: MOTA, IDF1, ID switches, recall, precision, the error in the number of people on screen, and the offset between the foot point (bottom center of the box) projected onto the floor and the ground truth.
  The foot point corresponds to the near edge of the body, so it is off by about 0.3 m even with perfect tracking.
- Check: with tracks in MOPF's format built from the ground truth (`mopf_link.synthetic_tracks`), MOTA and IDF1 are 1 when there are no errors, and recall is 0.8 with 20% misses (`tests/test_validity.py`).
- The results tab of the GUI also has "Detect and track the videos with MOPF (GPU)" and "Compare MOPF's tracks with the ground truth" (a confirmation dialog appears before the GPU is used).

### Results of actual MOPF processing (2026-10-22, A: test render, 5 s × 2 cameras, yolo11m + BoostTrack, GPU 3)

Results: `~/dt-data/twinsim/runs/office_gate_ev-20261022-172550/` (mopf_tracks, mopf_eval, mopf_graph). Processing took 18 s for the 2 videos.

| Camera | MOTA | IDF1 | ID switches | Recall | Precision | Error in on-screen count | Foot-point offset (median) |
|---|---|---|---|---|---|---|---|
| CamGate (gate) | 0.950 | 0.975 | 0 | 0.952 | 0.998 | 0.17 people | 0.19 m |
| CamEV (elevator hall) | 0.906 | 0.922 | 5 | 0.976 | 0.936 | 0.54 people | 0.18 m |

- Intermediate graph layer (mean number of people per zone): elevator hall MOPF 10.3 people / ground truth 14.2 people; in front of the gate 1.3 / 2.7 people. Counts come out low in crowded and distant areas.
- This test render came from a run of the previous version, which had no `mot/ids.json`, so it was rebuilt from the box positions (`ensure_ids`).
### 5 minutes × 2 cameras (2026-10-23, B: office_gate_ev, 94 people, morning peak with a building population of 600, rendering 89 min, MOPF processing about 3 min per video)

Results: `~/dt-data/twinsim/runs/office_gate_ev/` (video, mopf_tracks, mopf_eval, mopf_graph; the log is night_b.log).

| Camera | MOTA | IDF1 | ID switches | Recall | Precision | People (ground truth / MOPF IDs) | Error in on-screen count | Foot-point offset (median, 90%) |
|---|---|---|---|---|---|---|---|---|
| CamGate (gate) | 0.868 | 0.859 | 29 | 0.893 | 0.975 | 87 / 114 | 0.23 people | 0.22, 0.40 m |
| CamEV (elevator hall) | 0.898 | 0.878 | 29 | 0.964 | 0.936 | 83 / 112 | 0.16 people | 0.16, 0.38 m |

- More ID switches than in the 5 s test render (A) (29 each in 5 minutes; the number of IDs is about 1.3 times the ground-truth number of people). Longer videos contain more scenes where people overlap.
- Counting the gate line from MOPF's tracks (with the same rules as the flow monitor) gives entry 48, exit 3. From the ground truth (using the foot points of visible people) it would be entry 67, exit 3,
  and the gate passage log shows entry 73, exit 7. About 30% of entries were missed.
  The cause is not the tracking but the position of the line: people entering appear from behind the door at the back and walk toward the camera, but the line is right in front of the door, so when they appear their foot point is already on
  or past the line (there is no record of them on the approach side of the line). Shifting the line in the entry direction (`mopf.LINE_OFFSET_M`; the default is now 1 m):

  | Shift distance | Ground truth (entry, exit) | MOPF (entry, exit) |
  |---|---|---|
  | 0 m | 67, 3 | 48, 3 |
  | 0.5 m | 71, 3 | 61, 8 |
  | 1.0 m | 70, 4 | 65, 10 |
  | 1.5 m | 70, 4 | 66, 8 |
  | 3.0 m | 68, 13 | 67, 12 (also crosses other flows in the lobby) |

  At 1 m, MOPF counts 67 of the 74 ground-truth crossings (91%), with 7 missed counts and 8 extra counts (mostly in the exit direction; ID switches make people look as if they go back and forth).
- For visual checks: `mopf_eval/<camera>_overlay.mp4` (ground-truth and MOPF boxes overlaid, with marks at the times of missed counts and ID switches),
  `mopf_eval/CamGate_missed.png` (an overview of the missed-count scenes), `mopf_eval/CamGate_crossings.json` (times and people). Generated with `./run.sh mopf-overlay <run>`.
- Intermediate graph layer (mean number of people per zone): elevator hall MOPF 3.5 people / ground truth 4.0 people (error 0.61); in front of the gate 1.1 / 1.7 people (error 0.69).
- If it stops partway (after rendering), `tools/night_b.sh --resume` can continue from the step that encodes the mp4 (`isaac_bridge.finish_render`).

## 3. MOPF's flow monitor (live)

```bash
./run.sh mopf ~/dt-data/twinsim/runs/office_gate_ev --camera CamGate            # settings (floor plan, alignment, lines, areas) and the values the ground truth says should be counted
cd ~/MOPF_ALL_video && ./start_ampb.sh --gpu N --live-demo ~/dt-data/twinsim/runs/office_gate_ev/video/CamGate.mp4   # stream the video live over RTSP
cd ~/twinsim && ./run.sh mopf ~/dt-data/twinsim/runs/office_gate_ev --camera CamGate --apply   # send the settings to MOPF
```

- Because the simulator knows the camera matrices and the floor coordinates, the settings are built from floor grid points instead of matching 4 points by hand (`mopf.py`).
- The values that should be counted according to the ground truth (`mopf/<camera>/expected.json`) are counted from the foot points of people with a visible fraction of 0.4 or more, using the same rules as MOPF's flow monitor (foot point, 8 pixels from the line, line-segment intersection).
  The live stream loops the video, so the comparison is per loop.
  Example (office_gate_ev, CamGate, 5 minutes): gate line entry 67, exit 3; 87 people entered the area in front of the gate.
- Check (2026-10-22, looping the 5 s CamGate test render from A for 60 s): the settings reached MOPF via `--apply`. The gate line counted entry 0, exit 0,
  matching the ground truth (0, 0 per loop). Entries into the area in front of the gate were about 3 per loop (ground truth: 5 people). In live mode the video is downscaled to 640×360,
  and detection of distant people drops (video processing runs at 1280×720 with recall 0.95).

## 4. Intermediate graph layer (same format whether from the simulator or from MOPF)

| File | Contents |
|---|---|
| `graph/graph.json` | Zone graph (nodes: zones, edges: adjacent zones), 2 m grid graph, nodes visible from the cameras (`observed`) |
| `graph/zone_counts.csv`, `mopf_graph/<camera>/zone_counts.csv` | Number of people per zone, per second (columns: t, zones…) |
| `graph/zone_flows.csv`, `mopf_graph/<camera>/zone_flows.csv` | Movements between zones per minute (minute, source, target, count) |
| `graph/grid_counts.npz` | Number of people per grid node (counts[second, grid]) |

- `graph/` is built from the simulator's ground truth (everyone), and `mopf_graph/` from MOPF's tracks (foot points projected onto the floor). Because the format is the same, a GNN or an optimizer
  can read either one in the same way (a two-layer split: video → graph → learning / optimization).
- Comparing the two, even with perfect tracking the elevator-hall count comes out 1 person lower on average (3.0 people vs. 4.0 in the ground truth), because of almost fully occluded people and foot-point offsets.
  Building the graph from real cameras requires correcting for what cannot be seen (occlusion correction QAQS, people-count estimation).

## 5. Research code (~/MOPF_ALL_video/research)

`research/sim-cctv/cctv_eval_lib.py` reads twinsim results with `SIM_DATASET=twinsim TWINSIM_RUN=<run-dir>` (the ground-truth format is the same).
MOPF results are `twinsim-<run-name>-<camera>/tracking.jsonl` under `TRACKS_DIR`. However, the research evaluation does not know whether people are occluded
(it counts anyone inside the frame as someone who should be visible), so recall comes out lower even for the same tracks. Use `mopf-eval` for twinsim results.

## 6. Ground-truth formats (for other tools)

- `mot/<camera>.txt`: MOTChallenge (frame, id, x, y, w, h, 1, 1, visible fraction)
- `aicity/gt.txt`: multi-camera tracking (AI City Challenge MTMC: camera_id obj_id frame_id xmin ymin width height xworld yworld). Person IDs are the same across cameras
- `tasks.json`: ground-truth aggregates for the 6 tasks on p. 7 of the project plan; `frames.csv.gz`: one row per person per frame

## 7. Calibrating with real data (log formats and the data to request)

```bash
./run.sh export-logs ~/dt-data/twinsim/runs/office_gate_ev     # convert simulator results into the log format (a sample of the format)
./run.sh calibrate office_gate_ev --gate-log gate_log.csv --ev-log ev_log.csv   # scenario calibrated with the logs (~/dt-data/twinsim/calibration/<id>/)
```

| Log | Columns | One row per | What is calibrated |
|---|---|---|---|
| Gate passage log `gate_log.csv` | time_s, gate, lane, direction (in/out), person (optional) | each person passing | Number of people per minute in the incoming flow, gate time per person (log-normal fitted to intervals of 4 s or less) |
| Elevator operation log `ev_log.csv` | time_s, car, boarded, alighted (if known) | each elevator arrival at the lobby floor | Arrival interval per car (log-normal, or replay the times as-is with `--ev-mode replay`), mean number of people alighting |

- Calibrated values get `source: data:<id>`, and the scenario's `calibration` field keeps the log files, their hashes and the date/time. In the validity ledger they count as "real data".
- Round-trip check (calibrating with the simulator's own logs): arrivals 10.9 people/min (original 11.0), gate time median 2.03 s (original 2.0), elevator interval median 44 s (original 35–60 s).
- Anything made from Takeshiba's logs (potentially covered by the NDA) is not put in git or in any shared location (the default location is under `~/dt-data`).
- Proposed format for the request to Tokyu Land: the two above (times in seconds or milliseconds; date and time is also fine). Also confirm whether the elevators use destination dispatch (destination-floor booking).

## 8. From the GUI

- "Results" tab: videos, overlay videos and figures each have a "⬇ Download" button, and everything can be downloaded together as a zip (without videos / with videos). Videos can be played from the middle (Range).
  The MOPF integration section has the evaluation table, the counting-line counts, the floor map (`mopf_eval/<camera>_floor.png`, ground truth on the left, MOPF on the right) and a button that creates the overlay video.
- "MOPF" tab: pick a GPU from the status and GPU table (memory, utilization, GPUs used by twinsim and MOPF), then "Start for video processing", "Start live with the selected video",
  "Stop" (each shows a confirmation dialog; at most 2 GPUs at a time). It shows the live video (relaying the video of MOPF's flow monitor) side by side with the values MOPF counted and the values the ground truth says should be counted
  (for the number of loops of the video). "Send the settings of the selected run" re-sends the lines, areas and floor plan. MOPF's own UI is opened by forwarding port 5174.
- Check (2026-10-23): ran the whole sequence from the GUI: start live on GPU 3 → send the settings → video relay (1.1 MB in 3 s) and counts → stop.

## 9. Tracking across multiple cameras

- MOPF tracks per camera (one camera per cv-app; IDs are per camera). It has no function to link the same person across cameras.
- The ground truth uses the same ID across cameras (`aicity/gt.txt`, `mot/ids.json`), so linking methods can be evaluated.
- The research code (`~/MOPF_ALL_video/research/multicam/`) has a prototype that links two cameras with non-overlapping fields of view by time (expected arrival time) and appearance
  (virtual hospital: 6/6 with 4 people, 15/17 between the 2 cameras with 32 people). In twinsim, that idea became the inference below (mopf-link).
- Viewing aligned by time (`./run.sh mopf-sync <run>`, "Show 2 cameras side by side in time" in the GUI): a side-by-side (synchronized) video of the cameras, `mopf_eval/sync.mp4`
  (the same person has the same color in both cameras, boxes are labeled "person / MOPF ID", and when someone appears in the other camera: "ID a at the gate → ID b at the elevator hall, moved in x s"), and
  a per-person ID correspondence table, `mopf_eval/identities.json` and `identities.csv` (IDs and time spans per camera, movement between cameras, how many people a single ID spanned).
  The table in the GUI can be filtered by person or ID, and clicking an ID jumps the video to that time.
  office_gate_ev (5 minutes): of the 92 ground-truth people, 78 appeared in both cameras; the gate → elevator hall movement took a median of 6.6 s.
  IDs that spanned 2 or more people (ID switches): 11 tracks at the gate, 10 at the elevator hall.
- Linking inference without ground truth (`./run.sh mopf-link <run> [--apps color osnet_x0_25_msmt17] [--method <method>]`, "Predicted cross-camera association" in the GUI, `twinsim/mopf/linking.py`):
  1. Project the foot points of tracklets (continuous runs of a MOPF ID) onto the floor. 2. Link gaps of up to 3 s within a camera using predicted position and clothing color.
  3. Link the end of a camera track → the start of a camera track in another camera (within 90 s) using time, walking direction and clothing color. 4. Follow the links to assign global IDs (M001…; separate from the ground-truth group IDs G001…).
  - Time: deviation from the "expected time", the shortest walking distance over the walkable area of the space divided by walking speed (20% of people are assumed to be delayed by detours).
  - Clothing color: hue–saturation histograms of the upper and lower halves. Dissimilarity is standardized by the distribution for two people seen at the same time in the same camera (always different people).
  - Each cue is turned into a log-likelihood ratio of "same person" vs "different person"; they are summed, a prior set from the number of candidates is subtracted, and only pairs above 0 are linked one-to-one (Hungarian method).
  - The ground truth is used only for scoring (the person of each tracklet, precision and recall of cross-camera links, IDF1 over both cameras).
  - Outputs: `mopf_eval/links.json` and `links.csv` (predicted links and scores), `links.png` (crops of the predicted links, most confident first, with ○/×),
    `sync_pred.mp4` (the 2 cameras side by side with predicted global IDs; ○ = matches the ground-truth person, × = a different person; predicted links shown below).

  office_gate_ev (5 min, MOPF yolo11m + BoostTrack, 2026-10-23). Values are "IDF1 over both cameras (cross-camera links correct/predicted)".
  There are 78 true cross-camera transitions and 92 true people. Baselines: no linking 0.589, within camera only 0.607, time + direction only 0.617 (5/23).

  | Appearance (per crop, 8 CPU threads) | Appearance only | Time (map) + appearance | Time (learned) + appearance | Time (learned) + appearance, hierarchical clustering |
  |---|---|---|---|---|
  | Clothing color (0.37 ms) | 0.771 (69/84) | 0.816 (70/80) | 0.824 (73/81) | **0.845 (71/73)** |
  | OSNet x0.25, MSMT17 (3.9 ms, the same weights as MOPF) | 0.715 (58/82) | 0.793 (67/78) | 0.802 (69/79) | 0.826 (66/71) |
  | OSNet x1.0, MSMT17 (41 ms) | 0.746 (59/79) | 0.797 (64/79) | 0.805 (66/78) | 0.827 (66/71) |
  | CLIP-ReID ViT-B/16, MSMT17 (21 ms) | 0.791 (57/64) | 0.806 (67/75) | 0.806 (68/77) | 0.816 (63/68) |

  - Speed: the 5-minute, 2-camera run has 1,824 crops (8 s to read the videos). Appearance features take 7 s with OSNet x0.25, 39 s with CLIP-ReID and 75 s with OSNet x1.0
    (on the CPU, OSNet x1.0's depthwise convolutions are slow, so it is slower than the ViT-B CLIP-ReID). Linking takes 2–5 s per method. The side-by-side video with predicted IDs takes 3–4 min.
  - Learned time (time*): from the confident links of a first pass (margin ≥ 2, appearance z ≤ −2), learn the deviation from the expected time. For gate → elevator hall it learned from 45–48 links
    that people arrive a median 1.3 s earlier than the map estimate, which found 0–3 more transitions. Elevator hall → gate has fewer than 10 confident links and is not learned.
  - Hierarchical clustering (hc:, the idea of the AI City 2024 winner): compute scores (LLR) between all pairs of camera tracks and merge them by average linkage under cannot-link constraints.
    IDF1 is 0.01–0.02 higher than one-to-one assignment (fewer wrong links), but slightly fewer transitions are found.
  - Among the re-identification models, CLIP-ReID is best with appearance alone (89% of predicted links correct). Combined with time, the four differ little (IDF1 0.80–0.83).
  - Choosing representative crops by full-body aspect ratio and size (instead of pose) differed from evenly spaced crops by only ±0.01, so it did not help (the default is evenly spaced).
  - In this scene each person's clothing color differs, so color is strong. In real video, re-identification models are expected to matter. The default in the GUI and the command is "time (learned) + OSNet x0.25".
  - Re-identification weights: `tools/fetch_reid_weights.sh` (OSNet x1.0 and CLIP-ReID into `~/dt-data/twinsim/models/reid/`, with sha256 checks).
  - Time alone cannot narrow down the partner because about 11 people pass per minute (almost no pairs meet the linking threshold). Clothing color is the main cue, and time narrows it down.
  - 5 of the 10 wrong links are one-by-one shifts in a crowded queue near the end (272–283 s). There are more global IDs than the 92 people because within-camera breaks remain.
  - Changing the prior (0.5), the detour share (0.2) and the direction concentration (2.0) keeps IDF1 at 0.77–0.83 and found transitions at 60–74 (some values were set after seeing
    this scene's results; the initially chosen values are kept rather than the best ones). The first half (up to 150 s) gets 28/28 links and the second half 42/52; the busier second half is harder.
  - In this scene each person's clothing color differs (a rendering setting). In real video, people dress similarly, so the color cue is expected to be weaker.

## 10. REST API (GUI server, `Authorization: Bearer <token>`)

`POST /api/runs {scenario, overrides}` runs a computation, `GET /api/runs/<id>/file?path=...` fetches a file,
`POST /api/runs/<id>/mopf {camera, apply}` (flow monitor settings and the values that should be counted),
`POST /api/runs/<id>/mopf/process {cameras, model, confirm}` (process with MOPF; without confirm it returns an estimate), `POST /api/runs/<id>/mopf/eval` (comparison, graph, floor map),
`POST /api/runs/<id>/mopf/overlay` (overlay video, in the background), `GET /api/runs/<id>/zip[?videos=1]`, `GET /api/mopf/status`, `POST /api/mopf/start {gpu, live, confirm}`,
`POST /api/mopf/stop {confirm}`, `GET /api/mopf/live/summary`, `/api/mopf/live/stream` (relay), `POST /api/mopf/live/reset`, `/api/mopf/live/apply {run, camera}`.
From Python, `twinsim.api.run(..., elevator_policy=f)` replaces the elevator operation (the hook for plugging in optimization).

## 11. How much video validation needs (estimate, 2026-10-23)

Amounts estimated from the counts in office_gate_ev's morning peak (5 min), for a 95% interval (per camera). Rendering takes about 8.5× the video length per camera (README, "Time needed to produce video").

| What to check | Count in 5 min | Count needed | Video length | Rendering (1 camera, 1 GPU) |
|---|---|---|---|---|
| Share of counting-line crossings counted (now 91%), ±5% | 74 | about 130 | about 10 min | about 1.5 h |
| Same, ±3% | same | about 370 | about 25 min | about 3.5 h |
| Linking across the 2 cameras (share of people linked correctly, assumed 80%), ±5% | 78 pairs | about 250 pairs | about 16 min | about 2.3 h |
| Frequency of ID switches, ±20% (Poisson) | 29 | about 100 | about 17 min | about 2.4 h |

- A single scene is biased, so vary the conditions: 3 crowd levels (change the building population) × 2 times of day (morning entry peak, lunch two-way) × 10 min each = 60 min of video (per camera).
  Rendering takes about 8.5 h per camera; rendering the 2 cameras at the same time on 2 GPUs takes about 8.5 h (one night). Today the 2 cameras are rendered one after the other, so about 17 h.
- The hospital renders about 3× slower (many lights).
- When validating with real Takeshiba video: for crossing counts, the gate logs are the ground truth as they are, so hours of video can be compared without labeling.
  ID tracking and linking across the 2 cameras need manual labels, so limit them to short stretches (2–5 min per camera, at busy times).

## 12. Not yet done

- Closing the full loop (MOPF output → optimization (Gurobi in MOPF_OPT) → elevator operation → simulator → results). The hook (`elevator_policy`) exists, but it is not connected to MOPF_OPT
- An entry point for issuing events from outside via the API (switching signage, guidance when crowded)
- Automating the switch of the video streamed live (currently `start_ampb.sh --live-demo` is run by hand; it recreates the cv-app)
