## Game Scheduling Rules

### Overview

This document describes the general scheduling rules for badminton tournaments. All venue-specific parameters (courts, times, durations) are configured per tournament via YAML files in the tournament's `config/` directory.

### Court Availability

Court availability is defined in `venue.yaml`. Each tournament day specifies:
- Which courts are available
- Start and end times per court group (different courts may close at different times)

Courts that are not available on a given day are automatically excluded from scheduling.

### Match Durations

Match durations are defined in `match_rules.yaml` per division category. A default duration applies to categories not explicitly configured. Matches that exceed one scheduling slot (e.g., a 45-minute match in a 30-minute slot grid) block multiple consecutive slots on the assigned court.

### Rest Periods

Players are entitled to a rest period between consecutive matches. Rest periods are defined in `match_rules.yaml` per division category, with a default for unlisted categories.

### Match Overrun Buffer

Matches may overrun their expected duration. To prevent cascading delays, a configurable `overrun_buffer` (in minutes) can be defined in `match_rules.yaml` per category or as a default for all categories. The buffer creates a time gap between consecutive matches on the same court, absorbing potential overruns.

**How it works:**

When a match has an `overrun_buffer`, the scheduler blocks the court bidirectionally:
- **After the match**: the court is blocked for `match_duration + overrun_buffer` instead of just `match_duration`, preventing the next match from starting too soon.
- **Before the match**: the buffer time before the match start is also reserved, preventing a later-scheduled match from being placed too close before it.

This bidirectional blocking is necessary because matches are scheduled in priority order — higher-priority matches (e.g., Elite) are placed first, and lower-priority matches fill in around them later. Without the backward reservation, a lower-priority match could be placed immediately before a higher-priority match, leaving no gap for overruns.

**Configuration:**

- `overrun_buffer` is defined in `match_rules.yaml` under `default` and/or per category.
- A typical value is 15 minutes with a 30-minute slot grid, which reserves one additional slot as buffer.
- Setting `overrun_buffer: 0` disables the buffer for that category.

### Court Preferences

Court assignment preferences are defined in `court_preferences.yaml` per division category:
- **Required courts**: Hard constraint — the match must be on one of these courts.
- **Preferred courts**: Tried first, but not mandatory.
- **Fallback courts**: Used when preferred courts are unavailable.
- **Last resort courts**: Used only when all other options are exhausted.

Categories not listed use the default preference chain.

### Division Draw Formats

Draw formats (elimination, round-robin, group+playoff) are auto-detected from the input data. Per-division overrides can be specified in `divisions.yaml` via the `format_overrides` section.

### Scheduling Priorities

Matches are scheduled in priority order as defined in `scheduling.yaml`:
1. Elite pool matches (highest priority — scheduled first)
2. Regular pool / round-robin matches
3. Elimination Round 1 matches
4. Group playoff matches
5. Elimination Round 2 matches
6. Quarter-Finals
7. Semi-Finals
8. Finals (lowest priority — scheduled last)

### Day Constraints

Certain rounds can be constrained to specific days via `scheduling.yaml`. For example, semi-finals and finals may be required to be played on the last day of the tournament.

### Additional Scheduling Rules

- Start times are set at fixed intervals defined by `slot_duration` in `venue.yaml`.
- Matches within the same round of a cup bracket should be scheduled as close together in time as possible.
- No player may be scheduled on two courts at the same time.
- For later-round matches where players are unknown, worst-case player tracing ensures rest constraints are met for all possible players.
- Bye matches are not scheduled (no court time needed).
