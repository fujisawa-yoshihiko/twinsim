# Plans for the next versions

[日本語](roadmap.md)

Draft goals for the next versions and the decisions still to make. Once decided, items move to the release notes of that version (`release-X.Y.en.md`). The current version is [1.1](release-1.1.en.md).

## 1.2 (draft goals, to be decided)

### 1. Groups (from dyads to a general group feature)

What exists now:

- Group size distribution (`group_size`, zero-truncated Poisson), group speed (`group_speed`, Moussaïd et al. 2010), lateral spacing of dyads (`group_lateral_m`)
- Cohesion along the walking direction (a member ahead waits, one behind catches up), meeting (`meet`; `companion_wait` while waiting), members do not appear at the same point
- `group` in the ground truth (who belongs to which group). Checks: share of people by group size, slope of speed against group size, dyad distance

What the 1.1 checks showed to be missing ([validity.en.md, section 5.6](validity.en.md#56-checks-with-few-samples-2026-11-12)):

- No lateral cohesion. Each member walks its own route, so a dyad can walk side by side 2–4 m apart
- In a crowded stream, a stranger can walk between the members. With other people around, the dyad distance widens from 0.87 m to 1.13–1.23 m (in the literature, groups get closer and line up front to back as it gets crowded)
- Nothing defines what happens after members are split by different gate lanes or by elevator capacity

Proposed features:

| Feature | Content | Literature and quantities to check |
|---|---|---|
| Formation | Switch between abreast, V-shape and single file by density and corridor width | Zanlungo et al. 2015 (groups get longer as density rises), Moussaïd et al. 2010 (V-shape of groups of three) |
| Cohesion | Lateral and front–back cohesion. Strangers do not pass between members | Dyad distance and lateral spacing (Zanlungo et al. 2017), number of times someone passed between members |
| Splitting and rejoining | When split by gate lanes or elevator capacity, wait at the next place. Board the same car, and if not all fit, wait together for the next | Time spent apart, time spent waiting for members |
| Relations and roles | Colleagues, friends, family, patient and companion, person pushing a wheelchair. A leader decides where to go and the others follow | Distance by relation (tables in Zanlungo et al. 2017) |
| Output | Besides `group` in the ground truth, the formation and the times of splitting and rejoining | (to be added to docs/formats.en.md) |

To decide:

- How many relation types to model (for example colleagues, friends, family, companion)
- Whether to also build ground truth and evaluation for a group-finding task (group detection and tracking) in the benchmark
- Up to which density to verify (decide after checking the density range measured in the literature)

### 2. Components that are the purpose of a trip (other than elevators)

What exists now: entrances and exits (`spawn`, `exit`), gates (`gate`), elevators and waiting areas (`elevator`, `wait_zone`), stopping places (`spot`: reception, waiting area, in front of a sign),
placed objects (`prop: signage`), and itinerary steps (`dwell`, `then`, `meet`, `via`, `state`).
The warehouse "work, waiting, moving" (template `warehouse_picking`) is written as stopping places and stopping times (no capacity, queue or service).

Components derived from offices, hospitals, warehouses and other domains:

| Component | Behaviour | Office | Hospital | Warehouse and factory | Retail and stations (reference) |
|---|---|---|---|---|---|
| Counter | Queue, get served, move on. Number of servers, service time, queue shape (line or area) | Reception, visitor check-in | Reception, re-visit kiosk, payment, automatic payment machine, pharmacy, blood sampling | Shipping hand-over | Checkout, ticket machine |
| Called waiting | Wait seated (or standing), move on when called by number or name | Visitor waiting area | Waiting area → consultation and examination rooms | — | Food pick-up |
| Room | Enter, stay for some time, leave. Has a capacity | Meeting rooms, offices | Consultation, examination and patient rooms | Break room, locker room | Shops |
| Seating | A number of seats; walk to a free seat and sit | Lobby sofas, café | Waiting-room chairs | Rest area | Benches |
| Short stop | Used by one to a few people at a time; if busy, queue or go elsewhere | Toilets, vending machines, printers, pantry | Toilets, vending machines | Time clock | ATM, toilets |
| Work point | Work standing; visit in a set order | — | Nurse station, ward rounds | Shelves, packing, inspection, staging | Restocking |
| Non-human movers | People avoid them. Width and speed differ from people | Carts, cleaning machines | Wheelchairs, stretchers, meal carts | Forklifts, AGVs, carts | Shopping carts |
| Staff movement | Fixed rounds, go when called | Security rounds | Nurse rounds and calls | Work instructions | Shop staff |
| Changing floors | Stairs, escalators (as entrances and exits within one floor) | Stairs | Stairs | Stairs | Escalators |

Proposal (candidates for 1.2):

- Add three common components: counter (`service`: number of servers, service time distribution, queue shape, calling), seating (`seats`: seat positions and number) and room (`room`: capacity, time inside).
  Configurations written with today's `spot`, `dwell` and `wait_zone` keep loading
- Add state names to the ground truth (for example `service_queue` in a counter queue, `service` while served, `seated` while waiting seated, `in_room` inside a room)
- Templates: hospital outpatients (reception → waiting area → consultation room → payment → pharmacy), office lunchtime (café queue, seating), warehouse (work points with capacity and queues)

To decide:

- Which components come first (proposal: counter, called waiting, seating, room)
- Whether to add components without literature values (such as service times) with provisional values (marked "provisional" in the ledger of `validity.en.md`)
- Whether non-human movers (wheelchairs, AGVs) go into 1.2 or 1.3 or later
- Where the objects needed for rendering (chairs, counters, 3D models of AGVs) come from (including their licence terms)

### 3. Remaining movement fixes from 1.1

- Done (branch `crowd-1.2`): the step that puts people back near the line in front of a door jumped up to about 1 m
- In front of a crowded elevator, people taking more than 10 s to board (8–16%)
- A little shaking in place inside a crowd of waiting people
- In front of the office gates with many people, people appearing at and leaving through the south exit block each other head-on

### 4. Making spaces

- Describe the walkable area with polygons (outline and holes) and build the grid from them (today the grid file must be made by hand)
- Allow the space itself (a dict) in the configuration's `space`, or build it in Python and pass it in
- A USD for rendering is a candidate for 1.3 or later (a simple scene with floor and walls extruded from the polygons)

## 1.3 (planned)

### Two or more cameras

What exists now: a configuration can have any number of cameras. The person numbers in the per-camera ground truth (`mot/`, `labels/`) are the same across cameras. Ground truth in the
AI City Challenge multi-camera tracking (MTMC) format (`aicity/gt.txt`). Corpus v6 films one place with 9 cameras (different heights and angles).

What is missing (draft):

- Build one corpus from two or more cameras at different places (for example the gates and the elevator hall), and add ground truth and evaluation (a benchmark task) for matching the same person across cameras.
  Also ground truth and evaluation for "how many people from the entrance appear where after how many minutes" (flows of counts)
- Apply camera clock offsets and dropped frames (`clock_offset_s`, `drop_rate`) to the video and ground truth (today they are only recorded)
- Pairs of cameras with and without overlapping views, and checks that camera placement is plausible

To decide: what to build first under "support for two or more cameras" (one of the drafts above, or something else)
