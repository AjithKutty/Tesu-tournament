## Game Scheduling Rules

### Overview

This document describes the general scheduling rules for badminton tournaments. All venue-specific parameters (courts, times, durations) are configured per tournament via YAML files in the tournament's `config/` directory.

### Court Availability

Court availability is defined in `venue.yaml`. Each tournament day specifies:
- Which courts are available
- Start and end times per court group (different courts may have different start/end times)
- Per-day court buffer breaks for maintenance/rest intervals

Courts that are not available on a given day are automatically excluded from scheduling.

### Court Buffers

Periodic court buffers can be configured per day in `venue.yaml` to block courts at regular intervals for breaks or maintenance. Configuration includes:
- Which courts are in the rotation pool
- Buffer duration (minutes)
- Interval frequency (minutes from day start)
- How many courts to block per interval (rotates through the pool)

Court buffers are pre-reserved before match scheduling begins. When a match cannot be scheduled due to court buffers, the scheduler can override buffer blocks as a fallback — this is logged as a warning in the scheduling trace and flagged by the verifier.

### Match Durations

Match durations are defined in `scheduling.yaml` under `match_duration`. Resolution order:
1. Per-division override (e.g., `XD A: 30` overrides category default)
2. Per-category (e.g., `Open A: 40`)
3. Default (e.g., `30`)

Category keys can use either the full name (`"Open A"`) or the level code (`"A"`).

Matches that exceed one scheduling slot (e.g., a 40-minute match in a 15-minute slot grid) block multiple consecutive slots on the assigned court.

### Rest Rules

Rest between matches is context-dependent, defined in `scheduling.yaml` under `rest_rules`. Three levels of rest rules apply, and the **maximum** of all applicable rules is used:

- **`same_division_rest`**: Between consecutive games for a player within the same division. Can be overridden per division (e.g., Elite singles needs 3 hours between games in MS V).
- **`same_category_rest`**: Between games in different divisions of the same category (e.g., a player in MS V and XD V — both Elite — needs 60 min between them).
- **`cross_division_rest`**: Absolute minimum rest between games in any two divisions (default baseline, e.g., 30 min).
- **`player_exceptions`**: Per-player overrides for specific division pairs. When a player's matches in two divisions cannot both be scheduled with normal rest periods, an exception can reduce or eliminate the rest requirement for that player between those divisions. This affects only the named player — other players in the same divisions keep their normal rest.

**Cross-division rest relaxation fallback**: When a match cannot be scheduled with full rest constraints, the scheduler falls back to relaxing cross-division rest (only enforcing same-division rest and no-overlap). This is logged in the scheduling trace and flagged by the verifier.

### Match Density

An optional match density limit constrains how many matches a player can have within a rolling time window (e.g., max 3 matches within 3 hours). Configured via `match_density` in `scheduling.yaml`. Per-player exceptions allow specific players to have different limits.

### Match Overrun Buffer

Matches may overrun their expected duration. To prevent cascading delays, a configurable `overrun_buffer` (in minutes) can be defined in `scheduling.yaml` per category or as a default for all categories. The buffer creates a time gap between consecutive matches on the same court, absorbing potential overruns.

**How it works:**

When a match has an `overrun_buffer`, the scheduler blocks the court bidirectionally:
- **After the match**: the court is blocked for `match_duration + overrun_buffer` instead of just `match_duration`, preventing the next match from starting too soon.
- **Before the match**: the buffer time before the match start is also reserved, preventing a later-scheduled match from being placed too close before it.

This bidirectional blocking is necessary because matches are scheduled in priority order — higher-priority matches (e.g., Elite) are placed first, and lower-priority matches fill in around them later. Without the backward reservation, a lower-priority match could be placed immediately before a higher-priority match, leaving no gap for overruns.

### Court Preferences

Court assignment preferences are defined in `court_preferences.yaml` per division category:
- **Required courts**: Hard constraint — the match must be on one of these courts.
- **Preferred courts**: Tried first, but not mandatory.
- **Fallback courts**: Used when preferred courts are unavailable.
- **Last resort courts**: Used only when all other options are exhausted.

Categories not listed use the default preference chain.

**Per-round overrides** (`round_overrides` within a category): Allow different court preferences for specific rounds. For example, Junior group matches on courts 9-12 but Junior Finals on courts 5-8.

**Global round preferences** (`round_court_preferences`): Apply to all categories (except those with `required_courts`). For example, all Finals and Semi-Finals prefer courts 5-8.

### Division Draw Formats

Draw formats (elimination, round-robin, group+playoff) are auto-detected from the input data. When only an entries-only Excel is available (no draws), the format is determined by `draw_formats` in `scheduling.yaml`:
- Per-division override (e.g., `"BS U17": {format: group_playoff, groups: 4, advancers_per_group: 2}`)
- Per-category default (e.g., `Veterans: round_robin`)
- Global default (e.g., `elimination` for >6 entries, `round_robin` for ≤6)

### Scheduling Priorities

Matches are scheduled in priority order defined in `scheduling.yaml`. Lower number = scheduled first. The priority system is hierarchical:

1. **Base round priorities** (`priorities.rounds`): e.g., Round 1: 10, Pool: 30, Quarter-Final: 50
2. **Per-category overrides** (`priorities.categories`): e.g., Elite Pool: 5
3. **Per-division overrides** (`priorities.divisions`): e.g., MS C Round 1: 5
4. **Per-day overrides** (`priorities.day_overrides`): Different priorities on different days, with round-level and division-level overrides within each day. For example, all Quarter-Finals on Sunday get priority 25.

Day overrides are resolved at load time using explicit day constraints. When a match has no explicit day constraint but is inferred to be on a specific day (via round-completion chain from constrained SF/Final), the inferred day is used for priority resolution.

### Round Completion

When enabled via `round_completion` in `scheduling.yaml`, all matches in a round must finish before the next round starts within the same division. For example, all Round 1 matches in MS B must be completed before any Round 2 match in MS B can begin.

This rule applies only to elimination rounds (Round 1, Round 2, Quarter-Final, Semi-Final, Final) and playoff rounds. It does not apply to round-robin pool matches.

Specific divisions can be exempted via the `exceptions` list in the config.

### Round Time Limits

A soft constraint that limits the time span within which all matches of a round (per division/group) must complete. Configured via `round_time_limit` in `scheduling.yaml`:
- Per-round defaults (e.g., Quarter-Final: 120 minutes)
- Per-category overrides (e.g., Junior Pool: 300 minutes / 5 hours)
- Per-division overrides

When the constraint cannot be met, the scheduler places the match anyway and logs a warning. The verifier reports violations.

### Same-Day Rule

All matches in the same round of the same division must be scheduled on the same day. This is an automatic scheduling rule — no configuration is needed.

The rule applies to every draw format:
- **Elimination**: All matches in a given round (e.g., Round 1, Quarter-Final) of a division are placed on a single day.
- **Round-robin**: All pool matches for a division are placed on a single day.
- **Group+playoff**: All group-stage matches for a division are placed on a single day. Each playoff round for that division is also placed on a single day (which may be a different day from the group stage).

If the matches for a round+division cannot all fit on the assigned day, this is a **hard error** — the scheduler must report the failure and abort rather than silently splitting a round across days.

### Day Constraints

Day constraints force specific rounds to be scheduled on a specific day. They are configured in `scheduling.yaml` under `day_constraints`.

**Global constraints** apply to all divisions. For example, semi-finals and finals may be required to be played on the last day of the tournament.

**Per-division constraints** (`division_day_constraints`) allow the tournament director to pin specific divisions' rounds or stages to a chosen day. Per-division constraints override global constraints for the same round when both apply.

### Time Deadlines

Rounds can be constrained to finish by a specific day and time via `time_deadlines` in `scheduling.yaml`. Supports global (all divisions) or per-division scoping. For example, MS C Round 1 must finish by Saturday 12:00.

### Semi-Final Pair Scheduling

When `semi_final_same_time: true` is set in `scheduling.yaml`, both Semi-Final matches of a division are scheduled together as a pair — the scheduler finds a time slot where **two courts** are simultaneously available and both matches' player constraints are satisfied. This is fundamentally different from other match scheduling:

- **Normal match scheduling**: Each match is placed individually in priority order. The first available slot+court combination is used.
- **SF pair scheduling**: Both SF matches must be placed at the **same time** on different courts. The scheduler searches for a slot where two eligible courts are free and all players from both matches pass rest/overlap checks.

The SF pair scheduler also ensures the Final can fit after the SFs by tightening the latest bound: `SF_latest = day_end - SF_duration - same_division_rest - Final_duration`.

If the normal pair search fails, a relaxed fallback retries with cross-division rest relaxed. The scheduling trace logs whether the pair was placed normally or via the relaxed fallback.

### Potential Conflict Avoidance

For later-round matches where players are unknown (placeholders like "Winner R1-M1"), the scheduler traces all possible players through the bracket prerequisites and can avoid scheduling matches at the same time when the same player could potentially be in both.

Configured via `potential_conflict_avoidance` in `scheduling.yaml`:
- **`default.rounds`**: Rounds checked across ALL categories (e.g., Round 2, Quarter-Final, Semi-Final, Final)
- **`categories.<name>.rounds`**: Rounds checked within a specific category only (e.g., Junior: Semi-Final, Final)

The `default` scope prevents both time overlaps AND enforces rest between potential matches across all categories. The `categories` scope only checks within the same category.

When the full potential conflict check fails, a relaxed fallback accepts cross-category potential overlaps but still prevents same-category conflicts. The verifier independently reports any remaining potential conflicts.

### Bye Resolution

When a player advances via bye (no opponent), their actual name is propagated into later rounds instead of showing as "Winner R1-M1". This ensures:
- The player's name appears in QF/SF bracket displays
- The scheduler correctly tracks confirmed players for rest enforcement
- The scheduling trace shows real player names for analysis

### Scheduling Fallback Chain

When a match cannot be placed, the scheduler tries increasingly relaxed constraints in order:

1. **Normal pass**: Full constraints — rest, court preferences, potential conflict avoidance
2. **Inline buffer override**: For matches with round court preferences (e.g., Finals), try overriding court buffer on preferred courts before accepting fallback courts
3. **Buffer override pass**: Retry all slots with court buffer blocks treated as overridable
4. **Round time limit relaxation**: If the round time limit was the blocker, retry without it
5. **Cross-division rest relaxation**: Only enforce same-division rest and no-overlap; accept cross-division rest violations
6. **SF pair relaxed**: For semi-final pairs, retry with relaxed cross-division rest

Each fallback level is logged in the scheduling trace with appropriate warnings.

### Additional Scheduling Rules

- Start times are set at fixed intervals defined by `slot_duration` in `venue.yaml`.
- No player may be scheduled on two courts at the same time.
- For later-round matches where players are unknown, worst-case player tracing ensures rest constraints are met for all possible players.
- Bye matches are not scheduled (no court time needed).
- The scheduling algorithm is deterministic — the same configuration and input always produces the same output.

### Schedule Verification

The verifier (`verify_schedule.py`) performs 9 independent checks:

1. **Bracket completeness**: All expected rounds have the correct number of matches
2. **Round ordering**: Preceding rounds scheduled before succeeding rounds
3. **Schedule coverage**: All playable matches appear in the schedule (cascading failures suppressed)
4. **Player conflicts**: No confirmed player double-booked
5. **No double-bye matches**: No match has both players as Bye
6. **Scheduling constraints**: Same-day rule, round time limits, time deadlines, round completion, SF same-time
7. **Potential player conflicts**: Cross-division overlap and rest violations for possible players (FAIL for overlaps, SEVERE for non-Final rest, WARN for Final-involving rest)
8. **Court buffer violations**: Matches scheduled by overriding court breaks
9. **Court preference violations**: Matches on less-preferred courts when better were available

Results are categorized as failures, severe warnings, and warnings.

### Scheduling Trace Log

Every scheduling run writes `scheduling_trace.json` to the schedules output directory. For each match:
- **Scheduled**: match ID, priority, time, court, player1/player2, all possible players, warnings (buffer override, rest relaxation, etc.)
- **Unscheduled**: constraints (earliest/latest/day), all possible players, detailed per-slot rejections (court busy, player conflict with details, potential overlap)
