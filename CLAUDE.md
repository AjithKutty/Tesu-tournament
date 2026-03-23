# Badminton Tournament Website Generator

Generates match schedules and single-page HTML websites for badminton tournaments. Reads draw data from either an Excel export, a tournamentsoftware.com URL, or an entries-only player list. Each tournament has its own configuration, input, and output directory.

## Agent Behavior

- **Do not commit automatically.** Changes should only be committed when the user explicitly asks to commit. The agent may propose committing (e.g., "Should I commit these changes?"), but must not proceed with `git add` or `git commit` until the user confirms. Never combine implementation and commit in the same response.

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                      # Unified entry point (runs all steps)
│   ├── parse_tournament.py          # Excel draws → JSON parser
│   ├── parse_web.py                 # Web scraper → JSON parser (same output format)
│   ├── parse_entries.py             # Entries-only Excel → random draws → JSON
│   ├── generate_schedule.py         # JSON → schedule JSON
│   ├── verify_schedule.py           # Schedule verification (9 checks)
│   ├── generate_website.py          # JSON → HTML website
│   └── config.py                    # Configuration loading and resolution
├── tournaments/
│   └── <tournament-name>/           # One folder per tournament
│       ├── config/
│       │   ├── tournament.yaml      # Name, description, input source
│       │   ├── venue.yaml           # Days, sessions, courts, buffers, slot duration
│       │   ├── match_rules.yaml     # Match durations, rest periods per category
│       │   ├── court_preferences.yaml # Court preferences per category and round
│       │   ├── divisions.yaml       # Division → category mapping, tabs, format overrides
│       │   └── scheduling.yaml      # Priorities, day constraints, scheduling rules
│       ├── input/                   # Input files (Excel workbooks)
│       ├── scraped/                 # Cached web scrape data
│       └── output/
│           ├── divisions/           # Generated division JSON files
│           ├── schedules/           # Schedule JSON + trace + per-division schedules
│           └── webpages/            # Generated HTML website
├── docs/
│   ├── requirements/
│   │   ├── requirements.md
│   │   └── scheduling-rules.md     # Comprehensive scheduling rules documentation
│   ├── architecture/
│   │   ├── scheduling-proposal.md
│   │   └── tournament-config.md    # Config file architecture and format
│   └── implementation/
│       ├── implementation-plan.md
│       ├── website-schedule-plan.md
│       └── web-scraper-plan.md
├── requirements.txt                 # Python deps (openpyxl, requests, beautifulsoup4, lxml, pyyaml)
└── CLAUDE.md
```

## Workflow

```bash
# Run full pipeline for a tournament:
python src/main.py --tournament tournaments/kumpoo-2025

# Override input source via CLI:
python src/main.py --tournament tournaments/kumpoo-2025 --source web
python src/main.py --tournament tournaments/kumpoo-2025 --source web --full-results

# Entries-only with reproducible random draws:
python src/main.py --tournament tournaments/kumpoo-2026 --source excel --seed 42

# Web scraping with actual winner names in later bracket rounds:
python src/main.py --tournament tournaments/kumpoo-2025 --source web --get-winners
```

The pipeline:
```
Tournament Config (YAML) ──────────────────────────┐
        │                                          │
Excel (.XLSX) or Web URL or Entries Excel          │
        │                                          │
        ▼                                          ▼
  parse_tournament.py / parse_web.py  →  output/divisions/*.json
  parse_entries.py (entries only)      →  output/divisions/*.json
  generate_schedule.py  ← config      →  output/schedules/*.json
  verify_schedule.py    ← config      →  9 verification checks
  generate_website.py   ← config      →  output/webpages/index.html
```

Individual scripts can still be run standalone with `--tournament`:
1. `python src/parse_tournament.py --tournament tournaments/kumpoo-2025`
2. `python src/parse_web.py --tournament tournaments/kumpoo-2025`
3. `python src/parse_entries.py --tournament tournaments/kumpoo-2026 --seed 42`
4. `python src/generate_schedule.py --tournament tournaments/kumpoo-2025`
5. `python src/verify_schedule.py --tournament tournaments/kumpoo-2025`
6. `python src/generate_website.py --tournament tournaments/kumpoo-2025`

## Key Conventions

- **Do not hand-edit files under `tournaments/*/output/`** — they are generated. Change source scripts or config instead.
- Python 3 with `openpyxl`, `requests`, `beautifulsoup4`, `lxml`, `pyyaml`. Install via `pip install -r requirements.txt`.
- No template engines or frontend frameworks — pure Python string formatting for HTML generation.
- Website tabs are derived from categories present in the data and configured in `divisions.yaml`.
- All three input modes (Excel draws, web, entries-only) produce identical JSON output format — downstream pipeline is shared.
- The scheduling algorithm is deterministic — same config and input always produces the same output.

## Tournament Configuration

Each tournament is configured via 6 YAML files in `tournaments/<name>/config/`. See `docs/architecture/tournament-config.md` for full specification.

| Config file | Purpose |
|---|---|
| `tournament.yaml` | Tournament name, description, input source |
| `venue.yaml` | Days, sessions, court availability, per-group start times, slot duration, court buffers |
| `match_rules.yaml` | Match durations and rest periods per category |
| `court_preferences.yaml` | Court preferences per category, round overrides, global round preferences |
| `divisions.yaml` | Event names, level→category mapping, tab display, format overrides |
| `scheduling.yaml` | Priorities (hierarchical with day overrides), day constraints, draw formats, round completion, SF same-time, potential conflict avoidance, round time limits, time deadlines, match density, rest rules with player exceptions |

## Input Modes

### Excel draws
`parse_tournament.py` reads bracket/group draws from Excel workbooks. Supports dynamic column layout detection — works with varying column positions (2025-style: A=pos, B=status, C=club, D=flag, E=player; 2026-style: A=pos, B=club, C=player).

### Web scraping
`parse_web.py` scrapes from tournamentsoftware.com. When draws aren't published, automatically falls back to entries-only mode (scraping player lists from event.aspx). Filters out "Exclude list" and "Reserve list" entries.

### Entries only
`parse_entries.py` reads player entry lists and generates randomized draws using `draw_formats` config from `scheduling.yaml`. Use `--seed` for reproducible draws. Called automatically by `main.py` when Excel/web parsing finds no draws.

## Schedule Generator (generate_schedule.py)

Generates match schedules respecting court availability, player rest, and round ordering. All constraints are read from the tournament's config files.

- **Courts**: Defined in `venue.yaml` — days, court numbers, per-court-group start/end times
- **Court buffers**: Per-day periodic breaks configured in `venue.yaml`
- **Match durations**: From `scheduling.yaml` — per division, per category, or default
- **Rest periods**: Context-dependent with same-division, same-category, and cross-division rules. Per-player exceptions supported.
- **Match density**: Max matches within a time window per player
- **Court preferences**: Required/preferred/fallback/last-resort per category, with round and day overrides
- **Scheduling priorities**: Hierarchical — base rounds, per-category, per-division, per-day overrides
- **Same-day rule**: All matches in the same round of the same division on a single day (automatic)
- **Day constraints**: Global and per-division day pinning
- **Round completion**: All matches in a round finish before next round starts (configurable)
- **Round time limits**: Soft constraint on time span within a round (verifier reports violations)
- **Time deadlines**: Rounds must finish by a specific day+time
- **Semi-final pair scheduling**: Both SFs of a division at same time on 2 courts, with Final-aware latest bound
- **Potential conflict avoidance**: Trace all possible players through brackets, prevent overlaps/rest violations for configured rounds
- **Bye resolution**: Bye winners' names propagated to later rounds
- **Fallback chain**: Normal → buffer override → round time limit relaxation → cross-division rest relaxation
- **Scheduling trace**: Detailed `scheduling_trace.json` with per-match placement decisions and rejection reasons

## Verify Schedule (verify_schedule.py)

9 independent verification checks:

1. **Bracket completeness**: Correct number of matches per round
2. **Round ordering**: Prerequisites scheduled before dependents
3. **Schedule coverage**: All playable matches scheduled (cascading failures suppressed)
4. **Player conflicts**: No confirmed double-bookings
5. **No double-bye matches**: No Bye-vs-Bye
6. **Scheduling constraints**: Same-day, round time limits, deadlines, round completion, SF same-time
7. **Potential player conflicts**: Cross-division overlap (FAIL), rest without Final (SEVERE), rest with Final (WARN)
8. **Court buffer violations**: Matches overriding buffer breaks
9. **Court preference violations**: Matches on non-preferred courts when better available

Results categorized as failures, severe warnings, and warnings.

## Website Generator (generate_website.py)

Generates a self-contained single-page HTML website with inline CSS and vanilla JavaScript.

- **Tournament name**: Read from `tournament.yaml` for title, header, and footer
- **Tab structure**: Derived from categories in data + tab order from `divisions.yaml`
- **Schedule cross-reference**: Lookup keyed by `(division_code, round_name, match_num)` → time/court/date annotation on match cards
- **Bracket rendering**: Tree-style CSS connectors using `::before`/`::after` pseudo-elements (not SVG)
- **Schedule grid**: Time rows × court columns with configurable slot duration; multi-slot matches use dynamic `rowspan`; match time shown on each card
- **Responsive**: Mobile breakpoint at 600px with horizontal scroll for tables and brackets

## Testing Changes

After modifying any script, run the full pipeline:
```bash
python src/main.py --tournament tournaments/kumpoo-2025
python src/main.py --tournament tournaments/kumpoo-2025 --source web
python src/main.py --tournament tournaments/kumpoo-2026 --source excel --file "tournaments/kumpoo-2026/input/Draws Kumpoo Tervasulan Eliitti 2026.XLSX"
```
Then open `tournaments/<name>/output/webpages/index.html` in a browser and verify:
- All category tabs present in the data work correctly
- Elimination divisions show full bracket (R1 through Final) with tree-style connectors
- Group+playoff divisions show groups + playoff bracket
- Round-robin divisions show VS match cards
- Schedule annotations (time + court) on match cards
- Schedule tab shows session sub-tabs with time × court grids at configured slot duration
- Multi-slot matches (e.g., 40-min Open A) span correct number of rows in schedule grid
- No "Bye" entries in player lists

Check `output/schedules/scheduling_trace.json` for scheduling decisions and `verify_schedule.py` output for constraint violations.

## Creating a New Tournament

1. Create `tournaments/<name>/` with subdirectories: `config/`, `input/`, `scraped/`, `output/`
2. Copy and modify the 6 YAML config files from an existing tournament
3. Place input Excel file in `input/` (or configure web URL in `tournament.yaml`)
4. Run: `python src/main.py --tournament tournaments/<name>`
