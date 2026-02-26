# Schedule Generator — Implementation Plan

## Context

We need a Python script (`generate_schedule.py`) that reads the division JSON files in `divisions/` and produces match schedules in `schedules/`. The schedule must respect court availability, player conflicts, rest periods, round ordering, and the rule that all semi-finals and finals must be played on Sunday.

The algorithm and output format are defined in `scheduling-proposal.md`. This document describes the concrete implementation.

## File

- **Create**: `generate_schedule.py`
- **Reads**: `divisions/tournament_index.json` + `divisions/*.json`
- **Writes**: `schedules/Saturday_Morning.json`, `Saturday_Afternoon.json`, `Saturday_Evening.json`, `Sunday_Morning.json`, `Sunday_Afternoon.json`, `schedule_index.json`
- **Dependencies**: Python stdlib only (`json`, `os`, `datetime`, `collections`)

## Implementation Structure

### 1. Data Loading (`load_all_matches()`)

Read `tournament_index.json`, then each main_draw division JSON. Build a flat list of all schedulable matches. Each match object contains:

| Field | Description |
|---|---|
| `id` | Unique match ID: `"{division_code}:{round_name}:M{num}"` |
| `division_code` | e.g., `"MS C"` |
| `division_name` | e.g., `"Men's Singles C"` |
| `category` | e.g., `"Open C"` |
| `round_name` | e.g., `"Round 1"`, `"Quarter-Final"` |
| `match_num` | Integer match number within the round |
| `player1` | Name string or `"Winner R1-M1"` placeholder |
| `player2` | Name string or `"Winner R1-M2"` placeholder |
| `known_players` | List of actual player names (see below) |
| `duration_min` | 30 (standard) or 45 (Elite) |
| `rest_min` | 30 (standard) or 60 (Elite) |
| `priority` | Scheduling priority (lower = schedule first) |
| `is_sf_or_final` | Boolean — must be scheduled on Sunday |
| `prerequisites` | List of match IDs that must complete before this match |

**Priority assignment:**

| Priority | Round type |
|---|---|
| 10 | Round-robin / pool matches |
| 20 | Elimination Round 1 |
| 30 | Group playoff matches (after groups complete) |
| 40 | Elimination Round 2 |
| 50 | Quarter-Final |
| 60 | Semi-Final (Sunday only) |
| 70 | Final (Sunday only) |

**Known players for later rounds (worst-case tracing):**

For Round 1 and pool matches, `known_players` = the actual player names from `player1` and `player2`.

For later rounds, we trace backwards through the bracket to find all possible players who could reach that match:
- R2 Match 1 = "Winner R1-M1 vs Winner R1-M2" → `known_players` = all players from R1-M1 + R1-M2 (up to 4 for singles, 8 for doubles)
- QF Match 1 = "Winner R2-M1 vs Winner R2-M2" → trace through R2 to R1, collecting all possible players
- This grows exponentially but is bounded by draw size (max 32)

These possible players are used for **worst-case conflict checking**: the match is scheduled at a time where even the player with the latest commitment in another division would have enough rest.

**Bye filtering:**

Matches where both players are "Bye" or one is "Bye" with `auto-advances` notes are **not scheduled** (no court time needed). The auto-advancing player's availability is not affected.

**Doubles player extraction:**

For doubles matches, player names are formatted as `"Name1 / Name2"`. Split on `" / "` to get individual names for conflict tracking.

### 2. Court/Time Model (`CourtSchedule`)

**Time representation:** Minutes from Saturday 9:00.
- `0` = Saturday 9:00
- `30` = Saturday 9:30
- `780` = Saturday 22:00 (end of Saturday)
- `1440` = Sunday 9:00 (24 hours × 60 = 1440 minutes gap)
- `1860` = Sunday 16:00 (courts 1–4 close)
- `1980` = Sunday 18:00 (courts 5–8 close)

**Court availability:**

| Courts | Saturday slots | Sunday slots |
|---|---|---|
| 1–4 | 0, 30, 60, ..., 750 (26 slots) | 1440, 1470, ..., 1830 (14 slots) |
| 5–8 | 0, 30, 60, ..., 750 (26 slots) | 1440, 1470, ..., 1950 (18 slots) |
| 9–12 | 0, 30, 60, ..., 750 (26 slots) | *not available* |

**Methods:**
- `is_available(court, time_minute)` → bool: check if a time slot is free
- `book(court, time_minute, match_id, duration)` → mark slot(s) as occupied. A 45-min match blocks 2 consecutive 30-min slots.
- `find_slot(courts_list, earliest_minute)` → `(court, time)` or None: find the first available slot on any of the listed courts, starting from `earliest_minute`

### 3. Player Tracker (`PlayerTracker`)

Tracks when each player is next available.

```python
available_from = defaultdict(int)  # player_name → earliest minute
```

- Initialize all to `0` (Saturday 9:00)
- After scheduling a match at time `T` with duration `D` and rest `R`:
  - For each player in `known_players`: `available_from[player] = T + D + R`
- For later-round matches, update availability for all *possible* players (worst-case)

### 4. Scheduling Loop (`schedule_matches()`)

```
sorted_matches = sort all matches by (priority, division_code, match_num)

for match in sorted_matches:
    # Compute the earliest this match can start
    earliest = 0

    # Prerequisite constraint: all prior-round matches must finish
    for prereq_id in match.prerequisites:
        prereq_end = scheduled_end_time[prereq_id]
        earliest = max(earliest, prereq_end + match.rest_min)

    # Player availability constraint
    for player in match.known_players:
        earliest = max(earliest, player_tracker.available_from[player])

    # Sunday rule
    if match.is_sf_or_final:
        earliest = max(earliest, 1440)  # Sunday 9:00

    # Find a court and time slot
    courts = get_eligible_courts(match)
    slot = court_schedule.find_slot(courts, earliest)

    if slot:
        court, time = slot
        court_schedule.book(court, time, match.id, match.duration_min)
        player_tracker.update(match.known_players, time, match.duration_min, match.rest_min)
        scheduled[match.id] = (court, time)
    else:
        unscheduled.append(match)
```

**Court eligibility (`get_eligible_courts(match)`):**

Returns an ordered list of courts to try (preferred courts first):

| Category | Preferred courts | Fallback courts |
|---|---|---|
| Elite | 5, 6, 7, 8 | *(none — hard constraint)* |
| Open A | 5, 6, 7, 8 | 1, 2, 3, 4 (+ 9–12 Sat) |
| Junior | 9, 10, 11, 12 (Sat only) | 1, 2, 3, 4 (+ 5–8) |
| Open B, C, Veterans | 1, 2, 3, 4 | 5–12 (Sat) or 5–8 (Sun) |

Note: Courts 9–12 are only available on Saturday. If the match is on Sunday (time ≥ 1440), courts 9–12 are excluded.

### 5. Output Generation (`write_schedules()`)

Split scheduled matches into sessions by time range:

| Session | Time range (minutes) |
|---|---|
| Saturday Morning | 0–239 (9:00–12:59) |
| Saturday Afternoon | 240–539 (13:00–17:59) |
| Saturday Evening | 540–779 (18:00–21:59) |
| Sunday Morning | 1440–1679 (9:00–12:59) |
| Sunday Afternoon | 1680–1980 (13:00–18:00) |

**Minute-to-time conversion:**
```python
def minute_to_time(m):
    if m >= 1440:  # Sunday
        h, mm = divmod(m - 1440, 60)
        day = "Sunday"
    else:
        h, mm = divmod(m, 60)
        day = "Saturday"
    return day, f"{h + 9:02d}:{mm:02d}"
```

Each session JSON file:
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
      "player1": "Luka Heikkilä",
      "player2": "Siwei Lucas Qiu",
      "duration_min": 30,
      "category": "Junior"
    }
  ]
}
```

**Schedule index** (`schedule_index.json`):
```json
{
  "tournament": "Kumpoo Tervasulan Eliitti 2025",
  "sessions": [
    {"file": "Saturday_Morning.json", "label": "Saturday Morning", "time_range": "09:00–13:00", "match_count": 48}
  ],
  "total_matches": 281,
  "total_scheduled": 281,
  "unscheduled": [],
  "warnings": []
}
```

### 6. Validation (`validate_schedule()`)

After scheduling completes, run validation checks and collect warnings:

1. **Completeness**: Any matches left unscheduled?
2. **Player double-booking**: For each time slot, check no player appears in two matches
3. **Rest period violations**: For each player, check consecutive matches have sufficient gap
4. **Court availability**: No match scheduled outside a court's operating hours
5. **SF/Final on Sunday**: All Semi-Final and Final matches have time ≥ 1440
6. **Round ordering**: For each bracket, verify R1 matches are scheduled before R2, R2 before QF, etc.

Print a summary:
```
Schedule Summary:
  Total matches: 281
  Scheduled: 275
  Bye (skipped): 6
  Unscheduled: 0
  Warnings: 0

  Saturday Morning:  48 matches
  Saturday Afternoon: 62 matches
  Saturday Evening:  45 matches
  Sunday Morning:    38 matches
  Sunday Afternoon:  22 matches
```

## Key Design Decisions

1. **45-min Elite matches occupy 2 consecutive 30-min slots** — the court is blocked for both
2. **Bye matches are not scheduled** — auto-advances don't need court time
3. **Playoff sheets** are skipped (data is embedded in the main draw JSON via the `playoff` key)
4. **Round-robin divisions** have no SF/Final rounds, so the Sunday rule doesn't apply
5. **Court preference is soft** (try preferred courts first, fall back to others) **except Elite which is hard** (courts 5–8 only)
6. **Worst-case buffering** for later rounds — guarantees no rest violations regardless of who wins, at the cost of slightly larger time gaps

## Verification

```bash
python generate_schedule.py
```

Then verify:
1. All non-bye matches appear in the schedule files
2. No validation warnings printed
3. Session JSON files have correct time ranges
4. `schedule_index.json` shows correct total counts
5. Spot-check: Elite matches are on courts 5–8 only
6. Spot-check: All SF/Final matches appear in Sunday session files
7. Spot-check: No player has back-to-back matches without rest
