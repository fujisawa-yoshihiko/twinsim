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
| Free walking speed (walking with nobody within 1.5 m ahead, per-person median) | Input reproduction | Mean 1.34 ± 0.08, standard deviation 0.18–0.34 |
| Group size (share of people) | Input reproduction | Difference from the input distribution (total variation distance) at most 0.08 or 1.5/√(number of people) |
| Group speed (slope against group size) | Input reproduction | −0.14 to 0 m/s per person (when there are 15 or more groups) |
| Arrivals (per stream) | Input reproduction | Difference from the specified people/min within ±2 in z |
| Outgoing share of elevator use | Input reproduction | Difference from the literature (morning 0.105, lunch 0.5) within 2 standard errors + 0.03 |
| Interval between consecutive people boarding an elevator | Input reproduction | Median 0.7–1.6 s |
| Gate time per person when crowded | Input reproduction | Median 1.5–4.0 s (10 or more times with a queue) |
| Speed by density | Emergent quantity | Ratio to the person's own speed matches the formula's v/v0 within an RMS of 0.12 at 0.5 people/m² or more (verdict only for the unidirectional corridor `verify_*`; reference only otherwise) |
| Dyad distance | Emergent quantity | Literature (colleagues 0.85 m, etc.) ± 0.15 m |
| Nearest distance between waiting people | Emergent quantity | Below 0.45 m in at most 5% |
| People stuck and unable to move | Emergent quantity | In the last 30 s, 0 people en route who moved less than 0.3 m (excluding people who went more than 2 m away and came back in that time) |
| Doorway capacity | Emergent quantity | Within ±15% of 1.90–2.19 people/(m·s) from the 1.0 m width experiment (when `validity: {bottleneck: ...}` is set) |
| Time spent waiting in elevator and gate queues | Reference only | No literature to compare with |

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
  Pushing (forces between bodies) is not represented.
- Body heights are those of the 10 character models as-is (not fitted to the height distribution of Japanese people).
