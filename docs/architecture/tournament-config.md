# Tournament Configuration Architecture

## Overview

The system supports multiple tournaments, each with its own configuration, input data, and output. Tournament-specific details are separated from the general scheduling and website generation logic via YAML configuration files.

## Tournament Folder Structure

Each tournament lives in its own directory under `tournaments/`:

```
tournaments/<tournament-name>/
├── config/
│   ├── tournament.yaml          # Tournament metadata and input source
│   ├── venue.yaml               # Days, sessions, court availability
│   ├── match_rules.yaml         # Match durations and rest periods per category
│   ├── court_preferences.yaml   # Court preferences/restrictions per category
│   ├── divisions.yaml           # Division → category mapping, tab display, format overrides
│   └── scheduling.yaml          # Priority ordering, SF/Final constraints
├── input/                       # Input files (Excel workbooks, etc.)
├── scraped/                     # Cached web scrape data (avoids re-scraping)
└── output/
    ├── divisions/               # Generated division JSON files
    │   ├── tournament_index.json
    │   └── *.json
    ├── schedules/               # Generated schedule JSON files
    │   ├── schedule_index.json
    │   └── *.json
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
  excel_file: "Draws Kumpoo Tervasulan Eliitti 2025 vain kaaviot.XLSX"
  web_url: "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-..."
  full_results: false            # When using web source, scrape match results/scores/durations
```

### `venue.yaml` — Days, Sessions, and Court Availability

Defines the tournament schedule structure: which days, what time ranges, which courts are available on each day, and how the day is divided into sessions.

```yaml
slot_duration: 30                # Minutes per scheduling slot

days:
  - name: "Saturday"
    start_time: "09:00"
    courts:
      - numbers: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        end_time: "22:00"
    sessions:
      - name: "Saturday Morning"
        start_time: "09:00"
        end_time: "13:00"
      - name: "Saturday Afternoon"
        start_time: "13:00"
        end_time: "18:00"
      - name: "Saturday Evening"
        start_time: "18:00"
        end_time: "22:00"

  - name: "Sunday"
    start_time: "09:00"
    courts:
      - numbers: [1, 2, 3, 4]
        end_time: "16:00"
      - numbers: [5, 6, 7, 8]
        end_time: "18:00"
    sessions:
      - name: "Sunday Morning"
        start_time: "09:00"
        end_time: "13:00"
      - name: "Sunday Afternoon"
        start_time: "13:00"
        end_time: "18:00"
```

Notes:
- Courts with different end times on the same day are listed as separate groups.
- Sessions are display groupings for the website schedule grid; they don't affect scheduling logic.
- `slot_duration` determines the scheduling granularity (all match start times are multiples of this).

### `match_rules.yaml` — Match Durations and Rest Periods

Defines how long matches last and how much rest players get, per division category.

```yaml
default:
  match_duration: 30             # Minutes
  rest_period: 30                # Minutes between matches for same player

categories:
  Elite:
    match_duration: 45
    rest_period: 60
    overrun_buffer: 15           # Extra minutes of court gap before Elite matches
```

Notes:
- Any category not listed under `categories` uses the `default` values.
- A match occupying more than one slot duration (e.g., 45 min with 30 min slots) blocks multiple consecutive slots on the court.
- `overrun_buffer` ensures punctuality for the category's matches: the scheduler requires this many extra minutes of free court time before the match starts, absorbing potential overruns from the preceding match on the same court. Only applies to categories that define it.

### `court_preferences.yaml` — Court Preferences per Category

Controls which courts each division category prefers or is restricted to.

```yaml
categories:
  Elite:
    required_courts: [5, 6, 7, 8]        # Hard constraint — must use these courts
  Open A:
    preferred_courts: [5, 6, 7, 8]       # Try these first
    fallback_courts: [1, 2, 3, 4]        # Then these
    last_resort_courts: [9, 10, 11, 12]  # Only if nothing else available
  Junior:
    required_courts: [9, 10, 11, 12]     # Saturday: must use courts 9-12
    day_overrides:
      Sunday:                            # On Sunday (courts 9-12 unavailable):
        required_courts: null            #   clear the hard constraint
        preferred_courts: [1, 2, 3, 4]   #   prefer courts 1-4 instead
        fallback_courts: [5, 6, 7, 8]

default:
  preferred_courts: [1, 2, 3, 4]
  fallback_courts: [9, 10, 11, 12]
  last_resort_courts: [5, 6, 7, 8]
```

Notes:
- `required_courts` is a hard constraint — the match will fail to schedule if none are available.
- `preferred_courts` → `fallback_courts` → `last_resort_courts` is a soft preference chain.
- Court numbers that don't exist on a given day (e.g., courts 9-12 on Sunday) are automatically excluded.
- Categories not listed use the `default` preference.
- `day_overrides` allows per-day court preferences within a category. The day name must match a day in `venue.yaml`. Day-specific values override the base category values; set a key to `null` to clear a base constraint (e.g., clearing `required_courts` on a day where those courts are unavailable).

### `divisions.yaml` — Division Categories and Display

Maps division codes to categories for website tab grouping and display.

```yaml
# Event code → full name mapping
event_names:
  MS: "Men's Singles"
  WS: "Women's Singles"
  MD: "Men's Doubles"
  WD: "Women's Doubles"
  XD: "Mixed Doubles"
  BS: "Boys' Singles"
  BD: "Boys' Doubles"

# Level → category mapping
level_categories:
  A: "Open A"
  B: "Open B"
  C: "Open C"
  U11: "Junior"
  U13: "Junior"
  U15: "Junior"
  U17: "Junior"
  "35": "Veterans"
  "45": "Veterans"
  V: "Elite"

# Website tab display order and styling
tabs:
  - category: "Open A"
    tab_id: "opena"
    badge_class: "badge-open"
  - category: "Open B"
    tab_id: "openb"
    badge_class: "badge-open"
  - category: "Open C"
    tab_id: "open"
    badge_class: "badge-open"
  - category: "Junior"
    tab_id: "junior"
    badge_class: "badge-junior"
  - category: "Veterans"
    tab_id: "veterans"
    badge_class: "badge-veterans"
  - category: "Elite"
    tab_id: "elite"
    badge_class: "badge-elite"

# Doubles event codes (for parsing)
doubles_events: ["MD", "WD", "XD", "BD"]

# Optional: override auto-detected draw format for specific divisions
# format_overrides:
#   "BS U17": "group_playoff"
#   "MS C": "elimination"
```

Notes:
- Only categories present in the actual tournament data will appear as tabs on the website.
- The `tabs` list defines the display order; categories not in the list but present in the data will be appended at the end.
- `format_overrides` is optional — by default, formats are auto-detected from the input data (Excel column headers or web page metadata).

### `scheduling.yaml` — Scheduling Priorities and Rules

Controls the priority ordering for match scheduling and special day constraints.

```yaml
# Priority levels (lower number = scheduled first)
priorities:
  elite_pool: 5
  pool: 10
  round_1: 20
  group_playoff: 30
  round_2: 40
  quarter_final: 50
  semi_final: 60
  final: 70

# Which round names map to which priority
round_priority_map:
  "Round 1": round_1
  "Round 2": round_2
  "Quarter-Final": quarter_final
  "Semi-Final": semi_final
  "Final": final

# Division codes that get elite_pool priority for their pool matches
elite_divisions: ["MS V", "WS V", "XD V"]

# Rounds that must be scheduled on a specific day
day_constraints:
  - rounds: ["Semi-Final", "Final"]
    day: "Sunday"                # Must match a day name from venue.yaml
```

## Config Resolution Rules

1. **Missing config file**: If a config file is missing, sensible defaults are used (e.g., all courts have equal preference, 30 min match/rest, no day constraints).
2. **Missing category**: Categories not explicitly listed in `match_rules.yaml` or `court_preferences.yaml` use the `default` section.
3. **Court availability**: Courts listed in preferences but not available on a particular day (per `venue.yaml`) are silently skipped.
4. **Tab generation**: The website only creates tabs for categories that have at least one division in the tournament data. Tab order follows `divisions.yaml`; unlisted categories are appended alphabetically.

## CLI Changes

The `main.py` CLI accepts a `--tournament` argument pointing to the tournament directory:

```bash
# Run full pipeline for a tournament:
python src/main.py --tournament tournaments/kumpoo-2025

# Override input source via CLI (takes precedence over tournament.yaml):
python src/main.py --tournament tournaments/kumpoo-2025 --source web --url "..."

# Individual scripts also accept --tournament:
python src/parse_tournament.py --tournament tournaments/kumpoo-2025
python src/generate_schedule.py --tournament tournaments/kumpoo-2025
python src/generate_website.py --tournament tournaments/kumpoo-2025
```
