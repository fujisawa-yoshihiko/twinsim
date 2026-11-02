# Tutorial examples

[日本語](README.md)

Examples of using `twinsim` from code. Run them in order to go from a simulation to a video and on to a training dataset. Run them from the top folder of the repository.

```bash
uv run python examples/01_simulate.py      # simulate (the result goes to runs/tutorial/, which is not in git)
uv run python examples/03_read_labels.py   # read the ground-truth labels

./isaac_up.sh                              # only when making videos (GPU)
uv run python examples/04_get_video.py     # get the videos
isim down                                  # give the GPU back when done

uv run python examples/05_frames_with_boxes.py
uv run python examples/06_detection_dataset.py
```

| Example | What it does | GPU | Rough time |
|---|---|---|---|
| [minimal.json](minimal.json) | The smallest configuration (office, 60 s, 2 cameras) | | |
| [01_simulate.py](01_simulate.py) | Simulate from a JSON configuration and read the result | None | A few seconds |
| [02_change_settings.py](02_change_settings.py) | Make a configuration from a template, repeat runs with `overrides`, check for mistakes before simulating | None | About 10 s |
| [03_read_labels.py](03_read_labels.py) | Read the detection and tracking labels, each person's position and state, and the per-area counts | None | A few seconds |
| [04_get_video.py](04_get_video.py) | Render with Isaac Sim and get mp4 files. You can render only the busiest part, choose cameras, or keep the original clothing colors | 1 | 1 to 2 min for 2 s on 2 cameras |
| [05_frames_with_boxes.py](05_frames_with_boxes.py) | Take frames from a video and draw the ground-truth boxes on them | None | A few seconds |
| [06_detection_dataset.py](06_detection_dataset.py) | Make an object detection training set (YOLO format) from the videos and labels | None | A few seconds |
| [07_move_origin_and_camera.py](07_move_origin_and_camera.py) | Change where people appear with coordinates, and move or add cameras | None | A few seconds |

## Frame numbers

Keep the three numbers apart.

| Number | Starts at | Relation |
|---|---|---|
| Simulator frame | 0 | Seconds = frame ÷ fps (30 by default) |
| `frame` in the labels (`result.mot`) | 1 | Simulator frame + 1 |
| Position in the video | 0 | Simulator frame − `result.video_first_frame` |

`result.video_frames(camera)` returns simulator frames, so match them to the labels with `frame + 1` (see 05 and 06).

## When rendering videos

- The GPUs are shared. Check what is free with `nvidia-smi` before use, and stop Isaac Sim with `isim down` when done.
- Rendering the full length takes about 8.5 times the video length per camera (`--all`). Try a short part first.
- By default, 04 gives each person different clothing colors so that people are easy to tell apart. Use `--plain` for videos used in evaluation.
- The videos are at `runs/tutorial/video/<camera>.mp4`. Videos do not go into git.

The functions are listed in [docs/library.en.md](../docs/library.en.md), and the file formats in [docs/formats.en.md](../docs/formats.en.md). For JSON configurations, see the [tutorial](../docs/config-tutorial.en.md) and the [reference](../docs/config-reference.en.md).
