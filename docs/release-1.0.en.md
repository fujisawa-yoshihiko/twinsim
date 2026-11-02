# twinsim 1.0

[日本語](release-1.0.md)

The first release of this people-flow simulator for buildings. Configurations are JSON, and it can be called from Python.

## What 1.0 includes

- JSON configurations, a Python library, commands and a GUI
- Ground-truth data (trajectories, states, camera boxes, aggregates, graphs) and rendering with Isaac Sim
- [Tutorial](config-tutorial.en.md), [reference](config-reference.en.md) and [code examples](../examples/README.en.md)
- Coordinates for where people appear, and editing origins and cameras in the GUI

## Important fixes from earlier versions

| Fix | Effect |
|---|---|
| Videos had one extra frame | From about the third frame on, videos were one frame behind the labels. Videos rendered from now on match the labels on every frame. **Videos rendered with 0.x stay as they are** and are one frame behind |
| Default `min` and `max` were mixed into written distributions | Distributions such as walking speed were silently clipped |
| Boxes were off in spaces whose floor is not at height 0 | `simple_room` and your own spaces |
| Configuration names could write outside the result folder and run code inside Isaac Sim | `name` and camera names now use only letters, digits, `_` and `-` |
| Scripts could be injected into the GUI | All output is escaped, and a CSP was added |
| Simulating again in the same place left old camera labels | The previous result is now replaced |

## Known limitations

- Near a crowded gate, a trajectory can jump by up to about 1 m in one frame (about 0.3% of steps in `verify_gate_capacity`). This comes from an approximation in the walking engine, and fixing it means redoing all the comparisons with the literature, so it stays in 1.0.
- `clock_offset_s` and `drop_rate` of cameras are only recorded; they are not applied to the video or labels.
- Person boxes are approximations from a projected box, and values outside the image are written as they are.
- Times in `gate_events` are when the head of the queue starts to move (0.4 to 0.7 s before passing).
- `boarded` also includes people who could not finish boarding before the end of the simulation.
- Destinations are place names only; they cannot be coordinates.

## What was checked

- Automated tests, running every JSON in the tutorial, running all templates
- Installing the wheel in clean environments (Python 3.10 and 3.13)
- Same configuration and seed give the same result (across processes and Python versions)
- Operating the GUI in a browser (with the CSP enabled)
- Scanning the files and full history for secrets, and dependencies for known vulnerabilities
