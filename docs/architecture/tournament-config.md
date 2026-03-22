# Tournament Configuration Architecture

## Overview

The system supports multiple tournaments, each with its own configuration, input data, and output. Tournament-specific details are separated from the general scheduling and website generation logic via YAML configuration files.

## Tournament Folder Structure

Each tournament lives in its own directory under `tournaments/`:

```
tournaments/<tournament-name>/
├── config/
│   ├── tournament.yaml          # Tournament metadata and input source
│   ├── venue.yaml               # Days, sessions, court availability, court buffers
│   ├── match_rules.yaml         # Match durations and rest periods per category
│   ├── court_preferences.yaml   # Court preferences/restrictions per category and round
│   ├── divisions.yaml           # Division → category mapping, tab display, format overrides
│   └── scheduling.yaml          # Priorities, day constraints, draw formats, scheduling rules
├── input/                       # Input files (Excel workbooks)
├── scraped/                     # Cached web scrape data (avoids re-scraping)
└── output/
    ├── divisions/               # Generated division JSON files
    │   ├── tournament_index.json
    │   └── *.json
    ├── schedules/               # Generated schedule JSON files
    │   ├── schedule_index.json
    │   ├── scheduling_trace.json  # Detailed scheduling trace log
    │   ├── divisions/             # Per-division schedule files
    │   └── *.json                 # Per-session schedule files
    └── webpages/
        └── index.html           # Generated single-page website
```

## Configuration Files

### `tournament.yaml` — Tournament Metadata

Identifies the tournament and how to obtain its data.

```yaml
name: "Kumpoo Tervasulan Eliitti 2025"
description: "Badminton tournament organized by Tervasulka"

input:
  source: excel                  # "excel" or "web"
  excel_file: "Draws Kumpoo Tervasulan Eliitti 2025.XLSX"
  web_url: "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-..."
  full_results: false            # When using web source, scrape match results/scores/durations
```

### `venue.yaml` — Days, Sessions, Court Availability, and Court Buffers

Defines the tournament schedule structure: which days, what time ranges, which courts are available on each day, and how the day is divided into sessions.

```yaml
slot_duration: 15                # Minutes per scheduling slot

# Global court buffers (applied to days without their own court_buffers)
# court_buffers:
#   - courts: [1, 2, 3, 4, 5, 6, 7, 8]
#     duration: 30
#     interval: 120
#     courts_at_once: 4

days:
  - name: "Saturday"
    start_time: "09:00"
    # Per-day court buffers (override global for this day)
    court_buffers:
      - courts: [1, 2, 3, 4, 5, 6, 7, 8]
        duration: 30
        interval: 120            # every 2 hours from day start
        courts_at_once: 4        # rotate: 1-4 then 5-8
    courts:
      - numbers: [1, 2, 3, 4, 5, 6, 7, 8]
        end_time: "20:00"
      - numbers: [9, 10, 11, 12]
        start_time: "09:15"      # Per-group start time (optional)
        end_time: "20:30"
    sessions:
      - name: "Saturday Morning"
        start_time: "09:00"
        end_time: "13:00"

  - name: "Sunday"
    start_time: "09:00"
    court_buffers:
      - courts: [1, 2, 3, 4]
        duration: 30
        interval: 120
        courts_at_once: 2
    courts:
      - numbers: [1, 2, 3, 4]
        end_time: "16:00"
      - numbers: [5, 6, 7, 8]
        end_time: "18:00"
```

Notes:
- Courts with different start/end times on the same day are listed as separate groups.
- Per-group `start_time` is optional (defaults to the day's `start_time`).
- Sessions are display groupings for the website schedule grid; they don't affect scheduling logic.
- `slot_duration` determines the scheduling granularity (all match start times are multiples of this).
- Court buffers are per-day. Days without `court_buffers` inherit the global config. Set to empty list to disable for a day.

### `court_preferences.yaml` — Court Preferences per Category and Round

Controls which courts each division category prefers or is restricted to.

```yaml
categories:
  Elite:
    required_courts: [5, 6, 7, 8]
  Open A:
    preferred_courts: [5, 6, 7, 8]
    fallback_courts: [1, 2, 3, 4]
  Junior:
    required_courts: [9, 10, 11, 12]
    round_overrides:                  # Per-round court preference overrides
      "Semi-Final":
        required_courts: null         # Clear the hard constraint for SF
        preferred_courts: [9, 10, 11, 12]
        fallback_courts: [5, 6, 7, 8]
      "Final":
        required_courts: null
        preferred_courts: [5, 6, 7, 8]
        fallback_courts: [9, 10, 11, 12]
    day_overrides:
      Sunday:
        required_courts: null
        preferred_courts: [1, 2, 3, 4]
        fallback_courts: [5, 6, 7, 8]
  Veterans:
    preferred_courts: [1, 2, 3, 4]
    fallback_courts: [5, 6, 7, 8]

default:
  preferred_courts: [5, 6, 7, 8]
  fallback_courts: [1, 2, 3, 4]

# Global round preferences (override category for specific rounds)
# Does not apply to categories with required_courts
round_court_preferences:
  "Final":
    preferred_courts: [5, 6, 7, 8]
    fallback_courts: [1, 2, 3, 4]
  "Semi-Final":
    preferred_courts: [5, 6, 7, 8]
    fallback_courts: [1, 2, 3, 4]
```

Notes:
- `required_courts` is a hard constraint — the match will fail to schedule if none are available.
- `round_overrides` within a category allow different courts for specific rounds (e.g., Junior Finals on center courts).
- `round_court_preferences` apply globally but skip categories with `required_courts`.
- Override precedence: round_overrides > day_overrides > base category > default.

### `scheduling.yaml` — Scheduling Priorities and Rules

The central configuration file for all scheduling behavior.

```yaml
# Scheduling priorities (lower number = scheduled first)
priorities:
  rounds:                          # Base priorities by round type
    "Round 1": 10
    "Round 2": 20
    "Pool": 30
    "Quarter-Final": 50
    "Semi-Final": 60
    "Final": 70

  categories:                      # Per-category overrides
    Elite:
      "Pool": 5

  divisions:                       # Per-division overrides (highest precedence)
    "MS C":
      "Round 1": 5
    "MD A":
      "Quarter-Final": 15

  day_overrides:                   # Different priorities on different days
    Sunday:
      rounds:                      # Round-level defaults for Sunday
        "Quarter-Final": 25
        "Semi-Final": 35
        "Final": 45
      divisions:                   # Division-specific overrides for Sunday
        "MS C":
          "Quarter-Final": 20

# Global day constraints
day_constraints:
  - rounds: ["Semi-Final", "Final"]
    day: "Sunday"

# Per-division day constraints
division_day_constraints:
  "MS C":
    - rounds: ["Quarter-Final", "Semi-Final", "Final"]
      day: "Sunday"
  "BS U13":
    - rounds: ["Semi-Final", "Final"]
      day: "Saturday"

# Semi-final same-time scheduling
semi_final_same_time: true         # Both SFs of a division at same time slot

# Round completion
round_completion:
  enabled: true
  exceptions: ["MD C"]             # Divisions exempt from the rule

# Potential conflict avoidance
potential_conflict_avoidance:
  default:
    rounds: ["Round 2", "Quarter-Final", "Semi-Final", "Final"]
  categories:
    Junior:
      rounds: ["Semi-Final", "Final"]

# Round time limits (soft constraint)
round_time_limit:
  rounds:
    "Quarter-Final": 120
  categories:
    Junior:
      "Pool": 300

# Time deadlines
time_deadlines:
  - rounds: ["Round 1"]
    divisions: ["MS C", "MS B"]
    deadline: "Saturday 12:00"

# Draw format overrides (for entries-only input)
draw_formats:
  default: elimination
  categories:
    Veterans: round_robin
  divisions:
    "BS U17":
      format: group_playoff
      groups: 4
      advancers_per_group: 2

# Match durations
match_duration:
  default: 30
  categories:
    Elite: 45
    "Open A": 40
  divisions:
    "XD A": 30

# Overrun buffer
overrun_buffer:
  default: 0
  categories:
    Elite: 15

# Rest rules
rest_rules:
  same_division_rest:
    default: 30
    divisions:
      "MS V": 180
  same_category_rest:
    default: 30
    categories:
      Elite: 120
  cross_division_rest: 30
  player_exceptions:
    "Player Name":
      - between: ["MS A", "MD A"]
        rest: 0

# Match density
match_density:
  max_matches: 3
  time_window: 180
  player_exceptions:
    "Player Name":
      max_matches: 4
      time_window: 180
```

### `divisions.yaml` — Division Categories and Display

Maps division codes to categories for website tab grouping and display. (See existing documentation — unchanged.)

## Config Resolution Rules

1. **Missing config file**: Sensible defaults are used.
2. **Missing category**: Uses the `default` section.
3. **Court availability**: Courts not available on a day are silently skipped.
4. **Category key aliases**: Both level codes (`"A"`) and full names (`"Open A"`) work in `match_duration`, `overrun_buffer`, and `same_category_rest`.
5. **Priority resolution**: day_overrides.divisions > day_overrides.rounds > divisions > categories > rounds > fallback.
6. **Day inference**: When SF/Final has an explicit day constraint, earlier rounds (QF, R2) in the same division have their priorities resolved with the inferred day for day_overrides.

## Input Modes

The system supports three input modes:

1. **Excel draws**: `parse_tournament.py` reads bracket/group draws from Excel. Supports dynamic column layout detection (works with both 2025-style and 2026-style column formats).
2. **Web scraping**: `parse_web.py` scrapes from tournamentsoftware.com. Falls back to entries-only mode when draws aren't published.
3. **Entries only**: `parse_entries.py` reads player lists and generates random draws using `draw_formats` config. Used automatically when Excel/web parsing finds no draws.

All three produce identical JSON output format — downstream pipeline is shared.

## CLI

```bash
# Full pipeline:
python src/main.py --tournament tournaments/kumpoo-2026
python src/main.py --tournament tournaments/kumpoo-2026 --source web
python src/main.py --tournament tournaments/kumpoo-2026 --source excel --seed 42

# Individual scripts:
python src/parse_tournament.py --tournament tournaments/kumpoo-2026
python src/parse_web.py --tournament tournaments/kumpoo-2026
python src/parse_entries.py --tournament tournaments/kumpoo-2026 --seed 42
python src/generate_schedule.py --tournament tournaments/kumpoo-2026
python src/verify_schedule.py --tournament tournaments/kumpoo-2026
python src/generate_website.py --tournament tournaments/kumpoo-2026
```
