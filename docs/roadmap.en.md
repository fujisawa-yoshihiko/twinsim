# Plans for the next versions

[日本語](roadmap.md)

Draft goals for the next versions and the decisions still to make. Once decided, items move to the release notes of that version (`release-X.Y.en.md`). The current version is [1.1](release-1.1.en.md).

## 1.2 (goals, decided on 2026-11-12)

Decided (2026-11-12):

- Four group relations (colleagues, friends, family, companion). Also build ground truth and evaluation for a group-finding task (group detection and tracking)
- Components come in this order: counter, called waiting, seating, room. Values without literature (such as service times) go in as provisional values (marked "provisional" in the ledger of `validity.en.md`)
- Non-human movers (wheelchairs, AGVs and others) go into 1.3 or later
- Groups are checked over the density range measured in the literature, 0–0.3 people/m² (table below). Denser places are not judged; their values are only reported

Progress: 1 groups is done (2026-11-12, [validity.en.md, section 5.8](validity.en.md#58-group-formation-12-2026-11-12)). 2 components: counters, calling, seating, rooms and the hospital outpatient template are done (2026-11-13, [5.9](validity.en.md#59-components-that-are-the-purpose-of-a-trip-12-2026-11-13)). Rendering (sitting, benches, consultation-room doors, people inside rooms) is done (2026-11-16, [5.10](validity.en.md#510-checking-the-rendering-sitting-benches-consultation-room-doors-and-people-inside-rooms-12-2026-11-16); people being served drifting from the reception desk was fixed in [5.11](validity.en.md#511-routes-avoiding-the-front-of-counters-office-lunchtime-coffee-counter-and-folds-when-members-join-the-leaders-route-12-2026-11-16)). Office lunchtime (coffee counter queue, sofas) is done (2026-11-16, 5.11). The warehouse template is still to come.

Order of work: 1 groups → 2 components → 3 remaining movement fixes → 4 making spaces → rendering (seated people, chairs, counters) → comparison with 1.1 and release notes.
The work is on branch `crowd-1.2`.

### 1. Groups (from dyads to a general group feature)

What exists now:

- Group size distribution (`group_size`, zero-truncated Poisson), group speed (`group_speed`, Moussaïd et al. 2010), lateral spacing of dyads (`group_lateral_m`)
- Cohesion along the walking direction (a member ahead waits, one behind catches up), meeting (`meet`; `companion_wait` while waiting), members do not appear at the same point
- `group` in the ground truth (who belongs to which group). Checks: share of people by group size, slope of speed against group size, dyad distance

What the 1.1 checks showed to be missing ([validity.en.md, section 5.6](validity.en.md#56-checks-with-few-samples-2026-11-12)):

- No lateral cohesion. Each member walks its own route, so a dyad can walk side by side 2–4 m apart
- In a crowded stream, a stranger can walk between the members. With other people around, the dyad distance widens from 0.87 m to 1.13–1.23 m (in the literature, the lateral extent of groups narrows as density rises; table below)
- Nothing defines what happens after members are split by different gate lanes or by elevator capacity

Literature values (ATC, Osaka. Dyads by relation: Zanlungo et al. 2017; triads: 2019; dependence on density: 2015):

| Quantity | Value | Source |
|---|---|---|
| Density range studied | 0–0.3 people/m² (bins of 0.05 people/m²; density from 0.5 m cells averaged over 300 s) | Zanlungo et al. 2015 |
| Lateral extent of dyads | 0.646 − 0.538 ρ m (ρ in people/m²). The front–back offset is 0 on average (abreast); its spread grows with density | same |
| Lateral extent of triads | 1.096 − 1.370 ρ m. V-shape at every density (the middle person 0.14 m behind); the front–back distance does not change with density | same |
| Speed against density | individuals 1.286 − 1.072 ρ, dyads 1.147 − 0.931 ρ, triads 1.092 − 0.799 ρ m/s | same |
| Dyads by relation (speed, distance, lateral, front–back) | colleagues 1.27 m/s, 0.85, 0.72, 0.33 m; friends 1.14, 0.79, 0.66, 0.31; family 1.09, 0.86, 0.58, 0.50; couples 1.10, 0.71, 0.60, 0.29 (358, 318, 246, 96 dyads) | Zanlungo et al. 2017 |
| Triads by relation (speed, lateral, front–back) | colleagues 1.19 m/s, 1.10, 0.65 m; friends 1.04, 0.97, 0.61; family 0.99, 0.88, 0.75 (79, 212, 396 triads) | Zanlungo et al. 2019 |

What to build:

| Feature | Content | Quantities to check |
|---|---|---|
| Relation | `people.group_relation` sets the shares of relations (`colleagues`, `friends`, `family`, `companion`). Lateral and front–back spacing follow the literature for each relation. `companion` (patient and companion) has no literature values, so its values are provisional | Dyad distance, lateral and front–back spacing by relation (table above) |
| Formation | Each member gets a position relative to the group centre (lateral and front–back) and moves towards it. The lateral extent narrows with density following the literature fits. Triads walk in a V. In narrow passages, members line up | Lateral extent by density bin (0–0.3 people/m²) |
| Cohesion | Lateral and front–back cohesion. Strangers do not pass between members (other people avoid the line joining the members) | Dyad distance, number of times a stranger passed between members |
| Splitting and rejoining | When split by gate lanes, wait beyond the gate. Board the same elevator car, and if not all fit, wait together for the next | Time spent apart, time spent waiting for members |
| Leader | One member decides where to go (leader); the others follow | — |
| Output | Add each group's relation, leader and the times of splitting and rejoining to the ground truth (docs/formats.en.md) | — |
| Group-finding task | Ground truth (who is in the same group, over time) and evaluation (group-level precision, recall and F1, where a group counts as found when at least 2/3 of its members match; F1 over pairs of people) | — |

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
| Non-human movers (1.3 or later) | People avoid them. Width and speed differ from people | Carts, cleaning machines | Wheelchairs, stretchers, meal carts | Forklifts, AGVs, carts | Shopping carts |
| Staff movement | Fixed rounds, go when called | Security rounds | Nurse rounds and calls | Work instructions | Shop staff |
| Changing floors | Stairs, escalators (as entrances and exits within one floor) | Stairs | Stairs | Stairs | Escalators |

What to build (1.2):

- Counter (`service`): number of service points, service time distribution, queue shape (line or area). With calling (`call`), people do not queue; they wait at a waiting place (seats or an area) and are called in order as service points free up (called waiting)
- Seating (`seats`): seat positions and directions. People walk to a free seat and sit; if all are taken, they stand nearby
- Room (`room`): door, capacity and time inside. People who enter are no longer visible (their boxes in the ground truth end too) and come out after the time with the same person id. Calling can be added (waiting area → consultation room)
- Geometry (positions, directions, queue lines, seats) goes in the space (space.yaml); behaviour values (number of servers, times, capacity) go in the configuration (the same split as gates). Configurations written with today's `spot`, `dwell` and `wait_zone` keep loading
- Add states to the ground truth (`service_queue` in a counter queue, `service` while served, `call_wait` while waiting to be called, `seated` while sitting) and the times of entering and leaving rooms
- Templates: hospital outpatients (reception → waiting area → consultation room → payment → pharmacy), office lunchtime (café queue, seating), warehouse (work points with capacity and queues)
- Rendering: sitting uses the same NVIDIA assets as today's people (such as `SitAndStandChair` in Isaac's People). Chairs and counters are first placed to match the furniture already in the space's USD; if more are needed, they come from the same NVIDIA assets (after checking the licence terms). Done (2026-11-16, section 5.10 of docs/validity.en.md): sitting animation, hospital benches (those in the USD plus more of the same asset), consultation-room doors opened only while people pass, and people inside rooms placed below the floor

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

Decided (2026-11-12): as drafted above, start with matching people across cameras at different places and with flows of counts.

### Non-human movers

Wheelchairs, stretchers, carts, AGVs, forklifts and others ("non-human movers" in the component list of 1.2). People avoid them; their width and speed differ from people. 1.3 or later.
