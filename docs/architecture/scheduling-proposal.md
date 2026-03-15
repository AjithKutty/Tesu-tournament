# Match Schedule Generator — Design Proposal

## Problem Summary

Generate match schedules for a badminton tournament. The scheduler reads tournament-specific constraints from YAML config files, making it reusable across different tournaments and venues.

- Tournament days, court counts, and availability windows are defined in `venue.yaml`
- Match durations and rest periods per category are defined in `match_rules.yaml`
- Court preferences per category are defined in `court_preferences.yaml`
- Scheduling priorities and day constraints are defined in `scheduling.yaml`
- Player rest, court restrictions, round ordering, and player conflicts must all be respected

## Key Constraints (from config files)

### Court Availability (`venue.yaml`)

Defines days, court groups with end times, and session boundaries. Example for a 2-day tournament:

| Day | Courts | Hours |
|---|---|---|
| Day 1 | 1–12 | 9:00–22:00 |
| Day 2 | 1–4 | 9:00–16:00 |
| Day 2 | 5–8 | 9:00–18:00 |

Court preferences per category are defined in `court_preferences.yaml`:
- Required courts: hard constraint (e.g., Elite on courts 5–8 only)
- Preferred/fallback/last-resort: soft preference chain

### Match Durations & Rest (`match_rules.yaml`)

| Category | Duration | Rest between matches |
|---|---|---|
| Default | 30 min | 30 min |
| Elite | 45 min | 60 min |

### Start Times

All matches start on intervals defined by `slot_duration` in `venue.yaml` (e.g., every 30 minutes).

### Round Ordering

Within elimination brackets, all matches of round N must complete before round N+1 can begin. Matches within the same round should be scheduled close together in time.

### Day Constraints (`scheduling.yaml`)

Specific rounds can be constrained to specific days (e.g., Semi-finals and finals must be played on the last day).

## The Player Conflict Challenge

### Known conflicts (Round 1 / Pool matches)

For R1 and round-robin matches, all players are known upfront. The scheduler can check:
- Player X is in Match A at 10:00 → Player X cannot play Match B until 10:30 + rest period.

### Unknown conflicts (Later bracket rounds)

For Round 2, Quarter-Finals, Semi-Finals, and Finals in elimination brackets, we **don't know who will play** until the earlier rounds finish.

### Proposed solution: Worst-case rest buffer

For later-round matches, instead of checking specific player conflicts, we use a **worst-case timing guarantee**:

1. **Identify all possible players** who could reach each later-round match (by tracing the bracket backwards to R1)
2. **For each possible player**, check their other divisions' schedules
3. **Schedule the later-round match** at a time where even the worst-case scenario (a player finishing their last possible match in another division) still allows sufficient rest

This approach:
- **Guarantees** no player ever has insufficient rest, regardless of who wins
- **May create larger gaps** than necessary (a player who was eliminated doesn't need the slot, but we reserved it anyway)
- **Is conservative** but safe — better to have small gaps than scheduling conflicts

## Scheduling Algorithm

### Step 1: Load config and classify matches

Read all config files. Load division JSON files and build a flat list of schedulable matches. Assign priorities from `scheduling.yaml`.

Priority order (from `scheduling.yaml`):
1. Elite pool matches (highest — scheduled first)
2. Round-robin / pool matches
3. Elimination Round 1 matches
4. Group playoff matches
5. Elimination Round 2 matches
6. Quarter-Finals
7. Semi-Finals (may have day constraints)
8. Finals (may have day constraints)

### Step 2: Build player availability map

```
player_available_from[player_name] = earliest_time_they_can_play_next
```

Initially all players are available from the start of Day 1. After scheduling a match, update using the category's rest period from `match_rules.yaml`.

### Step 3: Greedy slot assignment

For each match (in priority order):
1. Compute earliest start time considering:
   - Prerequisite matches must have finished
   - All players (or possible players) must be available
   - Day constraints from `scheduling.yaml`
2. Find eligible courts from `court_preferences.yaml` (required → preferred → fallback → last resort)
3. Find the first available slot on any eligible court at or after the earliest time
4. Book the slot and update player availability

### Step 4: Later rounds (worst-case buffering)

For R2+ matches:
1. Identify all prerequisite matches and their scheduled end times
2. Identify all *possible* players (trace bracket back to R1)
3. For each possible player, find their latest commitment in other divisions
4. The match cannot start before: `max(all_prereq_end_times, worst_case_player_availability) + rest_period`
5. Find the first available court slot at or after that time

## Output Structure

### Directory: `tournaments/<name>/output/schedules/`

Session files are generated based on the sessions defined in `venue.yaml`. For example, a tournament with 5 sessions produces:

| File | Contents |
|---|---|
| `Saturday_Morning.json` | Matches in the Saturday Morning session |
| `Saturday_Afternoon.json` | Matches in the Saturday Afternoon session |
| `Saturday_Evening.json` | Matches in the Saturday Evening session |
| `Sunday_Morning.json` | Matches in the Sunday Morning session |
| `Sunday_Afternoon.json` | Matches in the Sunday Afternoon session |
| `schedule_index.json` | Summary and stats |

### Per-session JSON structure

```json
{
  "session": "Saturday Morning",
  "date": "Saturday",
  "start": "09:00",
  "end": "13:00",
  "matches": [
    {
      "time": "09:00",
      "court": 9,
      "division": "BS U11",
      "division_name": "Boys' Singles U11",
      "round": "Pool",
      "match_num": 1,
      "player1": "Player A",
      "player2": "Player B",
      "duration_min": 30,
      "category": "Junior"
    }
  ]
}
```

### Schedule index JSON

```json
{
  "tournament": "<tournament name>",
  "sessions": [
    {"file": "Saturday_Morning.json", "label": "Saturday Morning", "time_range": "09:00–13:00", "match_count": 48}
  ],
  "total_matches": 281,
  "total_scheduled": 281,
  "unscheduled": [],
  "warnings": []
}
```

## Script

**File**: `src/generate_schedule.py`
- **Reads**: Tournament config (`venue.yaml`, `match_rules.yaml`, `court_preferences.yaml`, `scheduling.yaml`, `divisions.yaml`)
- **Reads**: `tournaments/<name>/output/divisions/*.json`
- **Writes**: `tournaments/<name>/output/schedules/*.json`
- **Dependencies**: Python stdlib + `pyyaml`

## Verification Checklist

After running `python src/generate_schedule.py --tournament tournaments/<name>`:
1. All non-bye matches appear in the schedule files
2. No player has two matches at the same time
3. Rest periods respected (per category config)
4. Court restrictions respected (per category config)
5. No matches outside court availability windows
6. Round ordering correct (R1 → R2 → QF → SF → F)
7. Same-round matches are grouped close in time
8. Later-round matches have "Winner of..." labels
9. Day constraints respected (e.g., SF/Finals on the configured day)
