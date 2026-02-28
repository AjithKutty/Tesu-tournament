# Scheduling Algorithm: Probability-Based Player Filtering

## Problem

In elimination brackets parsed from pre-tournament data (Excel), later-round matches contain placeholder players ("Winner R1-M1", "Winner QF-M2") instead of actual names. The scheduler needs to enforce player rest between rounds, but it doesn't know which players will advance.

Without any handling, placeholder matches bypass rest enforcement entirely — resulting in QF/SF/Finals being packed greedily into the earliest available court slot without realistic spacing.

## Solution Overview

1. **Resolve possible players**: Trace back through the bracket to find all players who *could* reach each match (already implemented in `_resolve_known_players()`)
2. **Compute advancement probability**: For each possible player in each match, compute the probability they actually reach that match
3. **Normalize per round**: Divide probabilities by the expected base probability for that round depth, so a single threshold works consistently across all rounds
4. **Filter by threshold**: Only enforce rest for players whose normalized probability meets the threshold
5. **Schedule with filtered players**: Use the filtered "effective players" set for rest **checking**, but only update the player tracker for real-player matches

### Check vs Update Asymmetry

A key design decision: placeholder matches **check** `effective_players` against the player tracker (to respect rest from earlier real-player matches) but do **not update** the tracker. This avoids over-constraining cross-division schedules — updating the tracker for a Final with 12 possible players would block all 12 across all their other divisions, when in reality only 2 will play.

Within a division, proper round spacing is enforced by **prerequisite constraints** (a QF cannot start until its R1 feeders finish + rest). Cross-division rest is enforced for confirmed matches (R1, pools) via the player tracker. Later-round cross-division conflicts are inherently speculative and are not enforced for placeholder matches.

## Probability Computation

### Raw Probability

Each player's raw probability of reaching a match is the product of their win probabilities through each round:

```
P(player reaches match) = P(win R1) × P(win QF) × P(win SF) × ...
```

**Default mode (50/50):**
Every match is a coin flip. Raw probability at round depth `d`:

```
P_raw = 0.5^d
```

| Round | Depth | Raw Probability |
|-------|-------|-----------------|
| Round 1 | 0 | 1.0 (100%) |
| Quarter-Final | 1 | 0.5 (50%) |
| Semi-Final | 2 | 0.25 (25%) |
| Final | 3 | 0.125 (12.5%) |

**Seeding mode:**
Win probability depends on seed matchups. A seed-1 player vs unseeded might have 75% win chance:

```
P_raw(seed1 at QF) = 0.75  (beat unseeded in R1)
P_raw(seed1 at SF) = 0.75 × 0.65 = 0.4875  (then beat seed 3/4 in QF)
```

### Normalization

Raw probabilities decrease with round depth, making a single threshold unusable across rounds. We normalize by dividing by the **expected base probability** for that depth:

```
P_normalized = min(P_raw / 0.5^depth, 1.0)
```

The base is always `0.5^depth` regardless of whether seeding is used — this represents the "expected" probability in a fair tournament.

**With 50/50 defaults:**

| Round | Depth | Raw | Base (0.5^d) | Normalized |
|-------|-------|-----|--------------|------------|
| R1 | 0 | 1.0 | 1.0 | 1.0 (100%) |
| QF | 1 | 0.5 | 0.5 | 1.0 (100%) |
| SF | 2 | 0.25 | 0.25 | 1.0 (100%) |
| Final | 3 | 0.125 | 0.125 | 1.0 (100%) |

All players normalize to 100% — everyone is included. This is the conservative default.

**With seeding (example: seed 1 vs unseeded):**

| Round | Raw (Seed 1) | Normalized (Seed 1) | Raw (Unseeded) | Normalized (Unseeded) |
|-------|-------------|---------------------|----------------|----------------------|
| QF (d=1) | 0.75 | min(0.75/0.5, 1.0) = **1.0** | 0.25 | 0.25/0.5 = **0.50** |
| SF (d=2) | 0.4875 | min(0.4875/0.25, 1.0) = **1.0** | 0.0625 | 0.0625/0.25 = **0.25** |
| Final (d=3) | 0.317 | min(0.317/0.125, 1.0) = **1.0** | 0.0156 | 0.0156/0.125 = **0.125** |

With a threshold of 0.5: seed 1 is always included, while the unseeded player is excluded from SF onwards. This means the scheduler won't hold rest slots for an unlikely finalist.

### Important Note on Normalization

Normalization is **only used for the threshold check** to decide whether a player is included in the effective players set. The actual probability propagation through rounds always uses un-normalized raw probabilities:

```
P_raw(player at SF) = P_raw(player at QF) × P(win QF match)
```

Never use normalized probabilities for propagation — they would distort the cumulative calculation.

## Threshold Behavior

| Threshold | Effect |
|-----------|--------|
| 0.0 (default) | Include all possible players → conservative, maximum rest enforcement |
| 0.5 | Include players with above-average advancement probability |
| 1.0 | Only include guaranteed players (real-player matches only) — equivalent to old behavior |

## Configuration File

Optional JSON file passed via `--schedule-config`:

```json
{
  "default_threshold": 0.0,
  "use_seeding": false,
  "seeding_probabilities": {
    "1_vs_unseeded": 0.75,
    "2_vs_unseeded": 0.70,
    "3/4_vs_unseeded": 0.65,
    "seed_vs_seed": 0.55,
    "default": 0.50
  },
  "divisions": {
    "MS A": { "threshold": 0.5 },
    "MS B": { "threshold": 0.3 }
  }
}
```

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_threshold` | float | 0.0 | Probability threshold applied to all divisions unless overridden |
| `use_seeding` | bool | false | Use seed info from division JSON to compute win probabilities |
| `seeding_probabilities` | object | (all 0.5) | Win probability lookup by seed matchup. Only used when `use_seeding=true` |
| `divisions` | object | {} | Per-division overrides keyed by division code (e.g., "MS A") |

### Per-Division Configuration

Each entry in `divisions` can override:
- `threshold`: Override the default threshold for this division

This allows different divisions to have different scheduling aggressiveness. For example, a top-level division like "MS A" with clear seeding could use a higher threshold to reduce unnecessary rest blocking, while a junior division might keep the conservative default.

### Seeding Probability Lookup

When `use_seeding=true`, the scheduler determines win probability for each match by comparing the two players' seeds:

| Key | Description | Example |
|-----|-------------|---------|
| `1_vs_unseeded` | Seed 1 against an unseeded player | 0.75 |
| `2_vs_unseeded` | Seed 2 against an unseeded player | 0.70 |
| `3/4_vs_unseeded` | Seed 3/4 against an unseeded player | 0.65 |
| `seed_vs_seed` | Any seeded player vs another seeded player | 0.55 |
| `default` | Fallback for any unmatched pair | 0.50 |

The higher-seeded player gets the configured probability; the opponent gets `1 - probability`.

## Concrete Example: 16-Draw MS A Bracket

```
R1-M1: [1] Luka Penttinen vs Bye → Luka auto-advances
R1-M2: Janne Haurinen vs Eetu Hanhineva
R1-M3: [3/4] Elias Vuollet vs Bye → Elias auto-advances
R1-M4: Tommi Salonpää vs Iiro Romppainen
R1-M5: Miikka Pylväs vs Ilari Leskelä
R1-M6: Bye vs [3/4] Marko Koivusaari → Marko auto-advances
R1-M7: Heikki Roivainen vs Joel Pennanen
R1-M8: Bye vs [2] Anton Ketola → Anton auto-advances

QF-M1: Luka (auto) vs Winner R1-M2
QF-M2: Elias (auto) vs Winner R1-M4
QF-M3: Winner R1-M5 vs Marko (auto)
QF-M4: Winner R1-M7 vs Anton (auto)

SF-M1: Winner QF-M1 vs Winner QF-M2
SF-M2: Winner QF-M3 vs Winner QF-M4

Final: Winner SF-M1 vs Winner SF-M2
```

**With default 50/50 and threshold 0.0:**
- QF-M1 effective players: {Luka, Janne, Eetu} — all at normalized 100%
- SF-M1 effective players: {Luka, Janne, Eetu, Elias, Tommi, Iiro} — all at normalized 100%
- Final effective players: all 12 participants — all at normalized 100%
- Result: The Final must wait until ALL 12 players have had rest → naturally pushed to Sunday

**With seeding and threshold 0.5:**
- QF-M1 effective players: {Luka} — Luka at 100%, Janne and Eetu at 50% each (borderline)
- SF-M1 effective players: {Luka, Elias} — both seeds normalize above 100%
- Final effective players: {Luka, Elias, Marko, Anton} — only seeded players included
- Result: Final only waits for seeded players' rest → slightly more compact schedule

## Integration with Existing Scheduler

The probability system integrates between `_resolve_known_players()` (which populates `known_players`) and `schedule_matches()` (which uses them for rest enforcement):

```
load_all_matches()
  └─ _resolve_known_players()   ← populates match.known_players (all possible)

schedule_matches(matches, config)
  ├─ _compute_player_probabilities()  ← compute per-player-per-match probability
  ├─ _apply_probability_filter()      ← set match.effective_players (filtered by threshold)
  └─ scheduling loop:
       CHECK effective_players        ← ensures placeholder matches respect R1 rest
       UPDATE only has_real_players   ← avoids over-constraining cross-division
```

The `has_real_players` flag remains on Match objects for:
- Player tracker updates: only confirmed players update the tracker
- Validation: skip definitive double-booking checks for placeholder matches
- Output: annotate matches with "Players TBD" notes
