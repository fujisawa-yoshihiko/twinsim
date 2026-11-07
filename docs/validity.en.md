# Validity of people distributions (literature-based distributions and their verification)

[日本語](validity.md)

2026-10-22. A mechanism that builds the distributions of people's volume, types, grouping, speeds and stopping places from literature values, and compares them with the literature values after each run.
The list of literature and the values are in `twinsim/literature.py` (`REFS`, `PROFILES`); the checks are in `twinsim/validity.py`.

## 1. Approach

| Stage | What it does | Where |
|---|---|---|
| Input | Set the default values of the distributions from the literature and record the sources. Also record differences in conditions (country, time of day, building) | `literature.py`, the scenario's `people.profile` and `demand` |
| Input reproduction | Whether quantities fed in with literature distributions still have the same distribution after the run (whether the engine has distorted them) | First half of `validity.md` |
| Emergent quantities | Whether quantities that are not fed in fall within the literature ranges (speed by density, dyad spacing, distance between waiting people) | Second half of `validity.md`, the `verify_*` templates |
| Ledger | For each scenario value, list whether its basis is literature, literature for the shape only, or provisional | End of `validity.md` |

Literature values are "values observed under similar conditions", not values for the target building itself. Provisional values and literature values from different conditions
are not called "valid" until they have been fitted to real data (gate passage logs, elevator (EV) operation logs, detection and tracking trajectories) (calibration) and checked against data from another day (validation).

## 2. Literature values

| Distribution | Default value | Source | Observation conditions | Usage |
|---|---|---|---|---|
| Free walking speed | Normal distribution 1.34 ± 0.26 m/s (truncated at 0.8–1.9) | Weidmann 1993 | Compilation of many measurements (mainly Europe) | Default |
| Speed–density | v = 1.34 (1 − exp(−1.913 (1/ρ − 1/5.4))) | Weidmann 1993 (Kladek's formula) | Unidirectional flow | Default. Slows people down according to the density in the front semicircle (radius 1.5 m) |
| Following the person ahead | v ≤ (d − 0.36) / 1.06 for the distance d to the person ahead | Seyfried et al. 2005 | Single-file walking experiment | Engine rule (person ahead within 0.45 m laterally) |
| Group size (commuting) | Zero-truncated Poisson λ = 0.20 (82% of people walk alone) | Zanlungo et al. 2014 | Underground pedestrian space in Osaka | `office_commute_jp` |
| Group size (leisure) | λ = 0.78 (46% alone) | Moussaïd et al. 2010 | Shopping street in Toulouse, weekday afternoon | `leisure_low_density` |
| Shape of the group-size distribution | Zero-truncated Poisson | Coleman & James 1961 | Small, naturally forming groups | Shape |
| Group speed | −0.04 m/s per additional member (−0.08 at medium density) | Moussaïd et al. 2010 | Same as above, about 1500 groups | Default |
| Lateral spacing of dyads | Colleagues 0.72 m, overall mean 0.66 m, friends 0.66 m | Zanlungo et al. 2017 | Osaka ATC, 1018 dyads | Default 0.66; 0.72 for `office_commute_jp` |
| Dyad distance (comparison values) | Colleagues 0.85 m, friends 0.79 m, couples 0.71 m, families 0.86 m | Zanlungo et al. 2017 | Same as above | Check |
| Dyad speed (comparison values) | Colleagues 1.27, friends 1.14, couples 1.10, families 1.09 m/s; work 1.27, leisure 1.12 m/s | Zanlungo et al. 2017 | Same as above | Reference only (close to 1.34 − 0.04 = 1.30) |
| Elevator demand (number of users) | Building population × 12% ÷ 5 min (busiest 5 minutes) | Peters et al. 2011 | Current offices in Europe, North America and the UAE (observed maximum 12–13%; the old design guideline was 15%) | `demand` and `rate: {type: lift_demand}` |
| Breakdown of elevator use | Morning: incoming 85%, outgoing 10%, interfloor 5%; lunch: 45%, 45%, 10% | Peters et al. 2011 | Same as above | Incoming flow, number of people alighting |
| Elevator boarding and alighting | 1.0 s per person (the CIBSE Guide D worked example uses 1.2 s) | Peters Research default value | Design calculation | Default (`elevator.transfer_s`) |
| Gate time per person | Log-normal, median 2.0 s (1.2–4.0). Range 1.5–4.0 s, 25–40 people/min | Fruin 1987 | Card-reading turnstiles (range of observed means) | `office_commute_jp` (shape of the variability is provisional) |
| Interpersonal distance | Intimate 0–0.45 m, personal 0.45–1.2 m | Hall 1966 | Proxemics | Check (between waiting people) |
| Bottleneck capacity | 1.90–2.19 people/(m·s) at a width of 1.0 m | Seyfried et al. 2009 | Laboratory (doorway 2.8 m long, 20–60 people) | Check (`verify_bottleneck`) |
| Shape of stopping time | Log-normal | Brown et al. 2005 | Telephone call-handling times | Shape (applying it to the reception desk is by analogy) |

Full bibliographic references are at the end of `validity.md` and in `literature.REFS`. The values were checked against the text and tables of the papers (Weidmann's formula via arXiv:1512.01426;
the group proportions in the Osaka underground and Fruin's turnstile table from secondary sources that reproduce them; each is noted in `REFS[...]["check"]`).

## 3. Usage in scenarios

```yaml
people:
  profile: office_commute_jp      # literature profile (speed, groups, speed–density, gate, elevator boarding/alighting). Values you write take precedence
demand:                            # elevator demand (Peters et al. 2011)
  population: 600                  # building population (enter the building's value)
  period: morning                  # morning (incoming 85%, outgoing 10%) or lunch (45%, 45%)
  peak_pct_5min: 12                # share in the busiest 5 minutes
streams:
  - name: commuters
    origin: entrance
    rate: {type: lift_demand, flow: incoming, share: 0.9}   # 90% of the incoming flow (the rest are visitors etc.; share is provisional)
    destinations: [{to: elevator, via: [gate]}]
  - name: other
    origin: entrance
    rate: {type: constant, per_min: 2.5, unit: persons}       # unit: persons means people/min (if omitted, groups/min)
elevator:
  alight:
    count: {type: lift_demand, flow: outgoing}               # mean of the outgoing flow divided by the number of elevator arrivals (Poisson)
```

When you enter literature values yourself, writing `source: <REFS key>` on the distribution makes the ledger count it as "literature".
In the GUI, the "People distributions (literature)" section lets you choose the profile and the building population. The results tab shows `validity.png` and `validity.md`.

## 4. Checks (validity.json, md and png are written for every run; also with `./run.sh check <run>`)

| Item | Type | Verdict criterion |
|---|---|---|
| Free walking speed (walking with nobody in the 2.5 m half-circle ahead, per-person median; group members excluded) | Input reproduction | Mean and standard deviation within ± 0.05 of the speeds given to those people, and the speeds given to everyone have mean 1.34 ± 0.08 and standard deviation 0.18–0.34 (changed on 2026-11-06; 5.3) |
| Group size (share of people) | Input reproduction | Difference from the input distribution (total variation distance) at most 0.08 or 1.5/√(number of people) |
| Group speed (slope against group size) | Input reproduction | −0.14 to 0 m/s per person (when there are 15 or more groups) |
| Arrivals (per stream; people still waiting outside at the end are counted) | Input reproduction | Difference from the specified people/min within ±2 in z (variance = mean × the person-weighted mean group size; with a 2σ test, about one in 20 correct streams is still flagged "caution") |
| Outgoing share of elevator use | Input reproduction | Difference from the literature (morning 0.105, lunch 0.5) within 2 standard errors + 0.03 |
| Interval between consecutive people boarding an elevator | Input reproduction | Median 0.7–1.6 s |
| Gate time per person when crowded | Input reproduction | Median 1.5–4.0 s (10 or more pairs of consecutive passages in a lane where the second person had already stopped in the queue before the first passed) |
| Speed by density | Emergent quantity | Ratio to the person's own speed matches the formula's v/v0 within an RMS of 0.12 at 0.5 people/m² or more (verdict only for the unidirectional corridor `verify_*`; reference only otherwise) |
| Dyad distance (excluding the time from joining a gate queue until 5 s after passing) | Emergent quantity | Literature (colleagues 0.85 m, etc.) ± 0.15 m |
| Nearest distance between waiting people (between people standing and waiting; people walking past are not counted) | Emergent quantity | Below 0.45 m in at most 5% |
| People stuck and unable to move | Emergent quantity | In the last 30 s, 0 people en route or in a gate queue who moved less than 0.3 m (excluding people who went more than 2 m away and came back in that time) |
| Doorway capacity | Emergent quantity | Within ±15% of 1.90–2.19 people/(m·s) from the 1.0 m width experiment (when `validity: {bottleneck: ...}` is set) |
| Time spent waiting in elevator and gate queues and outside the entrance | Reference only | No literature to compare with |

## 5. Results of the engine verification (2026-10-22)

Results are in `~/dt-data/twinsim/runs/<template>/validity.md` and `validity.png`.

| Check | Simulation | Literature / expected | Verdict |
|---|---|---|---|
| `verify_corridor_speed` (equivalent to RiMEA test 1) | 40 m in 30.07 s | 40 ÷ 1.33 = 30.1 s | Pass |
| `verify_fundamental_diagram` (580 people, up to 123 at the same time, up to 1.4 people/m²) | Ratio to own speed: 0–0.25 people/m² 0.96, 0.25–0.5 0.93, 0.5–1 0.80, 1–1.5 0.65. Speed: 1.26, 1.19, 1.07, 0.89 m/s | Formula: 1.00, 0.99, 0.89, 0.69. 1.34, 1.33, 1.19, 0.93 m/s | Pass (ratio difference at 0.5 people/m² or more 0.069, speed difference 0.089 m/s) |
| `verify_groups` (92 people, 20 groups, leisure profile) | Share of people in groups of 1/2/3 = 52/35/13%, group-size slope −0.076 m/s per person, dyad distance 0.78 m, lateral 0.70 m | Input 46/36/14/4/1%, −0.04 to −0.08 m/s per person (Moussaïd), friends 0.79 m, 0.66 m (Zanlungo) | Pass |
| `verify_gate_capacity` (75 people/min into 2 entry lanes) | Interval when queued: median 1.97 s; max 32 people/min per lane | 1.5–4.0 s, 25–40 people/min (Fruin, card-reading turnstiles) | Pass |
| Same as above: distance between waiting people | 2.6% below 0.45 m (reduced from 8.5% by changing the queue spacing 0.6 → 0.65 m) | Few below 0.45 m (Hall) | Pass |
| `verify_counterflow` (35 people/min from each end, 4 min) | 0 stuck people, 1.7% of frames with people closer than 0.4 m, speed ratios by density 0.99, 0.97, 0.88, 0.65 | Formula 1.00, 0.99, 0.89, 0.69 (reference only, since it is a unidirectional formula) | Pass |
| `verify_bottleneck` (180 people/min into a 1.0 m wide doorway) | Up to 139 people in 1 min = 2.32 people/(m·s), 0 stuck people | 1.0 m width experiment 1.90–2.19 people/(m·s) (Seyfried et al. 2009; the maximum of Weidmann's formula, 1.22, is lower than the experiments) | Pass (+6% over the experiment) |
| `office_gate_ev` (94 people, 5 min, morning peak with a building population of 600) | Free walking speed 1.28 ± 0.27 m/s, share of people 85/12/4%, commuter arrivals 10.8 people/min, elevator outgoing share 0.135, consecutive boarding interval 0.84 s, dyads 0.96 m, lateral 0.78 m, between waiting people median 0.85 m (2% below 0.45 m) | 1.34 ± 0.26, input 82/17/2%, 11.0 people/min, 0.105, 1.0–1.2 s, colleagues 0.85 m, 0.72 m | All pass (group speed and gate interval not applicable because of small numbers) |
| Same as above: reference only | Elevator wait mean 15.6 s, 90% 26.8 s; 6 people were still waiting at the end. Speed ratio at 0.5–1 people/m² 0.76 (formula 0.89) | - | Reference only (the lobby has corners and merging flows, so it is slower than a corridor) |

Engine fixes (made during this verification): changed the following rule to the Seyfried et al. 2005 relation and the width available for stepping aside from 0.6 → 1.0 m,
and added overtaking when stuck behind a slower person, waiting / catching up when separated front-to-back from group members, lining up gate queues along the path people came from, and waiting outside when the entrance is blocked.
Proximity between people also improved (office_gate_ev: 1st percentile of the nearest distance between two people not in the same group 0.12 → 0.25 m; frames with people closer than 0.4 m 10% → 3.3%).

### 5.1 Movement in which people do not collide (2026-11-05, `people.motion_model: cfsm`)

The earlier model (`lane`) only shifted people sideways from their path; there was no rule keeping bodies from overlapping with people standing and waiting
or coming the other way, so people passed through each other in crowded places. To make the simulator usable for optimizing flows (comparing layouts and widths), it was replaced with a model from the literature.

- **Model:** Collision-Free Speed Model (Tordeux, Chraibi, Seyfried 2016; the same form as JuPedSim's CollisionFreeSpeedModel).
  - Speed = min(own speed, (distance to the person ahead − 0.36 m) ÷ 1.06 s). 0.36 m and 1.06 s are the same Seyfried et al. 2005 values as in the earlier model.
  - Direction = direction to the goal + away from nearby people (strength 8, range 0.25 m) + away from walls. Between group members the range is 0.1 m.
  - The range was chosen by comparing 0.1, 0.2, 0.25 and 0.3 m with strengths 3, 5 and 8 against the speed–density relation (Weidmann) and a 1 m wide doorway (Seyfried et al. 2009) (with JuPedSim's default of 0.1 m, people stayed behind slower people and were too slow).
- **Rules for busy places:** gate queues follow the order in which people actually stand; nobody waits right in front of an elevator door or in the aisle out of it (2.5 m × 1.2 m);
  people boarding wait at the door until those alighting are out; a standing person makes way for a walker they block (0.4 m/s, up to 1.5 s);
  the path is recomputed when a walker is more than 1.5 m from it or cannot see ahead.
- **Safety valve:** a person who cannot get closer to their goal for 15 s walks through others at half speed for 2 s (count in `motion.squeezes` of `summary.json`).
  This prevents people from getting stuck, at the cost of a little overlap.

Checks (same seeds, `tools/crowd_check.py`; overlap = pairs × frames of two people not in the same group whose centers are closer than 0.3 m, per 1,000 person-frames):

| Template | Overlap (before → now) | Stuck people | Safety valve | Comparison with literature |
|---|---:|---:|---:|---|
| `verify_fundamental_diagram` | 0 → 0 | 0 → 0 | 0 | Speed ratio 0.95, 0.91, 0.81, 0.76 (formula 1.00, 0.99, 0.89, 0.69; before 0.96, 0.93, 0.80, 0.65) pass |
| `verify_counterflow` | 0.12 → 0 | 0 → 0 | 0 | 0 stuck people |
| `verify_bottleneck` | 1.85 → 0.41 | 0 → 0 | 17 | 1.90 people/(m·s) (experiment 1.90–2.19; before 2.32) pass |
| `verify_gate_capacity` | 7.47 → 0 | 0 → 0 | 4 | Queue headway median 1.95 s, waiting people below 0.45 m 4.8% (before 12%), pairs 0.99 m; all pass |
| `verify_groups` | 0 → 0 | 0 → 0 | 0 | Pairs 0.93 m (friends 0.79 m) pass. Speed ratio at 0.5–1 people/m² 0.74 (formula 0.89) caution |
| `office_gate_ev` | 2.66 → 0.21 | 0 → 0 | 20 | All pass (pairs 0.89 m, interval between consecutive elevator boardings 1.38 s) |
| `office_ev_hall` | 1.99 → 0.26 | 0 → 0 | 24 | Pairs 0.93 m pass. Boarding interval 1.93 s caution (few pairs; it varies between 1.2 and 1.9 s across versions of the fixes) |
| `hospital_gate_ev` | 1.21 → 0.33 | 0 → 0 | 16 | Pairs 0.85 m, boarding interval 1.02 s pass |

- **Group and elevator rules (added on 11/5):** when the person ahead is a group member, the following time gap is 0.5 s (with 1.06 s, pairs forced into single file in crowds ended up about 1.6 m apart).
  People board the elevator in two lanes in boarding order (±0.25 m at the door, ±0.35 m in the car; in a single lane the interval between consecutive boardings grew to 1.8 s).
  People heading for a gate queue stop 0.65 m behind people in the queue. People entering from behind a door wait outside if someone is within 0.5 m of the door point.
- **Free walking speed:** 1.245 m/s in `verify_fundamental_diagram` (guide 1.34 ± 0.08), "caution". It is measured on people with nobody within 1.5 m ahead,
  but fast walkers already slow for someone 2 m ahead (2.4 m at 1.9 m/s with Seyfried's relation). Most people walk at their own speed (median speed ratio 1.00).

### 5.2 No more people stuck at doors, gates and elevator doors (2026-11-06)

In rendered material (the hospital elevator area at a busy time), a person leaving through the lobby entrance was stuck in the corner of the entrance for more than 30 s.
The causes were fixed one by one.

- **Two lanes at doors:** walking to and from behind a door (`hidden`) used a single line, so while people kept entering, a person leaving could not get onto the line and was pushed into the corner.
  People entering keep the original line; people leaving use a line 0.6 m beside it (on the left of the outgoing direction, or the right if the left is a wall; `Space.door_lanes`). At the hospital lobby entrance the leaving lane is 0.6 m north;
  at the office entrance 0.6 m east (west is a wall). Exit-only doors keep a single line. The portal area is centered between the two lanes. The earlier model (`lane`) keeps a single line.
- **Lateral limit for people walking behind a door:** a step beyond 0.35 m from the line used to be put back "0.35 m beside the closest point of the line", and on the inside of a corner of the path (elevator door → back of the car)
  that point coincided with the old position, so the step vanished (7 people stood still for 50 s in front of an office elevator door and got through only with the safety valve). Now only the part of the step that moves away from the line is removed.
- **No lingering overlap:** with someone closer than a body width (0.36 m), the rule on the distance to the person ahead gives speed 0, so people could not move apart. They now walk away from those people at 0.3 m/s.
  A standing person making way may also step if the step moves away from people who are already too close (before, they could only move if the new position was at least 0.36 m from everyone).
- **Swaps in front of gates:** within 2 m of a gate people walk straight along their path (no avoiding), so a queue stopped (for over a minute with some seeds of verify_gate_capacity) when (1) two people heading diagonally for each other's neighboring lane blocked each other,
  or (2) the head of a queue was blocked by the second person standing in front of the head's place. The blocked person and the blocker now swap queue positions (and lanes, if different) (count in `motion.lane_swaps` of `summary.json`). Two people side by side in the same lane who block each other are not swapped; the step away resolves it.
- **Stuck-person check:** it compared the position 30 s earlier (less than 0.3 m) and counted a person who went through a gate and came back and happened to be in the same place. People who went more than 2 m away in those 30 s are now excluded.

Checks (`tools/crowd_check.py`; overlap as in 5.1). With the template seeds:

| Template | Overlap (before → now) | Stuck people | Safety valve | Comparison with literature |
|---|---:|---:|---:|---|
| `verify_bottleneck` | 0.41 → 0.44 | 0 → 0 | 17 → 20 | 1.93 people/(m·s) pass |
| `verify_gate_capacity` | 0 → 0 | 0 → 0 | 4 → 5 (4 swaps) | Waiting people below 0.45 m 4.8 → 1.2%. Queue headway not applicable (only 8 cases of someone already waiting). Pairs 0.99 → 3.34 m caution (one pair split at the entrance; see below) |
| `office_gate_ev` | 0.21 → 0 | 0 → 0 | 20 → 1 | All pass |
| `office_ev_hall` | 0.26 → 0.24 | 0 → 0 | 24 → 2 | Interval between consecutive elevator boardings 1.93 s caution → 1.06 s pass |
| `hospital_gate_ev` | 0.33 → 0 | 0 → 0 | 16 → 0 | Pass |

The other templates are unchanged. Means over seeds 1–8 (per run):

| Template | Overlap | Stuck people (total of 8 runs) | Safety valve |
|---|---:|---:|---:|
| `office_gate_ev` | 0.24 → 0.08 | 0 → 0 | 29.4 → 2.1 |
| `office_ev_hall` | 0.43 → 0.16 | 1 → 0 | 34.1 → 5.4 |
| `hospital_gate_ev` | 0.85 → 0.18 | 0 → 0 | 21.2 → 2.2 |
| `verify_gate_capacity` | 0 → 0 | 0 → 0 | 0.6 → 0.4 (people through 166.6 → 172.1; before, one lane stopped for a minute with seed 7) |

Configurations of set A of the corpus (hospital and office elevator areas and the office gate, low/mid/high × seeds 1–3, 27 runs): stuck people 2 → 0, total safety-valve uses 189 → 105.

Remaining:
- The queue-headway check of `verify_gate_capacity` often has fewer than 10 cases of "someone already waiting in the queue when the person ahead passed" (all seeds 1–8 were not applicable before as well),
  because everyone walks to the next place each time the queue moves (and is not waiting meanwhile). The measurement needs fixing.
- When the entrance is crowded and the queue reaches it, the second member of a group waits outside the entrance and the group splits (the rule of waiting outside when the door point is blocked).
  Pair distance over seeds 1–8: mean 1.10 → 1.28 m (3/8 pass, before and now).
- Overlap in `verify_bottleneck` rose slightly, 0.41 → 0.44 (safety valve 17 → 20).

(These three were fixed in 5.3.)

### 5.3 Entrance order, a second entering line, gate queues, crowding in front of elevators, and how the checks measure (evening of 2026-11-06)

The remaining items of 5.2 were investigated, and both the motion and the measurements of the checks were changed.

Motion (engine):
- **People waiting at an entrance enter in order of arrival:** waiting people checked whether they could enter only every 0.2 s, so a later arrival took a brief gap first
  (the second person of a pair waited outside for 47 s while later people went in). Now waiting people are checked every frame, per entrance, in order of arrival (a group together), and while someone ahead is waiting, those behind wait too.
- **A second entering line:** people entered from behind the door one by one along a single line, so the entrance let in only about 58 people per minute (`verify_gate_capacity`
  feeds 75 people/min to build a queue at the gate, but its arrivals were flagged "caution", the queue never grew long, and 96% of the people who entered had waited outside for 14 s on average).
  When the entering line is blocked, people also enter along the leaving people's line, but only when nobody leaving through it is within 5 m of the door point (`motion.entry_alt` in `summary.json`).
- **How groups enter:** a group member also waits while a member is within 0.4 m of the spawn point (two members appeared at the same point in the same frame and one was pushed out around the door post).
  The second member enters side by side on the other line when it is free (entering one behind the other kept them walking in single file down the corridor). No lateral offset is applied while walking the door line (`straight`).
- **Groups wait for each other at stops:** someone who finishes a stop (reception, etc.) first waits until the members on the same stop have finished (at most 60 s). They had arrived at different times and the first walked off,
  so a pair going to the reception walked 10 m apart.
- **Two people side by side in the same gate lane:** someone later in the queue standing right beside you (0.3 m or more to the side) is not treated as the person ahead. Two people who had entered side by side joined the same lane,
  each treated the other as a queued person to keep 0.65 m from, and the lane stopped for 150 s (also between members of a group).
- **Restoring the lateral offset:** when the point offset sideways from the path is not walkable in front of a wall, the reduced offset now recovers by 0.5 per second instead of at once. Whether the offset point was walkable flipped at every step,
  and one member of a pair moved back and forth in front of a door corner for 12 s (this existed in the previous version too).
- **Yielding at a merge:** if someone who has been unable to make progress longer than you (5 s or more) is close and diagonally ahead (within 1 m, 0.6 m to the side), you treat them as the person ahead, slow down, and let them in first.
  People at the corners in front of an opening could not cut into the central stream and passed through with the safety valve after 15 s (about 20 times per run in `verify_bottleneck`). People yield in order of how long they have been stuck.
- **People who cannot progress ask standing people to step aside:** a walker who has made no progress for 3 s or more although nobody is directly ahead asks the people standing and waiting within 0.9 m on the goal side to step sideways
  (before, only the person blocking straight ahead was asked; among the people waiting for an elevator, the push from those around changed direction every frame and one person could not progress for 28 s).
  People heading for a gate also use the safety valve when they are more than 2 m from the gate (not while waiting behind the queue).
- **When re-planning a path, the part outside the walkable area is kept:** when a person boarding an elevator re-planned the path at a corner, the goal (inside the car) is outside the walkable area, so the new path ended in front of the door
  and the person "boarded" and disappeared outside the door (this existed in the previous version too). The route is now searched to the last walkable point and the rest of the original path is appended.

Checks (`validity`):
- **Gate headway:** of two consecutive people through the same lane, the case counts when the second had already stopped in the queue before the first passed. Before, cases were chosen by "in the queue state at the moment the person ahead passed",
  but everyone starts walking each time the queue moves (and is en route meanwhile), so none of seeds 1–8 reached 10 cases.
- **Arrivals:** people who arrived but were still waiting outside at the end (`outside_at_end` in `summary.json`) are counted. The variance of the count is the mean × the person-weighted mean group size
  (Σ k × (share of people in groups of k)). Before, it was 1.2 for every stream.
- **Free walking speed:** measured on walking with nobody in the 2.5 m half-circle ahead, compared with the speeds given to those people, and the distribution of the speeds given to everyone is compared with the literature. In cfsm,
  a person slows down when the person ahead is closer than 0.36 + 1.06 × speed (2.4 m at 1.9 m/s), so with 1.5 m fast people came out slow (ratio to the given speed 0.82 at 1.8 m/s).
  With 2.5 m the ratio is 0.99–1.00 at every speed. Even so, in a crowded stream fast people catch up with someone ahead and cannot be measured, so the people measured are biased toward slow walkers
  (1.27 m/s in `verify_fundamental_diagram`; the speeds given to those people are equally low).
- **Dyad distance:** the time from joining a gate queue until 5 s after passing is excluded (in the queue the pair stands one behind the other, and the gate lets one person through at a time; the literature is for pairs walking side by side in a corridor).
- **Distance between waiting people:** only between people standing and waiting. Before, the distance to people walking past was also counted, contrary to the definition in this document (13% below 0.45 m from people passing along the queue).
  Closeness to walking people is covered by the overlap measure (5.1).
- **Stuck people:** people in the middle of a gate queue are also counted (the queue was not counted, and a lane that stopped for 150 s was missed). Only people who were en route or in a queue during the whole 30 s are counted
  (someone who had stood at the reception and started walking 6 s before the end was counted).

Checks (mean of seeds 1–8; "before" is the 5.2 version fa7b9cc re-evaluated with the current checks, to separate what changes only because the checks changed):

| Template | Stuck people (total over 8 runs) | Safety valve | Overlap | Comparison with the literature (passes out of 8) |
|---|---:|---:|---:|---|
| `verify_gate_capacity` | 0 → 0 | 0.4 → 0.3 | 0 → 0 | People entered 172 → 182, mean wait outside the entrance 16.1 → 10.4 s. Arrivals 0 → 8, dyads 5 → 7 (1.07 → 0.95 m), gate headway 8 → 8 (1 → 8 with the old check). Dyads with the default seed 3.06 m caution → 0.91 m pass |
| `verify_bottleneck` | 0 → 0 | 22.4 → 19.9 | 0.45 → 0.38 | 1.93 → 1.91 people/(m·s), pass. Free walking speed 7 → 8 (0 with the old check) |
| `verify_fundamental_diagram` | 0 → 0 | 0 → 0 | 0 → 0 | Free walking speed 8 → 8 (0 with the old check; from the change in the check). Speed by density unchanged |
| `verify_counterflow` | 0 → 0 | 0 → 0 | 0 → 0 | Arrivals 6 → 6 (see remaining items below) |
| `office_gate_ev` | 0 → 0 | 2.1 → 1.5 | 0.08 → 0.09 | Dyads 4 → 5 (1.11 → 1.06 m) |
| `office_ev_hall` | 0 → 0 | 5.4 → 3.5 | 0.16 → 0.04 | Dyads 7 → 7 |
| `hospital_gate_ev` | 0 → 0 | 2.3 → 0.6 | 0.18 → 0.03 | Dyads 8 → 8 |

`verify_groups` and `verify_corridor_speed` are unchanged. The three elevator templates were also compared over seeds 1–16 (overlap varies a lot from seed to seed):

| Template | Stuck people (total over 16 runs) | Safety valve | Overlap (seeds lower / higher) | Dyads (passes out of 16) |
|---|---:|---:|---:|---|
| `office_gate_ev` | 0 → 0 | 2.8 → 1.4 | 0.13 → 0.06 (9 / 2) | 10 → 13 |
| `office_ev_hall` | 0 → 0 | 4.8 → 3.2 | 0.17 → 0.04 (9 / 3) | 15 → 15 |
| `hospital_gate_ev` | 1 → 0 | 9.3 → 3.2 | 0.47 → 0.07 (10 / 0) | 13 → 13 |

Configurations of set A of the corpus (27 runs): stuck people 0 → 0, total safety-valve uses 105 → 95, overlap 0.15 → 0.13 (safety valve in `A_hospital_ev_peak` 35 → 16).
More people entered in the crowded configurations (commuter arrivals in `A_office_gate_peak` were flagged "caution" in all three runs before, z = −2.4 to −2.8, with only about 70% of the specified number entering (86–91 of 120); they now pass).

Tried and reverted: joining the path of a group member who started the same step (stuck people rose to 7–10), and letting people standing in a gate queue step aside for people walking the other way (safety valve only 55 → 49, and one person got stuck).

Remaining:
- In crowded configurations the safety valve in front of the gate increased (26 → 55 over 3 runs in `A_office_gate_peak`; it surfaced because the specified number now enters).
  (Recounted in 5.4: the explanation written here, "people leaving cannot get past the queue", was wrong. Of the 55, 25 were people who, because of an error in the corpus
  configuration, passed the gate and then turned back to the east room, and 28 were people appearing and people leaving meeting head-on at the south exit.)
- The arrival check is a 2σ test, so about one in 20 correct streams is flagged "caution" (`verify_counterflow` seeds 2 and 5 have z = −2.2 and +2.6; arrivals are a Poisson process,
  and the variance-to-mean ratio over the 16 streams is 1.39).
- A pair who stood apart at the reception sometimes takes different corridors from there (dyads 1.14 m with seeds 9–16 of `hospital_gate_ev`, 1.03 m in the previous version, both 5/8).
  Pairs can also split into different lanes at the gate.

### 5.4 People waiting for an elevator standing in contact with a neighbour, and destinations on the near side of a gate (2026-11-07)

Two things that went wrong when the corpus re-rendered with the 5.3 version (v4, "v4" in `~/MOPF_ALL_video/research/video_corpus/audit/README.md`) was compared with v3.
The checks in 5.3 did not compare how close waiting people stand to each other (`standing_spacing` in section 4) for the elevator templates (an oversight; five of seeds 9–16 of `hospital_gate_ev` failed it in the 5.3 version).

- **People waiting for an elevator standing in contact with a neighbour:** in the corpus case `A_hospital_ev_mid`, 17% of waiting people were closer than 0.45 m to a stranger (1% in v3).
  Four pairs stood 20–30 s at 0.36 m, where bodies touch; in all four, a person who had stepped aside under the 5.3 rule "a stalled walker asks standing people to step aside" moved 0.2–0.6 m and never came back.
  Removing that rule brings it back to 3%, but the safety valve rises 4 → 12 and pair-frames closer than 0.3 m 22 → 141. So the rule stays and two rules were added:
  - A person who stepped aside goes back to where they stood once every walker is more than 0.9 m from that spot (`HOME_CLEAR_M`; if the step back would bring them closer than a body width to anyone, they wait).
  - A person waiting for an elevator who is closer than 0.45 m to a standing stranger moves away at 0.2 m/s if there is room (up to 0.4 m from where they stood; never a step that brings them closer than 0.45 m to anyone else).
    Not only people who had stepped aside, but also people who moved forward after a car left and people who stopped short of their spot, were left standing in contact with a neighbour.
- **Destinations on the near side of a gate:** the corpus configuration for the office gate (set A, low, mid and peak) sent 25% of commuters "through the gate to the east room",
  but the east room's entrance is only on the near side of the gate (the north hall). Those people passed the gate, turned back, crossed the gate line again and walked north up the corridor
  beside the incoming queue (since v1; 25 of the 55 safety-valve uses in `A_office_gate_peak` over 3 runs, and in v4 mid one pair drifted 4.5 m apart).
  When a scenario is read (`validate`), a configuration in which, after passing a `via` gate, the route to the destination crosses the gate line again is now rejected as an error
  (all 13 templates pass; the corpus configuration now sends those people to the west corridor beyond the gate).

Checks ("before" is the 5.3 version 2d7b575). The six templates without elevators (`verify_*`) give identical results for seeds 0–8 (the fix acts only on standing people). The three elevator templates (mean of seeds 1–16):

| Template | Waiting people closer than 0.45 m (passing seeds / 16) | Safety valve | Overlap | People who got stuck | Pairs (passing / 16) |
|---|---|---:|---:|---:|---:|
| `office_gate_ev` | 0.5% → 0.1% (16 → 16) | 1.38 → 1.25 | 0.061 → 0.028 | 0 → 0 | 13 → 13 |
| `office_ev_hall` | 1.4% → 0.4% (15 → 16) | 3.19 → 2.75 | 0.042 → 0.070 | 0 → 0 | 15 → 15 |
| `hospital_gate_ev` | 4.2% → 0.4% (11 → 16) | 3.19 → 2.88 | 0.074 → 0.098 | 0 → 0 | 13 → 13 |

Corpus set A (27 runs, both with the corrected corpus configuration): people who got stuck 0 → 0, runs with more than 5% of waiting people closer than 0.45 m 7 → 2, pairs flagged "caution" 7 → 7,
safety valve in total 62 → 69, overlap 0.10 → 0.17. Most of the overlap increase is a single incident in seed 3 of `A_hospital_ev_peak` (pair-frames closer than 0.3 m 108 → 408):
a person heading for the elevator went into the waiting people through the safety valve and stopped among them for 3–4 s (the waiting people did not move). In seed 1 of `A_hospital_ev_mid` (22 → 52),
a person stepping aside for someone leaving the elevator stepped toward where that person would turn next (the 5.3 rule). In both, the fix changed where waiting people stand, which changed where such incidents happen; they vary widely from seed to seed.
With 1.5 m or 2.5 m as the distance checked before going back, overlap went up or down and the spacing of waiting people got worse, so 0.9 m was kept.
The corrected corpus configuration reduces the safety valve in `A_office_gate_peak` 55 → 16 over 3 runs (with the previous code).

Remaining:
- When the area in front of an elevator is crowded, a person heading for the elevator can go into the waiting people through the safety valve and stop among them (`A_hospital_ev_peak`). A standing person steps aside
  perpendicular to the walker's direction at the time of asking; if the walker then turns, the person ends up in the walker's new path.
- At the south exit (office), people appearing from beyond the door and people leaving meet head-on (most of these safety-valve uses are beyond the edge of the map, where cameras do not see).

### 5.5 Walkers shaking back and forth in place (2026-11-08)

In the v5 corpus videos, walkers that had stopped in front of other people kept shaking in place in the walking pose (with the body turning by 90–150 degrees).
Counting "shaking" as a 1-second window with a net movement below 0.15 m in which the step direction reverses 3 times or more, the walking flag switches 3 times or more,
or the heading swings by 20 degrees or more and back at least twice, the six corpus cases had 2.5–108 per 1,000 person-seconds, the three elevator templates (seeds 1–16) 39–46, and `verify_bottleneck` 159.

- **Cause:** the walking direction is "direction to the destination + direction away from nearby people and walls", normalised to length 1. In front of waiting people (0.88 m behind a person straight ahead),
  the pull to the destination and the push away cancel, the sum has a length of about 0.1, and its direction reverses when the position moves by 1 cm. The speed was set from the free space in that direction
  (the person's own speed if nobody is there), so the person jumped back and forth by 1–5 cm every frame, at up to 1.4 m/s (90% of the shaking frames were this; median length of the sum 0.1).
  The written "walking" flag and heading were set from the single frame's step, so the body swung while in the walking pose. In a simple case of a walker heading between two people standing side by side,
  the step direction reversed 41 times in 2.9 s, and in the last second the walker went back and forth over 1.34 m (its own speed).
- **Fixes (three):**
  1. When the step direction changes by more than 90 degrees from the previous frame (going back and forth), for 0.5 s and then for as long as the sum stays shorter than 0.5, the speed is multiplied by
     "length of the sum ÷ 0.5", and a step against the destination is limited to 0.3 m/s (the walker stops where the two balance; `BALANCE_E`, `CHATTER_S`, `BACK_M_S`).
  2. The written "walking" flag and heading come from the speed smoothed over 0.3 s (walking starts above 0.2 m/s and stops below 0.1 m/s, or after 2 frames with almost no movement; `OUT_TAU`).
     Positions are not changed.
  3. A boarding person waiting at the door for people getting off now also steps aside when a stalled walker asks (added to the people who give way in 5.3). Before, they stood in front of the door,
     and people getting off got through by shaking. With fix 1 alone, getting off took 20–50 s and the boarding people kept waiting (in `hospital_gate_ev` seed 13, six boarding people took about 70 s to reach the door).
- **Tried and not used:** slowing down even when not going back and forth (people passing each other head-on also slow down; in `verify_counterflow` the free walking speed matched in 9 → 2 of 9 seeds
  and travel time went 41 → 49 s). Slowing down by the square, or capping the speed where the forces balance (less shaking, but people stayed stuck in crowded places: 1–5 people in the 27 corpus runs).
  Always turning the walking direction gradually (Xu, Chraibi and Seyfried 2021, Eq. 7, τ = 0.3 s; shaking in front of elevators went to 0.3–0.7, but the free walking speed matched in 0 of 9 seeds for
  `verify_bottleneck` and `verify_counterflow`, and the bottleneck flow went 1.91 → 1.69 persons/(m·s)). Stepping to the left for an oncoming walker, and not slowing down boarding people
  (neither reduced the number of people who took more than 10 s to board).

Checks ("before" is the 5.4 version 5cc7573; seeds 0–8, seeds 1–16 for the three elevator templates, 27 runs for corpus set A; shaking per 1,000 person-seconds):

| Target | Shaking | Safety valve | Overlap | Stuck | Took > 10 s to board | Other changes |
|---|---|---:|---:|---:|---:|---|
| `office_gate_ev` | 38.6 → 2.8 | 1.25 → 0.88 | 0.028 → 0.042 | 0 → 0 | 61 → 62 | seeds with matching pairs 13 → 11 |
| `office_ev_hall` | 45.5 → 4.8 | 2.75 → 1.94 | 0.070 → 0.020 | 0 → 0 | 133 → 148 | pairs 15 → 13 |
| `hospital_gate_ev` | 42.9 → 5.6 | 2.88 → 3.75 | 0.098 → 0.156 | 0 → 0 | 55 → 59 | |
| `verify_bottleneck` | 158.9 → 5.6 | 19.7 → 11.9 | 0.371 → 0.157 | 0 → 0 | | flow 1.91 → 1.91, seeds with matching free walking speed 9 → 7 |
| `verify_gate_capacity` | 8.8 → 2.5 | 0.89 → 0.78 | 0 → 0 | 0 → 0 | | gate headway still 9 / 9, pairs 8 → 7 |
| `verify_counterflow` | 3.5 → 3.1 | 0 → 0.11 | 0 → 0 | 0 → 0 | | travel time 41.2 → 42.4 s |
| Corpus set A (18 elevator runs, 9 gate runs) | 53–55 → 6, 11.0 → 5.5 | total 69 → 56 | 0.34, 0.18, 0 → 0.24, 0.15, 0 | 0 → 0 | 25 → 34 | in the 18 elevator runs, runs with matching waiting spacing 16 → 15, matching free walking speed 15 → 14 |

In `verify_corridor_speed`, `verify_fundamental_diagram` and `verify_groups`, free walking speed, pairs and arrivals are all unchanged (shaking was already almost 0).
In the six corpus cases (seed 1, the configurations rendered as video), shaking went 2.5–108 → 0–11, people who shook 124 → 52, safety valve 11 → 6, stuck 0 → 0.

Remaining:
- Shaking does not reach 0 (3–6 per 1,000 person-seconds in front of elevators: inside a crowd of waiting people, and after the step away from someone closer than body width).
- In front of a crowded elevator, 8–16% of boarding people took more than 10 s to board even in the previous version (they walk to the door through the waiting people).
- In `hospital_gate_ev`, overlap and safety-valve use went up a little (large variation between seeds).

## 6. Values without literature (provisional) and how to calibrate them with real data

| Value | Current | How to calibrate |
|---|---|---|
| Building population | 600 people (provisional) | The building's population (entry logs). Elevator demand is proportional to it |
| Split of the incoming flow (visitors 7%, meeting someone 3%) | Provisional | Reception logs; manual labels on short segments of real video |
| Ground-floor (1F) flows that do not use the elevators, pass-through | Provisional | Difference between the gate passage logs and the number of people boarding elevators |
| Destination shares, stopping time at reception | Provisional (the shape of the stopping time is log-normal) | Real video; flow estimation |
| Elevator arrival interval, time until the doors open | Provisional | Elevator operation logs |
| Variability of gate time per person | Range from the literature, shape provisional | Time intervals in the gate passage logs |
| Shape of the time-of-day peak (how morning arrivals build up) | No literature figures obtained. Generated at the constant rate of the busiest 5 minutes | Aggregate the gate passage logs per minute |

## 7. Limitations

- No literature was found on group proportions in office lobbies themselves. The underground pedestrian space in Osaka (including commuters) is used as a substitute.
  This agrees with the trend in a review (Nicolas & Hassan 2021) that there are fewer groups on weekdays and at rush hour.
- At 0.25–1 people/m², the simulated speed is about 0.1 m/s slower than Weidmann's formula (because the overtaking behavior is simple).
- The gate values are for card-reading turnstiles from 1987. Today's IC-card and face-recognition gates may be faster.
- Corners, stairs and evacuation have not been verified (of the RiMEA test cases, only the one corresponding to no. 1; counterflow and bottlenecks have been verified).
- (Earlier model `lane`) When people jam in front of a bottleneck above 2 people/m², they squeeze in from the side and their bodies overlap (49% of frames below 0.4 m). Overlap with the person ahead moving in the same direction
  is prevented (`MIN_SEP` 0.35 m), but because the model shifts people sideways along the path, it cannot represent pushing from the side. The capacity is close to the experiments.
- (`cfsm`) Bodies overlap a little only while the safety valve lets someone through (table in 5.1). At gates, pairs are split into different lanes.
  In front of a crowded elevator, a person heading for the elevator can go into the waiting people through the safety valve and stop among them (5.4). Inside a crowd of waiting people, a little shaking in place remains (5.5).
  Pushing (forces between bodies) is not represented.
- Body heights are those of the 10 character models as-is (not fitted to the height distribution of Japanese people).
