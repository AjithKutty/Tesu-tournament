# Schedule Generator — Implementation Plan

## Context

We need a Python script (`generate_schedule.py`) that reads tournament config and division JSON files, then produces match schedules. The schedule must respect court availability, player conflicts, rest periods, round ordering, and day constraints — all configurable per tournament.

The algorithm and output format are defined in `scheduling-proposal.md`. This document describes the concrete implementation.

## File

- **Modifies**: `src/generate_schedule.py`
- **Reads**: Tournament config files (`venue.yaml`, `match_rules.yaml`, `court_preferences.yaml`, `scheduling.yaml`, `divisions.yaml`)
- **Reads**: `tournaments/<name>/output/divisions/tournament_index.json` + `tournaments/<name>/output/divisions/*.json`
- **Writes**: `tournaments/<name>/output/schedules/*.json` (one per session + index)
- **Dependencies**: Python stdlib (`json`, `os`, `datetime`, `collections`) + `pyyaml`

## Implementation Structure

### 0. Config Loading (`load_config()`)

Read all YAML config files from the tournament's `config/` directory. Return a config object with:
- `venue`: days, sessions, court groups, slot duration
- `match_rules`: default and per-category match duration / rest period
- `court_preferences`: default and per-category court preference chains
- `scheduling`: priorities, round-priority map, elite divisions, day constraints
- `divisions`: event names, level-category map, elite divisions

Missing config files use sensible defaults (30 min slots, 30 min match/rest, no court preferences, no day constraints).

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
| `duration_min` | From `match_rules.yaml` based on category |
| `rest_min` | From `match_rules.yaml` based on category |
| `priority` | From `scheduling.yaml` based on round type |
| `is_day_constrained` | Boolean + target day, from `scheduling.yaml` day constraints |
| `prerequisites` | List of match IDs that must complete before this match |

**Priority assignment** uses `scheduling.yaml`:
- Look up round name in `round_priority_map` to get priority key
- Look up priority key in `priorities` to get numeric value
- Pool matches from `elite_divisions` get `elite_pool` priority

**Match duration and rest** use `match_rules.yaml`:
- Look up category in `categories`; fall back to `default`

**Known players for later rounds (worst-case tracing):**
Same as before — trace backwards through the bracket to find all possible players.

**Bye filtering:**
Matches where both players are "Bye" or one is "Bye" with `auto-advances` notes are not scheduled.

### 2. Court/Time Model (`CourtSchedule`)

**Time representation:** Built dynamically from `venue.yaml`.
- Parse day start times and compute minute offsets from tournament start
- Each day's offset = cumulative minutes from Day 1 start, with overnight gaps calculated from day start times

**Court availability:** Built from `venue.yaml`:
- For each day, for each court group, compute available time slots based on start/end times and `slot_duration`

**Methods:**
- `is_available(court, time_minute)` → bool: check if a time slot is free
- `book(court, time_minute, match_id, duration)` → mark slot(s) as occupied
- `find_slot(courts_list, earliest_minute)` → `(court, time)` or None
- `court_exists(court, time_minute)` → bool: is this court available at this time (venue constraint)

### 3. Player Tracker (`PlayerTracker`)

Tracks when each player is next available. Same design as before but rest periods come from `match_rules.yaml`.

### 4. Scheduling Loop (`schedule_matches()`)

Same greedy algorithm but reads constraints from config:
- Court eligibility from `court_preferences.yaml`
- Day constraints from `scheduling.yaml`
- Match durations from `match_rules.yaml`
- Priorities from `scheduling.yaml`

### 5. Output Generation (`write_schedules()`)

Split scheduled matches into sessions defined in `venue.yaml`. Session boundaries come from config, not hardcoded.

**Minute-to-time conversion:** Uses the day definitions from `venue.yaml` to determine which day a minute offset falls on and compute the clock time.

### 6. Validation (`validate_schedule()`)

Same validation checks, but thresholds and constraints come from config:
1. **Completeness**: Any matches left unscheduled?
2. **Player double-booking**: For each time slot, check no player appears in two matches
3. **Rest period violations**: Per-category rest from `match_rules.yaml`
4. **Court availability**: Per `venue.yaml` court windows
5. **Day constraints**: Per `scheduling.yaml`
6. **Round ordering**: For each bracket, verify round order

## Key Design Decisions

1. **Multi-slot matches** occupy consecutive slots — the court is blocked for all
2. **Bye matches are not scheduled** — auto-advances don't need court time
3. **Playoff sheets** are skipped (data is embedded in the main draw JSON via the `playoff` key)
4. **Round-robin divisions** typically have no SF/Final rounds, so day constraints may not apply
5. **Court preference is soft** (try preferred first, fall back) **except `required_courts` which is hard**; `day_overrides` allow per-day customization
6. **Worst-case buffering** for later rounds — guarantees no rest violations regardless of who wins
7. **All constraints from config** — no hardcoded venue/time/court values in the scheduling code
8. **Overrun buffer is bidirectional** — when booking a match, the court is blocked for `duration + overrun_buffer` after it AND the buffer time before it is reserved. This prevents both (a) a match being placed too close after an already-booked match, and (b) a later-scheduled match being placed too close before an earlier-scheduled high-priority match. This is necessary because matches are scheduled in priority order, not chronological order.

## Verification

```bash
python src/generate_schedule.py --tournament tournaments/<name>
```

Then verify:
1. All non-bye matches appear in the schedule files
2. No validation warnings printed
3. Session JSON files have correct time ranges matching `venue.yaml`
4. `schedule_index.json` shows correct total counts
5. Court restrictions from `court_preferences.yaml` are respected
6. Day constraints from `scheduling.yaml` are respected
7. No player has back-to-back matches without configured rest
