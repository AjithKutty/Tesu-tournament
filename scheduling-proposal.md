# Match Schedule Generator — Design Proposal

## Problem Summary

Generate match schedules for the Kumpoo Tervasulan Eliitti 2025 tournament.

- **281 total matches** across 28 divisions
- **144 players**, 107 of whom compete in multiple divisions (up to 3)
- **12 courts** on Saturday, 8 courts on Sunday
- **2 days**: Saturday 9:00–22:00, Sunday 9:00–16:00/18:00
- Player rest, court restrictions, round ordering, and player conflicts must all be respected

## Key Constraints (from scheduling-rules.md)

### Court Availability

| Day | Courts | Hours |
|---|---|---|
| Saturday | 1–12 | 9:00–22:00 |
| Sunday | 1–4 | 9:00–16:00 |
| Sunday | 5–8 | 9:00–18:00 |

**Court preferences:**
- Elite (MS V, WS V, XD V): courts 5–8 only
- Open A: courts 5–8 preferred
- Junior: courts 9–12 preferred (Saturday only)

### Match Durations & Rest

| Category | Duration | Rest between matches |
|---|---|---|
| Juniors | 30 min | 30 min |
| Adults | 30 min | 30 min |
| Elite | 45 min | 60 min |

### Start Times

All matches start on 30-minute intervals (9:00, 9:30, 10:00, ...).

### Round Ordering

Within elimination brackets, all matches of round N must complete before round N+1 can begin. Matches within the same round should be scheduled close together in time.

### Sunday Rule

**Semi-finals and finals of all divisions must be played on Sunday.** This applies to:
- Elimination brackets: Semi-Final and Final rounds
- Group+playoff divisions: the playoff final (and SF if the playoff bracket is large enough, e.g., BS U17)
- Round-robin divisions: no SF/Final rounds, so this rule does not apply to them

## Match Count by Division

| Division | Format | Matches |
|---|---|---|
| MS C | 32-draw elimination | 31 |
| MS B | 32-draw elimination | 31 |
| MD B | 32-draw elimination | 31 |
| BS U17 | 5 groups + 8-player playoff | 28 |
| BS U13 | 2 groups + final | 17 |
| MS A | 16-draw elimination | 15 |
| MD A | 16-draw elimination | 15 |
| MD C | 16-draw elimination | 15 |
| BS U15 | 2 groups + final | 10 |
| XD A | 8-draw elimination | 7 |
| XD B | 8-draw elimination | 7 |
| XD C | 8-draw elimination | 7 |
| MS 45 | 2 groups + final | 7 |
| BS U11 | 4-player round-robin | 6 |
| MD 45 | 4-pair round-robin | 6 |
| MS V | 4-player round-robin | 6 |
| WS C | 4-player round-robin | 6 |
| XD V | 4-pair round-robin | 6 |
| BD U13 | 3-pair round-robin | 3 |
| BD U15 | 3-pair round-robin | 3 |
| BD U17 | 3-pair round-robin | 3 |
| MD 35 | 3-pair round-robin | 3 |
| MS 35 | 3-player round-robin | 3 |
| WD A | 3-pair round-robin | 3 |
| WD C | 3-pair round-robin | 3 |
| WS B | 3-player round-robin | 3 |
| WS V | 3-player round-robin | 3 |
| XD 35 | 3-pair round-robin | 3 |

**Total: 281 matches**

## The Player Conflict Challenge

### Known conflicts (Round 1 / Pool matches)

For R1 and round-robin matches, all players are known upfront. The scheduler can check:
- Player X is in Match A at 10:00 → Player X cannot play Match B until 10:30 + 30 min rest = 11:00.

This covers 107 players who compete in 2–3 divisions.

### Unknown conflicts (Later bracket rounds)

For Round 2, Quarter-Finals, Semi-Finals, and Finals in elimination brackets, we **don't know who will play** until the earlier rounds finish. For example:
- MS C Round 2 Match 1 = "Winner of R1-M1 vs Winner of R1-M2"
- The winner of R1-M1 might be Player X who also plays in MD C

This means we can't do exact player-conflict checking for later rounds.

### Proposed solution: Worst-case rest buffer

For later-round matches, instead of checking specific player conflicts, we use a **worst-case timing guarantee**:

1. **Identify all possible players** who could reach each later-round match (by tracing the bracket backwards to R1)
2. **For each possible player**, check their other divisions' schedules
3. **Schedule the later-round match** at a time where even the worst-case scenario (a player finishing their last possible match in another division) still allows sufficient rest

**Example:**
- MS C R2-M1 could involve Player X (from R1-M1) or Player Y (from R1-M2)
- Player X also plays MD C R1-M3, scheduled at 11:00
- Player Y also plays XD C QF-M1, scheduled at 11:30
- MS C R1-M1 finishes at 10:30, R1-M2 finishes at 10:30
- Worst case: Player Y finishes XD C at 12:00 → needs rest until 12:30
- So MS C R2-M1 must be scheduled at 12:30 or later

This approach:
- **Guarantees** no player ever has insufficient rest, regardless of who wins
- **May create larger gaps** than necessary (a player who was eliminated doesn't need the slot, but we reserved it anyway)
- **Is conservative** but safe — better to have small gaps than scheduling conflicts

### Alternative: Schedule later rounds as "TBD slots"

Another option is to only assign time/court slots for later rounds without player names, and update the schedule as results come in. The schedule would show:

```
14:00  Court 3  MS C Quarter-Final 1  (Winner R2-M1 vs Winner R2-M2)
```

This is how many real tournaments operate — the bracket times are fixed, but players fill in as the tournament progresses.

### Recommended approach: Hybrid

1. **Fully schedule** all R1 and round-robin matches with exact player-conflict resolution
2. **Pre-allocate time slots** for later rounds using worst-case rest buffers
3. **Mark later-round matches** with placeholder player names ("Winner of...")
4. The generated schedule serves as the tournament's master timing plan

## Scheduling Algorithm

### Step 1: Classify and prioritize matches

Priority order (higher = schedule first):
1. Round-robin / pool matches (known players, often prerequisites for playoffs)
2. Elimination R1 matches (known players, prerequisite for all later rounds)
3. Group playoff matches (after groups complete)
4. Elimination R2 matches
5. Quarter-Finals
6. Semi-Finals — **must be on Sunday**
7. Finals — **must be on Sunday**

### Step 2: Build player availability map

```
player_available_from[player_name] = earliest_datetime_they_can_play_next
```

Initially all players are available from 9:00 Saturday. After scheduling a match, update:
- Standard: available_from = match_end + 30 min
- Elite: available_from = match_end + 60 min

### Step 3: Greedy slot assignment

For each time slot (30-min intervals) on each court:
1. Find the highest-priority unscheduled match that fits:
   - All players available (checked against `player_available_from`)
   - Court is eligible (Elite → courts 5–8, Junior → courts 9–12, etc.)
   - Round prerequisites met (all prior-round matches in this bracket already scheduled earlier)
2. Assign the match → update player availability

### Step 4: Later rounds (worst-case buffering)

For R2+ matches:
1. Identify all prerequisite matches and their scheduled end times
2. Identify all *possible* players (trace bracket back to R1)
3. For each possible player, find their latest commitment in other divisions
4. The match cannot start before: `max(all_prereq_end_times, worst_case_player_availability) + rest_period`
5. Find the first available court slot at or after that time

### Day Allocation Heuristic

**Saturday Morning (9:00–13:00, ~96 slots):**
- Junior pools (BS U11, BD U13, BD U15, BD U17) on courts 9–12
- BS U13/U15 groups on courts 9–12
- Veterans round-robins (MS 35, MD 35, XD 35) on courts 1–4
- WS B, WS C, WD A, WD C pools on courts 1–4

**Saturday Afternoon (13:00–18:00, ~120 slots):**
- BS U17 groups on courts 9–12
- Open B/C R1 matches (MS B, MS C, MD B, MD C) on courts 1–4
- Open A R1 (MS A, MD A) on courts 5–8
- Elite round-robins (MS V, WS V, XD V) on courts 5–8

**Saturday Evening (18:00–22:00, ~96 slots):**
- Open B/C R2 and QF matches
- Open A QF
- XD A/B/C QF
- Junior playoff QF (BS U17)
- No semi-finals or finals (reserved for Sunday)

**Sunday Morning (9:00–13:00):**
- All semi-finals across divisions
- Junior playoff SF (BS U17)
- BS U13/U15/MS 45 playoff finals
- Remaining QF matches if any spill from Saturday

**Sunday Afternoon (13:00–16:00/18:00):**
- All finals across divisions
- Open A/B/C finals, XD finals, MD finals
- Elite division completion (if pool format has a deciding final match)

## Output Structure

### Directory: `schedules/`

| File | Contents |
|---|---|
| `Saturday_Morning.json` | Sat 9:00–13:00 matches |
| `Saturday_Afternoon.json` | Sat 13:00–18:00 matches |
| `Saturday_Evening.json` | Sat 18:00–22:00 matches |
| `Sunday_Morning.json` | Sun 9:00–13:00 matches |
| `Sunday_Afternoon.json` | Sun 13:00–16:00/18:00 matches |
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
      "player1": "Luka Heikkilä",
      "player2": "Siwei Lucas Qiu",
      "duration_min": 30,
      "category": "Junior"
    },
    {
      "time": "14:00",
      "court": 3,
      "division": "MS C",
      "division_name": "Men's Singles C",
      "round": "Quarter-Final",
      "match_num": 1,
      "player1": "Winner R2-M1",
      "player2": "Winner R2-M2",
      "duration_min": 30,
      "category": "Open C",
      "notes": "Players TBD based on earlier results"
    }
  ]
}
```

### Schedule index JSON

```json
{
  "tournament": "Kumpoo Tervasulan Eliitti 2025",
  "generated": "2025-01-15",
  "sessions": [
    {
      "file": "Saturday_Morning.json",
      "label": "Saturday Morning",
      "time_range": "09:00–13:00",
      "match_count": 48
    }
  ],
  "total_matches": 281,
  "total_scheduled": 281,
  "unscheduled": [],
  "warnings": []
}
```

## Script

**File**: `generate_schedule.py`
- **Reads**: `divisions/*.json`
- **Writes**: `schedules/*.json`
- **Dependencies**: Python stdlib only (json, os, datetime)

## Verification Checklist

After running `python generate_schedule.py`:
1. All 281 matches appear in the schedule files
2. No player has two matches at the same time
3. Rest periods respected (30 min standard, 60 min Elite)
4. Elite matches on courts 5–8 only
5. No matches outside court availability windows
6. Round ordering correct (R1 → R2 → QF → SF → F)
7. Same-round matches are grouped close in time
8. Later-round matches have "Winner of..." labels
9. **All semi-finals and finals are scheduled on Sunday**
