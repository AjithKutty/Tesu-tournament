# Badminton Tournament Website Generator

A configurable badminton tournament website generator that reads draw data from either an Excel export or a [tournamentsoftware.com](https://tournamentsoftware.com) URL, generates match schedules, and builds a self-contained single-page HTML website.

Each tournament has its own directory with YAML configuration files defining venue, courts, match rules, and division categories — no code changes needed to set up a new tournament.

## Features

- **Multi-tournament support**: Each tournament gets its own config, input, and output directory
- **YAML configuration**: Venue, courts, match rules, court preferences, divisions, and scheduling priorities are all configurable per tournament
- **Dual input modes**: Parse draws from an Excel workbook (Badminton Finland export) or scrape directly from tournamentsoftware.com
- **Scrape caching**: Web-scraped data is cached locally to avoid redundant HTTP requests
- **Automatic schedule generation**: Greedy scheduling algorithm with configurable court preferences, rest periods, round ordering, and worst-case rest buffering
- **Single-page website**: Tabbed sections derived from tournament divisions, with collapsible division cards
- **Bracket visualization**: Tree-style elimination brackets with CSS connectors
- **Schedule grid**: Time x court grid with session sub-tabs
- **Self-contained output**: Single HTML file with inline CSS and vanilla JavaScript — no external dependencies

## Prerequisites

- Python 3.6+
- pip

## Installation

1. Clone the repository:

   ```bash
   git clone <repository-url>
   cd Tesu-tournament
   ```

2. (Optional) Create and activate a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate        # Linux/macOS
   venv\Scripts\activate           # Windows
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   This installs: `openpyxl`, `requests`, `beautifulsoup4`, `lxml`, `pyyaml`.

## Quick Start

```bash
# Run the full pipeline for an existing tournament:
python src/main.py --tournament tournaments/kumpoo-2025

# View the generated website:
open tournaments/kumpoo-2025/output/webpages/index.html       # macOS
start tournaments/kumpoo-2025/output/webpages/index.html      # Windows
xdg-open tournaments/kumpoo-2025/output/webpages/index.html   # Linux
```

## Usage

### Full pipeline (recommended)

Run all three steps (parse, schedule, generate website) in one command:

```bash
# Using tournament config defaults (input source from tournament.yaml):
python src/main.py --tournament tournaments/kumpoo-2025

# Override to use Excel input:
python src/main.py --tournament tournaments/kumpoo-2025 --source excel --file "path/to/draws.xlsx"

# Override to use web scraping:
python src/main.py --tournament tournaments/kumpoo-2025 --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

# Web scraping with match results, scores, and durations:
python src/main.py --tournament tournaments/kumpoo-2025 --source web --full-results
```

### Individual scripts

Each pipeline stage can be run independently:

```bash
# 1a. Parse Excel draws → JSON
python src/parse_tournament.py --tournament tournaments/kumpoo-2026

# 1b. (Alternative) Scrape web → JSON
python src/parse_web.py --tournament tournaments/kumpoo-2026

# 1c. (Alternative) Parse entries Excel → random draws → JSON
python src/parse_entries.py --tournament tournaments/kumpoo-2026 --seed 42

# 2. Generate schedule from division JSON
python src/generate_schedule.py --tournament tournaments/kumpoo-2026

# 3. Verify schedule (optional)
python src/verify_schedule.py --tournament tournaments/kumpoo-2026

# 4. Generate website from divisions + schedule JSON
python src/generate_website.py --tournament tournaments/kumpoo-2026
```

## Pipeline

```
Tournament Config (YAML) ──────────────────────────┐
        │                                          │
Excel (.XLSX) or Web URL or Entries Excel          │
        │                                          │
        ▼                                          ▼
  parse_tournament.py / parse_web.py  →  output/divisions/*.json
  parse_entries.py (entries only)      →  output/divisions/*.json
  generate_schedule.py  ← config      →  output/schedules/*.json
  generate_website.py   ← config      →  output/webpages/index.html
```

## Tournament Directory Structure

Each tournament lives in its own folder under `tournaments/`:

```
tournaments/kumpoo-2025/
├── config/
│   ├── tournament.yaml          # Name, description, input source
│   ├── venue.yaml               # Days, sessions, court availability
│   ├── match_rules.yaml         # Match durations and rest periods per category
│   ├── court_preferences.yaml   # Court preferences/restrictions per category
│   ├── divisions.yaml           # Division → category mapping, tab styling, format overrides
│   └── scheduling.yaml          # Priorities, day constraints
├── input/                       # Input files (Excel workbooks)
├── scraped/                     # Cached web scrape data
└── output/                      # Generated files (git-ignored)
    ├── divisions/               # One JSON per division + tournament_index.json
    ├── schedules/               # One JSON per session + schedule_index.json + scheduling_trace.json
    └── webpages/                # index.html — the final single-page website
```

## Configuration

Tournament behavior is controlled by 6 YAML config files. See `docs/architecture/tournament-config.md` for the full specification.

| Config file | Purpose | Key settings |
|---|---|---|
| `tournament.yaml` | Tournament identity | Name, description, default input source |
| `venue.yaml` | Venue and schedule | Days, start/end times, court groups, session boundaries, slot duration |
| `match_rules.yaml` | Match timing | Duration and rest period per category (e.g., Elite: 45 min match, 60 min rest) |
| `court_preferences.yaml` | Court assignment | Required/preferred/fallback courts per category |
| `divisions.yaml` | Division mapping | Event names, level→category mapping, website tab order and styling, format overrides |
| `scheduling.yaml` | Scheduling logic | Priority ordering, day constraints, draw format overrides for entries-only mode |

## Creating a New Tournament

1. Create the tournament directory structure:

   ```bash
   mkdir -p tournaments/my-tournament/config
   mkdir -p tournaments/my-tournament/input
   mkdir -p tournaments/my-tournament/scraped
   mkdir -p tournaments/my-tournament/output
   ```

2. Copy config files from an existing tournament and modify them:

   ```bash
   cp tournaments/kumpoo-2025/config/*.yaml tournaments/my-tournament/config/
   ```

3. Edit the config files for your tournament:
   - `tournament.yaml` — set the tournament name and input source
   - `venue.yaml` — define your days, courts, and sessions
   - `match_rules.yaml` — set match durations and rest periods
   - `court_preferences.yaml` — set court preferences per category
   - `divisions.yaml` — define your event names, categories, and website tabs
   - `scheduling.yaml` — set priorities and day constraints

4. Place input files (Excel workbook) in the `input/` directory, or configure the web URL in `tournament.yaml`.

5. Run the pipeline:

   ```bash
   python src/main.py --tournament tournaments/my-tournament
   ```

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                  # Unified entry point (parse → schedule → website)
│   ├── parse_tournament.py      # Excel draws → JSON parser
│   ├── parse_web.py             # Web scraper → JSON parser
│   ├── parse_entries.py         # Entries-only Excel → random draws → JSON
│   ├── generate_schedule.py     # JSON → schedule JSON
│   ├── verify_schedule.py       # Schedule verification checks
│   └── generate_website.py      # JSON → single-page HTML
├── tournaments/                 # One folder per tournament (config + input + output)
├── docs/
│   ├── requirements/            # Functional & scheduling requirements
│   ├── architecture/            # Config architecture, scheduling algorithm design
│   └── implementation/          # Implementation plans
├── requirements.txt
└── CLAUDE.md                    # AI assistant project instructions
```

## Input Formats

The pipeline supports three input modes depending on what data is available.

### Excel mode (draws available)

Expects an `.xlsx` workbook exported from tournamentsoftware.com with one sheet per division draw. Supports three draw formats:

- **Elimination bracket** — standard knockout draws (detected by "Round 1" header)
- **Round-robin** — all-vs-all pools (detected by numbered column headers)
- **Group + Playoff** — group stages followed by a knockout bracket

Format detection is automatic. Per-division overrides can be specified in `divisions.yaml`.

### Web scraping mode (draws available)

Scrapes tournament data directly from tournamentsoftware.com. Handles cookie consent walls automatically. Scraped data is cached in the tournament's `scraped/` directory.

Note: club-per-player data is not available from the web (only country codes).

The `--full-results` flag additionally scrapes match results, scores, durations, scheduled times, and court assignments.

### Entries-only mode (no draws yet)

When only a player entry list is available (no bracket draws), `parse_entries.py` reads the entries Excel and generates randomized draws. This is useful for pre-tournament scheduling when draws haven't been made yet.

The entries Excel has one sheet per division named `{EVENT} {LEVEL} - Main Draw` (e.g., `MS B - Main Draw`), with columns: No., Name (and partner on the next row for doubles).

```bash
# Generate random draws from entries and run the full pipeline:
python src/parse_entries.py --tournament tournaments/kumpoo-2026 --seed 42
python src/generate_schedule.py --tournament tournaments/kumpoo-2026
python src/generate_website.py --tournament tournaments/kumpoo-2026

# Use --seed for reproducible draws (omit for fully random)
```

#### Draw format configuration

The draw format for each division is controlled by the `draw_formats` section in `scheduling.yaml`. This determines whether a division plays as round-robin, elimination, or group stage with playoffs.

```yaml
draw_formats:
  # Default for divisions with >6 entries (<=6 always use round_robin)
  default: elimination

  # Per-category defaults
  categories:
    Veterans: round_robin

  # Per-division overrides (take precedence over category and default)
  divisions:
    "BS U13":
      format: group_playoff
      groups: 2                  # Number of round-robin groups
      advancers_per_group: 2     # Top 2 per group → 4 in playoff → SF + Final
    "MD 35":
      format: group_playoff
      groups: 2
      advancers_per_group: 1     # Top 1 per group → 2 in playoff → Final only
```

Resolution order: per-division override → per-category default → global default → fallback (round_robin if ≤6 entries, elimination otherwise).

## License

## Scheduling Trace Log

Every scheduling run writes a detailed trace log to `tournaments/<name>/output/schedules/scheduling_trace.json`. This log records the outcome of every match placement attempt:

- **Scheduled matches**: match ID, priority, placed time, and court number
- **Unscheduled matches**: match ID, constraints (earliest/latest time bounds, day), effective players, number of slots tried, and the last 10 rejection reasons

Rejection reasons include specific details to help diagnose scheduling failures:
- `"player conflict: Player Name needs 30min rest after Division X"` — rest period violation
- `"player conflict: Player Name exceeds 3 matches in 180min"` — match density limit
- `"court busy"` — no court available at this slot
- `"past latest bound Saturday 20:00"` — time deadline or same-day constraint exceeded
- `"prerequisite failed: DIV:Round 1:M3"` — a feeder match couldn't be scheduled
- `"previous round incomplete: Round 1 has unscheduled [...]"` — round-completion constraint

## License

This project is not currently licensed for distribution.
