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
| Lateral spacing of dyads | Colleagues 0.72 m, friends 0.66 m, family 0.58 m (couples 0.60 m) | Zanlungo et al. 2017 | Osaka ATC, 1018 dyads | Formation slots by relation (from 1.2; `people.group_relation`, default shares colleagues 39%, friends 35%, family 27%); companion uses the family values provisionally |
| Front–back offset of dyads (mean absolute value) | Colleagues 0.33 m, friends 0.31 m, family 0.50 m | Same (reprinted in Table 4 of Zanlungo et al. 2019) | Same as above | Size of the front–back fluctuation of the slots (from 1.2; its time constant of 5 s is provisional) |
| Lateral extent of triads | Colleagues 1.10 m, friends 0.97 m, family 0.88 m | Zanlungo et al. 2019 | Osaka ATC, 687 triads | Formation slots by relation (from 1.2) |
| Group formation and density | Dyad lateral extent 0.646 − 0.538 ρ m, triad 1.096 − 1.370 ρ m (ρ in people/m², 0 to 0.3). Triads walk in a V at every density (the middle person 0.14 m behind) | Zanlungo et al. 2015 | Corridor of Osaka ATC, 3305 dyads and 602 triads; density from 0.5 m cells averaged over 300 s | Slots narrow with density (from 1.2); check |
| Dyad distance (comparison values) | Colleagues 0.85 m, friends 0.79 m, couples 0.71 m, families 0.86 m | Zanlungo et al. 2017 | Same as above | Check |
| Dyad speed (comparison values) | Colleagues 1.27, friends 1.14, couples 1.10, families 1.09 m/s; work 1.27, leisure 1.12 m/s | Zanlungo et al. 2017 | Same as above | Reference only (close to 1.34 − 0.04 = 1.30) |
| Elevator demand (number of users) | Building population × 12% ÷ 5 min (busiest 5 minutes) | Peters et al. 2011 | Current offices in Europe, North America and the UAE (observed maximum 12–13%; the old design guideline was 15%) | `demand` and `rate: {type: lift_demand}` |
| Breakdown of elevator use | Morning: incoming 85%, outgoing 10%, interfloor 5%; lunch: 45%, 45%, 10% | Peters et al. 2011 | Same as above | Incoming flow, number of people alighting |
| Elevator boarding and alighting | 1.0 s per person (the CIBSE Guide D worked example uses 1.2 s) | Peters Research default value | Design calculation | Default (`elevator.transfer_s`) |
| Gate time per person | Log-normal, median 2.0 s (1.2–4.0). Range 1.5–4.0 s, 25–40 people/min | Fruin 1987 | Card-reading turnstiles (range of observed means) | `office_commute_jp` (shape of the variability is provisional) |
| Interpersonal distance | Intimate 0–0.45 m, personal 0.45–1.2 m | Hall 1966 | Proxemics | Check (between waiting people) |
| Bottleneck capacity | 1.90–2.19 people/(m·s) at a width of 1.0 m | Seyfried et al. 2009 | Laboratory (doorway 2.8 m long, 20–60 people) | Check (`verify_bottleneck`) |
| Shape of stopping time | Log-normal | Brown et al. 2005 | Telephone call-handling times | Shape (applying it to the reception desk is by analogy) |
| Outpatient consultation time | under 5 min 28.1%, 5 to under 10 min 40.9%, 10 to under 20 min 15.0%, 20 to under 30 min 6.6%, 30 min or more 4.0% (unknown 5.4%). Approximated by a lognormal with median 421 s, σ 0.714 | MHLW 2023 Patient's Behavior Survey | Outpatients of Japanese hospitals, patients' answers | Consultation rooms of `hospital_outpatient` (from 1.2) |
| Breakdown of order-picking time | travel 50%, search 20%, pick 15%, setup 10%, other 5% | De Koster et al. 2007 (Fig. 4, after Tompkins et al. 2003) | Typical picker-to-parts warehouse (it varies by warehouse; the same paper notes cases where other activities are large) | Time at shelves in `warehouse_shift` (target share of travel within a picking tour 50 / (50 + 20 + 15) = 59%; from 1.2) |

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
| Free walking speed (walking with nobody in the 2.5 m half-circle ahead, per-person median; group members excluded) | Input reproduction | Mean and standard deviation within ± 0.05 of the speeds given to those people, and the speeds given to everyone match mean 1.34 and standard deviation 0.26 within ± 0.08 (widened to three times the sampling spread when there are few people; 5.3, 5.6) |
| Group size (share of people) | Input reproduction | Difference from the input distribution (total variation distance) at most 0.08 or 1.5/√(number of people) |
| Group speed (slope against group size) | Input reproduction | −0.14 to 0 m/s per person (when there are 15 or more groups) |
| Arrivals (per stream; people still waiting outside at the end are counted) | Input reproduction | Difference from the specified people/min within ±3 in z (variance = mean × the person-weighted mean group size; changed from 2σ to 3σ in 5.6) |
| Outgoing share of elevator use | Input reproduction | Difference from the literature (morning 0.105, lunch 0.5) within 2 standard errors + 0.03 |
| Interval between consecutive people boarding an elevator | Input reproduction | Median 0.7–1.6 s (10 or more pairs; 5.6) |
| Gate time per person when crowded | Input reproduction | Median 1.5–4.0 s (10 or more pairs of consecutive passages in a lane where the second person had already stopped in the queue before the first passed) |
| Speed by density | Emergent quantity | Ratio to the person's own speed matches the formula's v/v0 within an RMS of 0.12 at 0.5 people/m² or more (verdict only for the unidirectional corridor `verify_*`; reference only otherwise) |
| Dyad distance (excluding the time from joining a gate queue until 5 s after passing, and meeting groups before they meet) | Emergent quantity | Literature value for each relation (colleagues 0.85 m, etc.; mean weighted by samples) ± 0.15 m (3 or more dyads and 20 or more samples; 5.6, 5.8) |
| Lateral extent of groups against density (dyads and triads, where the group centre is at least 1 m from walls) | Emergent quantity | Density bins of 0.05 from 0 to 0.3 people/m²; the difference from the low-density value of the relation × (1 − k ρ) (Zanlungo et al. 2015) is within 0.1 m + 2 standard errors of the per-group mean differences (bins with 20 or more samples and 3 or more groups; density as in the literature, 0.5 m cells averaged over 300 s; 5.8) |
| Times a stranger crossed between group members | Reference only | No literature (crossings of the line joining two members while they are closer than 1.3 m. A companion who joined at a meeting point counts as a member of the same group (from 2026-11-17; before, it counted as a stranger)) |
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
  at the office entrance 0.6 m east (west is a wall). Exit-only doors keep a single line (from 5.13, an exit that is also a stream origin gets two). The portal area is centered between the two lanes. The earlier model (`lane`) keeps a single line.
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
- **People who cannot progress ask standing people to step aside:** a walker who has made no progress for 3 s or more although nobody is directly ahead asks the people standing and waiting within 0.9 m (1.2 m from 5.13) on the goal side to step sideways
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
- The arrival check is a 2σ test, so about one in 20 correct streams is flagged "caution" (changed to 3σ in 5.6; `verify_counterflow` seeds 2 and 5 have z = −2.2 and +2.6; arrivals are a Poisson process,
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

### 5.6 Checks with few samples (2026-11-12)

Three of the four "caution" verdicts in corpus v6 came from small samples, not from how people move. Only the checks were changed; movement is unchanged.

| Check | What happened in corpus v6 | Change |
|---|---|---|
| Free walking speed (speeds given) | In `A_office_ev_low` the 19 people were given speeds with mean 1.498 (literature 1.34). The standard error of a mean of 19 is 0.06, so this is within chance | Widen the ± 0.08 tolerance to three times the sampling spread (mean sd/√n, standard deviation sd/√(2(n−1))) |
| Interval between consecutive boardings | In `A_hospital_ev_low` the median of 5 pairs was 0.67 s (decided by a single boarding) | Judge from 10 pairs (as for the gate headway) |
| Dyad distance | In `A_office_gate_low` a single dyad gave 1.00 m | Judge from 3 dyads and 20 samples |
| Arrivals | (In the templates with seeds 1–16, about one in 20 correct streams was flagged "caution") | Widen the z tolerance from ±2 to ±3 |

The 129 runs of the previous comparison (5.5) were judged with the old and the new checks (the simulations were not rerun).
"Caution" disappeared in 18 runs (arrivals 8, free walking speed 5, dyads 3, consecutive boardings 2), and "pass" became "not applicable" in 7 runs (elevator 6, dyads 1).
No verdict went from "pass" to "caution".

24 "caution" verdicts remain; the most common is the dyad distance (15 runs, 1.0–2.1 m, in `office_gate_ev`, `office_ev_hall`, `hospital_gate_ev`, `verify_gate_capacity` and the corpus elevator cases).
In corpus v6 `A_office_ev_mid` (1.13 m, 20 dyads), two dyads walked side by side 2–4 m apart for about 20 s while crossing the lobby diagonally.
Groups keep together along the walking direction, but nothing controls how far apart they are sideways, and each member walks its own route. This is a change to movement and is left for the next version.

### 5.7 The step that puts people back near the line through a door jumped (2026-11-12)

The comparison of 1.0 and 1.1 (the size of each one-frame step) found steps larger than 0.2 m in one frame in the three elevator templates (205 in 48 runs, at most 1.01 m).
198 were boarding people walking to the door and 7 were people leaving through the east exit of the hospital to beyond the door.

- **Cause:** traffic to and from beyond a door (outside the walkable area) may move at most `NO_WALL_LAT_M` (0.35 m) sideways from the door line. In the hall, people may leave the line to avoid waiting people,
  but in the frame in which a point a little ahead became non-walkable (they started looking beyond the door), anyone more than 0.55 m from the line was put back 0.35 m from the line in a single frame.
- **Fix:** instead of putting them back, move them towards the line by half their own speed per frame (`NO_WALL_BACK`).

Verification ("before" has the same movement as 1.1; the three elevator templates with seeds 1–16, and the 18 elevator runs of corpus set A):

| Target | Steps larger than 0.2 m | Largest step | Stuck people | Safety valve (per run) | Overlap | People taking more than 10 s to board |
|---|---:|---:|---:|---:|---:|---:|
| `office_gate_ev` | 63 → 0 | 1.01 → 0.09 m | 0 → 0 | 0.88 → 0.81 | 0.042 → 0.021 | 62 → 58 |
| `office_ev_hall` | 81 → 0 | 1.00 → 0.08 m | 0 → 0 | 1.94 → 2.06 | 0.020 → 0.016 | 148 → 138 |
| `hospital_gate_ev` | 61 → 0 | 0.93 → 0.08 m | 0 → 0 | 3.75 → 3.75 | 0.156 → 0.163 | 59 → 58 |
| Corpus set A (elevator) | 12 → 0 | 0.79 → 0.08 m | 0 → 0 | 1.67 → 1.67 | 0.195 → 0.192 | 34 → 32 |

### 5.8 Group formation (1.2, 2026-11-12)

In 1.1, group members each planned their own route from their own position, and groups had no lateral cohesion (5.6). 1.2 adds the following (`motion_model: cfsm` only).

- **Relations and slots:** each group gets a relation (colleagues, friends, family, companion; `people.group_relation`), and each member gets a slot relative to the leader (the first member to appear).
  Dyads walk abreast at the lateral spacing of their relation, triads in a V (the middle person 0.14 m behind), groups of four or more in two rows (provisional). The lateral part of the slots
  narrows with the surrounding density (cell counts in 0.5 m cells averaged over time, as in the literature) following Zanlungo et al. 2015, and members line up where the distance between neighbours
  would fall below a body width (0.36 m) or a slot would be in a wall. The front–back offset fluctuates so that the mean absolute front–back offset of dyads matches the literature for each relation (the 5 s time constant is provisional).
  A member does not move to its slot when a stranger is standing there or when it cannot make progress; it then avoids others along its own route.
- **Joining the leader's route:** when the leader has already started the same itinerary step, a follower joins the leader's route ahead (from two different spots at a reception desk, a dyad walked 7 m apart on opposite sides of an island for 50 s).
  Standing spots are chosen only where they are in sight of the target point (a member was given a spot behind the reception desk and set off in the opposite direction).
- **Strangers do not walk between members:** strangers avoid the nearest point on the line joining two members (closer than 1.3 m) as they avoid a person.
  We also tried steering early around the outer end of such a line, but it increased the safety valve in crowded places (11 → 34 times in office_ev_hall, seeds 17–32), so it is not used.
  A widely spaced pair may still open up to let an oncoming person through (people do this too).
- **Splitting and rejoining:** at gates, members prefer the lane where a member is queuing (up to one person longer than the shortest queue), and a member who passes first waits 2 m beyond the gate (state `group_wait`, up to 30 s, provisional).
  Groups board the same elevator car; if not all fit, they wait together for the next one (a group that was skipped moves to the front for the next car). They wait up to 60 s for members who have not arrived yet.
  Elevator waiting spots are chosen next to a member's spot (within 1 m).
- **Output and checks:** the ground truth gets `groups` (members, relation, leader, intervals apart), each person's `relation` and `regroup` events (docs/formats.en.md).
  The dyad distance check compares with the literature value for each relation; a check of lateral extent against density and a count of strangers crossing between members (reference only) were added (table in section 4).
  Evaluation of a group-finding task (`twinsim/group_eval.py`, `python -m twinsim group-eval <run> <found.json>`): group-level precision, recall and F1 with the criterion of Setti et al. 2015 (T = 2/3 and 1), and F1 over pairs.

Checks (same templates and seeds as 1.1. The random sequence changes (relations are drawn), so we look at the overall trend, not run-by-run differences. Results in `~/dt-data/twinsim/crowd_check/groups1/`):

| Template | Runs | Dyads within range | Dyad distance, lateral, front–back (gstats measure) | Triad lateral | Safety valve | Overlap (< 0.3 m per 1,000 person-frames) | Shaking (per 1,000 person-seconds) | Spacing of waiting people within range |
|---|---:|---|---|---|---|---|---|---|
| `verify_groups` | 9 | 9/9 → 9/9 | 0.88, 0.77, 0.38 → 0.73, 0.60, 0.31 m (friends 0.79, 0.66, 0.31) | 1.35 → 0.90 m (friends 0.97) | 0 → 0 | 0.004 → 0.002 | 0.0 → 0.0 | — |
| `verify_gate_capacity` | 9 | 7/9 → 8/9 | 1.10, 0.70, 0.71 → 0.90, 0.47, 0.64 m | 1.20 → 0.73 m | 7 → 4 | 0 → 0 | 2.5 → 3.2 | 9/9 → 9/9 |
| `office_gate_ev` | 16 | 11/16 → 16/16 | 1.09, 0.66, 0.73 → 0.95, 0.50, 0.66 m | 1.15 → 1.30 m | 14 → 15 | 0.042 → 0.063 | 2.8 → 3.9 | 16/16 → 16/16 |
| `office_ev_hall` | 16 | 13/16 → 16/16 | — | 3.62 → 2.99 m | 31 → 24 | 0.020 → 0.062 | 4.8 → 5.8 | 16/16 → 15/16 |
| `hospital_gate_ev` | 16 | 13/16 → 16/16 | 1.00, 0.79, 0.49 → 0.77, 0.59, 0.39 m | 1.66 → 0.85 m | 60 → 56 | 0.156 → 0.212 | 5.6 → 5.5 | 16/16 → 15/16 |

- The checks without groups (`verify_bottleneck`, `verify_corridor_speed`, `verify_counterflow`, `verify_fundamental_diagram`) give exactly the same results as 1.1.
- The new check of lateral extent against density passed in `verify_groups` 8/9, `verify_gate_capacity` 6/9, `office_gate_ev` 16/16, `office_ev_hall` 14/16 and `hospital_gate_ev` 16/16.
  Pooled over all runs, the differences are within ± 0.1 m in most bins (dyads in `office_ev_hall` are 0.04–0.11 m narrower; `verify_gate_capacity` at 0.05–0.1 people/m² is 0.18 m wider).
- Shaking and overlap rose slightly, but with every group feature switched off and only the random sequence of 1.2 kept, `office_gate_ev` had shaking 4.5 and overlap 0.083 (3.9 and 0.063 with the group features).
  Most of the increase comes from the changed random sequence (and the fix in 5.7). The overlaps happen when people walking to board an elevator squeeze past members of another waiting group.
- In `verify_gate_capacity`, shaking rose around members waiting beyond the gate (2.6 without the waiting, but the safety valve then rises to 15). Moving the waiting spot to the side of the flow
  was also tried; shaking rose in some templates and fell in others, and the safety valve rose, so it is not used.
- The "caution" for the spacing of waiting people (`hospital_gate_ev` seeds 10 and 12 and others) occurs in runs with a crowded elevator hall: 5.8–6.5% below 0.45 m (threshold 5%).

### 5.9 Components that are the purpose of a trip (1.2, 2026-11-13)

Counters (`service`), calling (`call`), seating (`seats`) and rooms (`room`) were added (twinsim/components.py; geometry in section 1 of docs/spec.en.md; settings in `services` and `rooms` of docs/config-reference.en.md).
They were checked with the template `hospital_outpatient` (hospital outpatients, 30 min). The consultation time follows the outpatient consultation times of the MHLW 2023 Patient's Behavior Survey (lognormal, median 421 s, σ 0.714;
within 0.04 of the shares without "unknown" at the bin edges); the times at reception, payment and pharmacy, the arrival rate and the group shares are provisional. The waiting seats and the pharmacy counter are stand-ins.

Found during the checks and fixed ("before" is before the fix, totals over 16 runs):

| Finding | Fix | Effect |
|---|---|---|
| In a crowd, people "arrived" short of the service point and jumped up to 1.4 m to the point in one frame | Get served where they arrived; keep walking if more than 0.4 m away | Largest step 1.42 → 0.35 m (0.08 m after also fixing seats and rooms) |
| The space between a queue along the reception desk and the desk became a dead end; people who had been served could not get out | Hospital reception uses number tickets (calling), like the reception machines in Japanese hospitals. Queuing counters are left for another template | — |
| Companions waiting at one point by reception clustered and blocked the flow from the entrance | Companions wait at the waiting seats (the space's `aside` can name seats) | — |
| Routes went through rows of seated people, who could not be pushed aside, and people got stuck | Seats are furniture and removed from the walkable area (radius 0.25 m); people walk to 0.6 m in front of the seat and sit at a fixed speed (0.5 m/s) | — |
| With all seats taken, people standing to wait overlapped at one point (the 2.3 m search for a standing spot returned its centre when full) | Search walkable cells within 6 m, at least 0.6 m from others, wall side first | Overlap 1.13 → 0.44 |
| At the end of a row of seats, pushing away from seated people cancelled the pull towards the destination and people stopped | Seated people are not avoided as people (the seat walls do that) | Safety valve 308 → 178, stuck 1 → 0 |
| A companion was released twice and went on to the next step from inside a seat, stuck for 848 s | Release once; if seated or moving into the seat, first go back to the point in front of it | — |
| A companion who arrived after the leader had entered a room was not in the party and waited up to 25 min at the door | If the leader is heading into or inside the room, follow them in | — |
| The destination prefix `consult` matched both the consultation rooms and the seats (`consult_seats`), so the consultation was skipped; likewise 1.1's `reception` matched the new counter | Candidates of different kinds under one prefix are now a configuration error; places renamed `clinic_seats`, `front_desk`, `cashier` | — |
| Stepping back 1 m after service before walking on | Those stepping back overlapped the head of the queue and passers-by; overlap rose 0.50 → 1.72, so it is not used | — |

Detecting being stuck (affects every template): the safety valve was used for people whose straight-line distance to the destination had not shrunk for 15 s, but people taking a detour east from the lobby into the corridor
triggered it while walking normally (most valves in the outpatient runs). Measuring the remaining path length instead made the progress of people pushing in front of a 1 m exit fluctuate
(safety valve 107 → 223 in `verify_bottleneck`), and a person shaking in place in front of a door counted as progressing and stayed stuck for 150 s (`office_ev_hall`).
Current rule: progress if the straight-line distance shrinks, or, on a detour (remaining path at least 2 m longer than the straight-line distance), if the person moved at least 0.3 m in the last second and the remaining path shrank.

Results (16 runs of 30 min; results in `~/dt-data/twinsim/crowd_check/parts1/`):

| Quantity | Value |
|---|---|
| Safety valve | 178 (11 per run, 0.37 per minute; `hospital_gate_ev` 0.85 per minute) |
| Overlap (< 0.3 m per 1,000 person-frames) | 0.33 |
| Stuck people, largest step | 0, 0.08 m |
| Dyads within range, free walking speed within range | 15/16, 16/16 |
| Median waiting time (top 10%) | reception 95 s (298), payment 29 s (82), pharmacy 10 s (41), consultation room 21 s (401) |

Effect on templates without components (from the change in detecting being stuck; same seeds as 5.8, `~/dt-data/twinsim/crowd_check/groups1/`, parts4): the four checks without groups give the same results as 1.1.
Safety valve `office_ev_hall` 24 → 27, `hospital_gate_ev` 56 → 66, `office_gate_ev` 15 → 13, `verify_gate_capacity` 4 → 3 (results of 5.8 → now); no stuck people.

Remaining: rendering (sitting animation, chairs, room doors that are closed in the USD, hiding people inside rooms) is in 5.10. A template with a queuing counter (office lunchtime café) and warehouse work points are still to come.

### 5.10 Checking the rendering: sitting, benches, consultation-room doors and people inside rooms (1.2, 2026-11-16)

The components of 5.9 were added to the renderer, and the outpatient template (seed 1) was rendered on GPU 3 and looked at (records in `~/dt-data/twinsim/crowd_check/render12/`, README.md).

- Sitting animation: `SitAndStandChair` from NVIDIA Isaac Sim People (30 fps; approaching and turning, sitting down 109–156, seated 156–266, standing up 266–334) is retargeted to each character's skeleton, like the walking animation.
  Retargeted with `set_root_identity=False`, the whole-body forward motion and heading go to the root joint of the skeleton, so the renderer removes them there and moves the body by the person's position and heading.
  The simulator sits down and stands up along the body trajectory of the animation (forward distance and heading in the seat's frame; `components.SIT_DOWN_TRACK`, `STAND_UP_TRACK`), so the ground-truth position and the rendered body agree.
  Sitting down: animation frames 62–156 (3.1 s; the walk-in before the turn ends is shortened to start from the point 0.6 m in front of the seat, and the heading turns from the current heading to the seat's heading following the progress of the turn in the animation).
  Standing up: frames 266–332 (2.2 s, 0.42 m forward). Seated people do not look around (turning the whole body swept the legs through the neighbouring seat and armrest)
- Benches: the waiting-room bench of the hospital USD (`SM_Chair_02a`, three seats, seat height 0.43–0.48 m). The pelvis position was decided by seating characters at different depths on an empty stage (the middle of the depth;
  0.05 m further back the legs go into the seat, 0.10 m further back the body goes into the backrest). The earlier stand-in seats were in the air 0.7 m in front of the benches. A way to write furniture, `furniture`, was added to `seats` in the space, and benches not in the USD are placed by the renderer
- Doors: the door leaf of a consultation room (`door_prim`; its origin is the hinge) is turned 90 degrees towards the inside of the room only while people pass. It starts opening when a person entering reaches the point in front of the door
  (2 s before reaching the inside point) and starts closing 0.3 s after they reach the inside point. People become invisible only after the door closes (for a group, after the last member arrives). People leaving appear at the inside point and start walking after the door has opened
- People inside a room (`in_room`): the renderer places them 200 m below the floor (switching visibility is not followed by Replicator's annotations; same as park in section 5). They are left out of the rendered labels (`labels/`) and MOT as well
- Ground-truth boxes (`mot/`): for seated people, the height is the seated height and the knees and feet in front are included (previously only a cylinder at the pelvis, and the feet were outside the box). The name matching of the rendered labels (`labels.fix_names`) uses the same boxes

Found by rendering and fixed:

| Finding | Fix |
|---|---|
| The sitting animation is in cm; after retargeting, only the position of the pelvis joint stayed in cm, so the pelvis jumped to 47.9 m and no one was visible | If the seated pelvis height is over 5, divide by 100 (the positions of the other joints match the walking animation) |
| Seat points were 0.7 m in front of the benches, and people sat in the air | Seats are made on furniture (benches) with `furniture` |
| The feet of seated people were outside the ground-truth box | Use the seated height and include the knees (0.55 m) and feet 0.5 m in front |
| The door opened 3 s before, while the person was still near the bench, like an automatic door | From when they reach the point in front of the door (2 s before) |
| People vanished the moment they reached the inside point, which a camera facing the door saw happen behind the open door | They stand at the inside point until the door closes. When leaving, they appear at the inside point before the door opens |
| In a pair, the first to enter vanished behind the door held open for the second (members were looked up in the party called to the room, which did not include a member following the leader in later) | People of the same group entering the same room are members, and everyone stands until the door closes after the last member arrives |
| Because the first person stands at the inside point, the second could not reach the same point and waited inside the doorway for up to 30 s | Members go to points 0.6 m to the side of the inside point. People standing inside and waiting for the door are, like seated people, not avoided by others (members now enter within 1.6 s of each other) |
| A person being served at the reception kept giving way to passers-by, drifted 1.25 m from the desk and was served there (CamGate; in 16 runs, 4.1% of services drifted more than 0.9 m, at most 1.91 m) | Not fixed here (fixed in 5.11 by making passers-by route away from the front of counters). If people being served do not give way, the safety valve rose 168 → 368 and overlaps 0.28 → 1.03; limiting it to 0.4 m gave a safety valve of 330 and 1 stuck person. The service points are near a walking route, and people being served keep the flow going by giving way. The next step is to make passers-by route away from the front of the reception |
| With seats reduced to the 12 of the USD benches (14 stand-in seats before), standing waiters increased 1.7 times, and the safety valve and overlaps around the island increased (178 → 222, 0.23 → 0.49) | The same benches were added by the renderer along the west wall and south window of the lobby and in front of the consultation rooms (18 seats in the lobby, 9 in front of the consultation rooms) |

Results (16 runs of 30 minutes; before = the result of 5.9; final7 → render5 in `~/dt-data/twinsim/crowd_check/parts1/`):

| Measure | Before | Now |
|---|---|---|
| Safety valve | 178 | 168 |
| Overlaps (under 0.3 m, per 1,000 person-frames, on walkable cells) | 0.23 | 0.28 |
| Stuck people, largest step | 0, 0.08 m | 0, 0.07 m |
| Pairs that agree, free walking speed that agrees | 15/16, 16/16 | 15/16, 16/16 |

Counting positions outside the walkable area too (seats, inside rooms), overlaps fell from 0.31 to 0.28, but on walkable cells they rose from 0.23 to 0.28. People being served drifting from the reception desk was fixed in 5.11. Most are between companions standing and waiting around the bench added at the south window of the lobby and people passing (remaining).
The benches added to the hospital space are also rendered, and removed from the walkable area, in templates that do not use components (such as `hospital_gate_ev`).
In the check with `hospital_gate_ev` made 2.5 times busier (tests/test_benchmark_gt.py), a pair of people standing and waiting for the elevator closer than 0.3 m appeared in one of seeds 1–8 both in the components version and now (seed 1 then, seed 4 now).

### 5.11 Routes avoiding the front of counters, office lunchtime (coffee counter), and folds when members join the leader's route (1.2, 2026-11-16)

- Routes avoiding the front of counters: routes of people going elsewhere avoid, where they can, a circle of 0.8 m around the service points of the counters listed in `services` of the configuration
  (4 m is added to the route weight per metre, and line-of-sight thinning does not cross it; it does not apply to people going to or leaving that counter; `Space.set_soft`). This fixes the remaining issue of 5.10,
  "people being served at the reception keep giving way to passers-by and drift from the desk". Not giving way, or giving way only up to 0.4 m, was not adopted because passers-by pushed through in front of the reception and the safety valve doubled
- Office lunchtime template `office_lunch` (30 minutes): people going out for and returning from lunch pass the gate and elevators; some queue at a coffee counter along the east wall of the lobby (a stand-in: the same asset as the
  reception desk of the USD, placed by the renderer), then take it upstairs or rest on the sofas of the USD (15 seats) before going up. The elevator mix is from the literature (Peters et al. 2011, lunchtime); the rest is provisional
  (ledger in section 6). It is the first template using a queuing counter (`line`)
- Furniture: a sofa `sofa3` (three seats, front +x) and a counter `counter2` (no seats) were added, and `furniture` can now be written on counters too. The pelvis depth on the sofa was decided by seating characters
  at different depths on an empty stage (+0.10 m; at 0 m or less the shins go into the front edge of the seat, at +0.20 m they perch on the front edge). The three sofas around the southern coffee table are not used,
  because the points where people stand before sitting are outside the walkable area (0.5 m grid)
- Folds when members join the leader's route (applies to every template with groups): a member joining the leader's route joined at the point 1 m ahead of the leader. When that point was behind the member,
  the route went back 0.4 m and then turned around, the target direction switched every frame, and the person shook in place (in `office_lunch` seed 11, a visitor stayed 20 minutes east of the reception; the route kept being rebuilt,
  so the safety valve did not act either). Members now join at the point of the leader's route, from 1 m ahead of the leader onwards, that is nearest to them, and short folds in the joined route are removed

Results (16 runs):

| Template | Measure | Before | Now |
|---|---|---|---|
| `hospital_outpatient` (render5 of 5.10 → final8) | Safety valve, overlaps (on walkable cells), shaking | 168, 0.28, 0.5 | 98, 0.16, 0.3 |
| | Share of services where the person drifted more than 0.9 m from the service point, top-10% drift | 4.1%, 0.71 m | 2.2%, 0.20 m |
| | Stuck people, pairs, free walking speed | 0, 15/16, 16/16 | 0, 15/16, 16/16 |
| `office_lunch` (before the join fix lunch1 → now lunch2) | Safety valve, overlaps, shaking | 249, 0.17, 6.6 | 156, 0.16, 3.7 |
| | Stuck people, spacing of waiting people, pairs, free walking speed | 1, 16/16, 16/16, 16/16 | 0, 16/16, 16/16, 16/16 |

The café of `office_lunch` (total of 16 runs): 48 people buy per run; queuing time median 47 s, top 10% 198 s; people sat on the sofas 14 times per run. The queue was at most 2 to 14 people
(the queue line holds 11; beyond that it extends in the direction of the end of the line). 40 seconds were rendered with CamCafe to look at the counter, queue and seated people (`~/dt-data/twinsim/crowd_check/lunch1_render/`).
The counter has no staff and no coffee machine, so it can look like people queuing at a reception desk (remaining).

Effect of the join fix on the existing templates (same seeds as 5.8; parts4 → fold1 in `~/dt-data/twinsim/crowd_check/groups1/`; parts4 is the version of 5.9): safety valve `office_gate_ev` 13 → 15,
`office_ev_hall` 27 → 22, `hospital_gate_ev` 66 → 61, `verify_gate_capacity` 3 → 1; overlaps and shaking are the same or lower everywhere; the verdicts for pairs and spacing of waiting people are unchanged;
strangers passing between members in `verify_gate_capacity` 5 → 0. `verify_groups` gives the same results.

### 5.12 Warehouse shift start (work points with a capacity and a queue) and the state while walking to a queue (1.2, 2026-11-16)

- Work points: the counter component (5.9) gained the name of the state while being served (`services.<counter>.state` in the configuration), so a place where people stand
  and work and that has a capacity and a queue (the warehouse packing tables) can be written as a counter. There are four packing tables (the NVIDIA Isaac Sim asset
  `PackingTable`, placed by the renderer; furniture `pack_table`); people waiting for a free one queue on a line running north from the middle of the row
  (with a waiting area (`area`), the rule that prefers places by walls made them stand right beside other tables). The state while packing is `work`
- Round order: destinations gained `visits`. It chooses n places among the candidates for the start of a name (`pick_1` to `12`) and goes round them in the order of the number
  in the name (the numbers of the places in the space give the round order). If someone is already at a shelf, the existing rule for stops makes the next person stand at a
  free place nearby (the shelves have no capacity)
- Template `warehouse_shift` (20 min): workers come from the dock (`dock`), queue at the time clock (on the south wall; notional, nothing is placed by the renderer), wait for
  instructions at the waiting place, go round 6 to 8 shelves and then pack at a packing table, repeatedly. 20% of early arrivals wait on the break benches (two benches of the
  same asset as the hospital benches, by the west wall) before clocking in. The number of workers and the times for clocking in, waiting for instructions and packing are
  provisional (ledger in section 6)
- The stop time at shelves was set to match the breakdown of order-picking time (table in section 2; Fig. 4 of De Koster et al. 2007). The target share of travel within a
  picking tour (from the end of waiting for instructions or of packing until heading to the next packing queue), travel / (travel + at shelves), is 59%. With a median of
  12 s at shelves it was 52% (1 run); with 9 s, 56.7% (16 runs)
- State while walking to a queue (affects counters with a queue line: the café in `office_lunch` and the warehouse): people heading for the queue line had the state
  `service_queue` all the way, even while walking from far away (in the warehouse, people walking 10 to 20 m from a shelf were "queuing"). While more than 1.5 m from their place
  in the queue they are now `pass`. Movement is unchanged (16 runs of `office_lunch`: safety valve, overlap, shaking and verdicts are the same as lunch2). The `service_queue`
  time in `office_lunch` went from 968 to 815 minutes (sum of 16 runs; 16% was walking to the queue)
- Dwells (`3_dwell` in `tasks.json`): it listed the stop states, so names given by `state` of a destination (the warehouse `work` and `wait`) were missing. It is now every state
  except the walking ones (`pass`, `alight`, `ev_approach`) and inside a room (changes `tasks.json` of `warehouse_picking`)
- Rendering: assets differ in the units of their stage (m or cm; the packing table asset has a cm stage with values in m). When the renderer places furniture, it rescales it if
  the loaded width differs from the furniture box (`box` in `FURNITURE`) by more than 20%

Results (16 runs, w2 in `~/dt-data/twinsim/crowd_check/warehouse1/`; summarised with `scripts/wh_stats.py`):

| Measure | Value |
|---|---|
| People | 21 per run (2 per minute in the 8 minutes before the start, then 0.3 per minute) |
| Share of time | walking 49%, at shelves 28%, packing 11%, waiting for instructions 6%, seated 3%, queuing 2%, clocking in 0.5% |
| Travel within picking tours | 56.7% (target 59%) |
| Time clock (queue line) | 21 per run. Time waiting in the queue median 0 s, top 10% 1 s, max 14 s; longest queue 0 to 3 people |
| Packing tables (four, queue line) | 63 per run. Time waiting in the queue median 0 s, top 10% 23 s, max 88 s; longest queue 0 to 10 people |
| Break benches | 3.4 people sat per run |
| Safety valve, overlap (on walkable cells), shaking, people stuck, largest step, free walking speed | 48 (sum of 16 runs), 0.031, 2.3, 0, 0.06 m, 16/16 |

Rendering (GPU 3, seed 1: CamDock 30 s, CamPack 30 s, CamAisles 20 s; videos with the ground-truth boxes in `~/dt-data/twinsim/crowd_check/warehouse1/review/`):
the packing tables were loaded at the asset's own size (the rescaling did not trigger; it stays for other assets). Workers stand on the north side of the tables facing south,
and people waiting for a free table queue northwards from between tables 2 and 3. The benches stand on the floor between the pillars of the west wall, and the ground-truth
boxes of sitting down and of seated people match the rendered bodies. The time clock is a notional place on the south wall: people stand in front of the wall to clock in, and
one person queued behind. CamDock showed mostly empty floor and wall with small people, so it was moved closer and re-aimed (eye (-7, -14, 4.0), target (-19.5, -19.5, 0);
a person at the time clock grows from about 75 to 100 pixels). CamAisles (an existing camera) has many people hidden behind shelves (the visible share is in MOT and `labels/`).

### 5.13 Remaining movement fixes from 1.1: the boarding tail at elevators, shaking among waiting people, and the south exit (1.2, 2026-11-16 to 17)

The three items left over from 1.1 (5.3–5.5) were investigated and fixed. The previous version (ad76383) was run 153 times (6 `verify_*` × seeds 0–8, the 3 elevator-lobby templates × seeds 1–16,
the 27 runs of the corpus set A, and the 3 templates of 1.2 × seeds 1–8), and the positions where the safety valve was used, the time boarding people stood still and the states of people who shook were counted before fixing.

- **Blocking at the south exit:** counting where the safety valve was used in the gate settings of corpus set A, most were beyond the door of the office south exit (y = −17 to −21, out of camera view).
  The south exit is an exit (`kind: exit`), so the walk to and from beyond its door kept a single line (5.2), but the corpus settings and the templates (`office_gate_ev`, `office_lunch`) also make people appear there.
  People appearing and people disappearing faced each other on the same line (the one stuck person in `A_office_gate_mid` seed 3 was also here). An exit that is also a stream origin (`origin`) now gets
  two lines for people entering and leaving (people leaving 0.6 m to the east)
- **Boarding tail (cause):** of the time of people who took more than 10 s to board, 27–37% was standing still while an alighting person of that car was within 1 m of the door (waiting in front of the door),
  17–36% standing still otherwise, and 18–24% walking slowly. When they started to walk, two or more waiting people who were not boarding stood between them and the door (within 0.6 m of the line to the door)
  for 29–43% of the slow people and 9–10% of the others. Waiting people who did not board kept standing on the way to the door, and boarding people went through them. Alighting people also stopped in balance with
  people standing 1 m ahead (the pull towards the goal and the push away cancelled, and the rule of 5.5 slowed them), and boarding people waited in front of the door meanwhile (one boarding person stood 1.9 m from the door for 68 s).
  Standing people only gave way when a walker had made no progress for 3 s and asked people within 0.9 m ahead; people at 1.0–1.1 m were not asked (the push is 0.62 at 1.0 m, and two people cancel the pull of 1 towards the goal)
- **Fixes (boarding tail):**
  1. People standing and waiting on the way to the door (1.5 m ahead, 0.5 m sideways) of a boarding person, or of an alighting person within 4 m of the door, step aside before being asked (`CLEAR_AHEAD_M`, `CLEAR_W_M`, `CLEAR_DOOR_M`)
  2. The distance within which people who cannot progress ask standing people to step aside: 0.9 → 1.2 m (`NUDGE_ASK_M`)
- **Shaking (causes and fixes):** people who shook were walking to their waiting spot (`ev_approach`), standing and waiting or boarding (`ev_wait`), or passing (`pass`). Going through the longest cases frame by frame:
  - A person boarding the hospital elevator from beside the door (beside the box of the car) headed straight for the door, towards the corner of the box, balanced with the push from the wall and shook for 13 s.
    People boarding from beside the door (less than 0.5 m out in front of it) now go through a point 0.6 m in front of the door first (`BOARD_FRONT_M`)
  - A person who had stepped aside went back while the person who asked was still stopped 1.0–1.2 m away (they go back once walkers are more than 0.9 m away), was asked again, and stepped aside and back for 20 s.
    They do not go back while the person who asked is still walking within the asking distance
- **Spacing after stepping aside:** with fix 2 more people stepped aside, and in 2 runs in front of the hospital elevator the share of waiting people closer than 0.45 m rose 5 → 18%. Someone else stood where the person who had
  stepped aside would go back, every step back brought them into body contact (70 s), and the rule to move apart from neighbors (5.4) did not apply to people with a spot to go back to. Now they do not go back if someone stands there,
  and people who have not gone back also move apart from neighbors (not further than now from where they stood)
- Tried and not used: an asking distance of 1.0 m (small effect), stepping aside only once for the same person (the one case of shaking went away, but the same pattern appeared elsewhere and total shaking was unchanged,
  and people taking more than 10 s to board increased a little)

Check ("before" is ad76383; records in `~/dt-data/twinsim/crowd_check/rest1/`, base and c5. Shaking per 1,000 person-seconds, overlap per 1,000 person-frames, safety valve per run):

| Target | People taking more than 10 s to board | Boarding (top 10%, longest) | Safety valve | Overlap | Shaking | Waiting people below 0.45 m (runs that pass) |
|---|---|---|---:|---:|---:|---|
| `office_gate_ev` (16 runs) | 49 / 748 → 10 / 740 | 8.6, 34.4 → 6.6, 13.8 s | 0.94 → 0.38 | 0.065 → 0 | 3.8 → 3.5 | 0.3% → 0.5% (16 → 16) |
| `office_ev_hall` (16 runs) | 154 / 857 → 63 / 854 | 16.2, 75.3 → 9.1, 33.4 | 1.38 → 0.50 | 0.049 → 0.007 | 4.3 → 4.0 | 1.1% → 0.5% (15 → 16) |
| `hospital_gate_ev` (16 runs) | 67 / 532 → 11 / 565 | 12.7, 41.4 → 5.6, 26.9 | 3.81 → 0.31 | 0.156 → 0 | 5.2 → 3.9 | 1.4% → 0.9% (15 → 15) |
| Corpus set A, office elevator lobby (9 runs) | 30 / 112 → 25 / 127 | 18.7, 40.1 → 12.3, 20.0 | 2.00 → 0.67 | 0.050 → 0.002 | 6.0 → 5.9 | 3.3% → 1.5% (7 → 9) |
| Corpus set A, hospital elevator lobby (9 runs) | 4 / 79 → 2 / 79 | 7.4, 25.7 → 5.1, 11.8 | 2.33 → 0.22 | 0.074 → 0 | 7.7 → 5.1 | 1.6% → 1.9% (8 → 8) |
| Corpus set A, gates (9 runs) | | | 4.22 → 0.78 | 0 → 0 | 7.1 → 6.2 | stuck people 1 → 0, pairs that pass 4 → 5 / 5 |
| `office_lunch` (8 runs) | | | 8.25 → 1.00 | 0.095 → 0.003 | 3.5 → 2.4 | 0.3% → 0.2% (8 → 8) |
| `hospital_outpatient`, `warehouse_shift` (8 runs each) | | | 1.25 → 1.12, 3.12 → 2.62 | 0.025 → 0.018, 0.033 → 0.011 | 0.3 → 0.2, 1.9 → 2.7 | |

The 6 `verify_*` are the same except a small shift in the breakdown of shaking in `verify_gate_capacity` (no elevators, no people appearing at exits, no standing people to ask).
The longest time an alighting person stayed within 1 m of the door went 20.0 → 9.5 s (`office_ev_hall`) and 17.1 → 3.3 s (`hospital_gate_ev`). The boarding interval, pairs, free walking speed and arrivals
still pass in every template (boarding interval 0.91–0.96 s in the 3 elevator-lobby templates). No stuck people. 5 tests were added (all fail on the previous version), and the test of the two door lines now also covers exits.

Remaining:
- People taking more than 10 s to board remain at 7% in `office_ev_hall` and 20% in the office runs of corpus set A. 70% of their time is walking slowly through the crowd, and some still stop in balance inside a ring of
  standing people 1.0–1.4 m away (the safety valve after 15 s)
- Shaking is 2–6 per 1,000 person-seconds and did not drop much (people walking to their waiting spot and people passing through crowds; the two repeating patterns above were fixed). `warehouse_shift` 1.9 → 2.7
  (people working at shelves now step aside)
- The car a late boarding person gets into may already have left (car departure times are not modeled; the elevator doors stay open in the rendering)

### 5.14 Remaining rendering fixes: overlaps at seat fronts and room points, staff and a machine at the cafe (1.2, 2026-11-18)

The three rendering items among the known limitations in the 1.2 release notes (overlaps around benches, no staff or machine at the cafe counter, the rendered annotation boxes of seated people) were fixed and checked.
Simulation records are in `~/dt-data/twinsim/crowd_check/render13/` (README.md); the 16-run comparison is v1.2 → v1.2b in `~/dt-data/twinsim/crowd_check/release_1.2/`.

- **Where the overlaps were:** in 16 outpatient runs, of 1,608 pair-frames with centres under 0.3 m (excluding mates, all positions in `frames.csv`), 1,057 were at the inside point of "other clinics" (`other_clinics`).
  People leaving a room appear there and wait for the door to open (5.10). With a capacity of 100 and many people coming and going, people coming out and going in, or two coming out, stood on the same point. It is outside the walkable area, so the previous overlap measure (on the walkable area) did not count it.
  499 were people standing and waiting within 0.5 m of a seat front point (where people walk in to sit) with people sitting down, standing up and leaving, or passing. They came from the fallback `alloc_stand` when the standing-spot search was full at busy times, and from people pushed in front of seats while making way.
- **Fix (room points):** a person going in takes the inside point or one of up to two points 0.6 m to each side that is 0.5 m from visible people and from points others are heading for (`ROOM_POINT_CLEAR_M`, `ROOM_SIDE_SLOTS`).
  A person coming out waits inside while someone is within 0.5 m of their point or someone is walking in from the door to the same room (up to 30 s, `ROOM_EXIT_WAIT_S`). The `exit` of `room` in `events` is now the time they actually came out (the rendered door opens then)
- **Fix (seat fronts):** standing spots keep 0.5 m from seat front points (`free_spot`, `alloc_stand`, `STAND_SEAT_CLEAR_M`). If nothing is free within 6 m at busy times, the search widens to 12 m.
  A person pushed in front of seats while making way moves away at 0.2 m/s in the direction of the sum of the directions away from all nearby seat front points (away from only the nearest point, they went back and forth between two neighbouring points in front of a row and could not get out)
- **Tried and not used:** stopping making-way steps from entering seat fronts (unable to make way, a passer-by and a stander stood 0.16 m apart for 120 s; seed 12). Also waiting until the straight path into and out of a room is clear (people waiting at the door and people coming out collided; in a test room overlaps rose from 24 to 231 pair-frames)
- **Cafe:** the counter, the same asset as the reception desk in the USD, is a 1.12 m high ledge only on the customer side (0.35 m deep) and a 0.75 m desk on the staff side (measured from the asset's points). The counter was moved 0.8 m away from the wall,
  with two staff behind it (streams `cafe_staff_1` and `_2`, one each appearing at time 0 and staying in state `work` to the end, type `clerk`), a drinks machine between it and the pillar to the north (`SM_DrinksMachine`, 1.2 m wide, 1.83 m high),
  and two takeaway coffees and a cup on the ledge (furniture now has a height above the floor, `z`; items with a height do not block the floor). The customer points, queue and waiting point for mates moved 0.5 m west too.
  The tracks of the office templates that do not use the cafe are unchanged (nobody walks near the counter)
- **Judgements:** with a stream of fixed group size (`group_size: 1` of the staff), the group-size judgement was skipped (not zero-truncated Poisson). A fixed size now enters the expected shares

Results (16 runs each; before is v1.2 in `release_1.2/`, now is v1.2b; the other templates have the same tracks):

| Template | Measure | Before | Now |
|---|---|---|---|
| `hospital_outpatient` | Overlaps (pair-frames, total over 16 runs, excluding mates, all positions) | 1,608 (other clinics' inside point 1,057, standers at seat fronts 499) | 798 (0, 73) |
| | Overlaps on the walkable area (per 1,000 person-frames, mean per run) | 0.041 | 0.071 (excluding seed 12, 0.025 → 0.003) |
| | Safety valve (per run), shaking, stuck people, largest step | 1.94, 0.3, 0, 0.07 m | 1.88, 0.2, 0, 0.07 m |
| | Free walking speed, group size, dyads, lateral spread | 16/16, 16/16, 16/16, 16/16 | 16/16, 16/16, 15/16, 15/16 |
| `office_lunch` | Safety valve, overlaps on the walkable area, shaking | 1.25, 0.003, 2.5 | 0.94, 0.000, 2.3 |
| | Taking over 10 s to board, mean travel time (excluding staff) | 1.0%, 74.7 s | 1.4%, 71.2 s |
| | Judgements (speed, group size, dyads, standing spacing, arrivals / lateral spread / gate headway) | 16/16 / 14/16 / 2/2 | 16/16 / 16/16 / 1/1 |

Remaining: in seed 12 of the outpatients, a passer-by got stuck for 18 s beside a person standing and waiting to be called, and most of the overlap on the walkable area is this one case (resolved by the safety valve; the same pattern as the remainder in 5.13).
Seed 12 is a busy run whose results swing widely: 0.29 in the previous version, 0.27 with the move-away rule turned off (21 safety-valve uses) and 1.09 now (8 uses).
In the same seed 12, from 1,470 to 1,545 s while the waiting area was crowded, the companions of two called patients took long to get through people standing and waiting to be called (40 s for 3 m).
They entered the consultation room up to 18 s after their patients, and the mean dyad distance went from 0.83 to 1.12 m, making the judgement a caution.
Over all 16 runs, the time from being called to entering a room (mean 27.6 s, 90th percentile 38.8 s), the delay of companions (mean 0.4 s) and the number of people in that area (about 25) are the same as before.
We take it as one case caused by small differences in where people stand. The lateral spread at 15/16 is the density bin 0.10–0.15 people/m² of seed 10 (29 points), where the difference of −0.176 m is just over the tolerance of 0.172 m.

Rendering (one GPU): with the current version, `CamCafe` from 772 to 802 s of office lunchtime (seed 1) and `CamWaiting` from 1,751 to 1,781 s of the outpatients (seed 1, with the rendered annotations `labels/`) were rendered (records in `review/` of render13).

- **Cafe:** the two staff stand behind the counter and have ground-truth boxes (full-body boxes including the legs hidden by the counter). The takeaway coffees and the cup sit on the high ledge.
  The drinks machine is outside the view of `CamCafe` (at the north end), so 10 frames were rendered with two trial cameras to check that its front (the display and buttons) faces the lobby (west) (`rot: 180`)
- **Rendered annotations of seated people:** the IoU of the full-body box (including hidden parts) with the simulation box (`mot/`) while seated (5,452 rows) has a median of 0.72, a 10th percentile of 0.62 and none under 0.5 (walking people: median 0.65).
  During the sitting-down motion (655 rows), 95 rows are under 0.5: the rendered annotation encloses the body bending forward, but the simulation box only changes its height with the pelvis and does not follow the upper body bending forward
- **Around benches:** no visible overlaps in the 30 rendered seconds. This seed had no overlaps at seat fronts in the previous version either, so the difference before and after is seen in the numbers above
- **The Isaac Sim receiver:** it exits after a job that outputs rendered annotations (a second annotation in the same Isaac Sim comes out empty or wrong; since 2026-11-03). `tools/render_farm.sh` restarts it automatically, but
  one started with `./isaac_up.sh` is not restarted, so start it again to render more (written in [operations.en.md](operations.en.md))

## 6. Values without literature (provisional) and how to calibrate them with real data

| Value | Current | How to calibrate |
|---|---|---|
| Building population | 600 people (provisional) | The building's population (entry logs). Elevator demand is proportional to it |
| Split of the incoming flow (visitors 7%, meeting someone 3%) | Provisional | Reception logs; manual labels on short segments of real video |
| Ground-floor (1F) flows that do not use the elevators, pass-through | Provisional | Difference between the gate passage logs and the number of people boarding elevators |
| Destination shares, stopping time at reception | Provisional (the shape of the stopping time is log-normal) | Real video; flow estimation |
| Elevator arrival interval, time until the doors open | Provisional | Elevator operation logs |
| Variability of gate time per person | Range from the literature, shape provisional | Time intervals in the gate passage logs |
| Service times at counters (reception, payment, pharmacy), default time in rooms, time in other departments | Provisional (1.2; lognormal shape) | Ticketing and calling logs of the counters, hand labels on video |
| Outpatient arrival rate, group shares and relations, destination shares | Provisional (1.2) | Reception records, real video |
| Office lunchtime share of the busiest 5 minutes (11%), share stopping at the café, café service time (median 50 s), time on the sofas (median 10 min) | Provisional (1.2, `office_lunch`; only the elevator mix is from the literature) | Elevator logs, till records, real video |
| Warehouse: number of workers, time to clock in (median 4 s), time waiting for instructions (20 to 90 s), packing time (median 30 s), shelves per tour (6 to 8), share waiting on the benches (20%) and how long (median 150 s), walking speed (1.3 m/s) | Provisional (1.2, `warehouse_shift`; only the time at shelves follows the breakdown in the literature) | Time-clock records, warehouse management records (start and end times of picks), real video |
| Companion formation (family values reused), formation of four or more, time constant of the front–back fluctuation, longest wait beyond gates | Provisional (1.2) | Trajectories of pairs and triads in real video |
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
  In front of a crowded elevator, a person heading for the elevator can go into the waiting people through the safety valve and stop among them (5.4). Inside a crowd of waiting people, a little shaking in place remains (5.5). Group formation was added in 1.2 (5.8). A widely spaced pair may open up to let an oncoming person through. The formation of groups of four or more, the waiting time beyond gates and the time constant of the front–back fluctuation have no literature values and are provisional.
  Pushing (forces between bodies) is not represented.
- Body heights are those of the 10 character models as-is (not fitted to the height distribution of Japanese people).
