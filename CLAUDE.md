# Badminton Tournament Website Generator

Generates match schedules and single-page HTML websites for badminton tournaments. Reads draw data from either an Excel export or a tournamentsoftware.com URL. Each tournament has its own configuration, input, and output directory.

## Agent Behavior

- **Do not commit automatically.** Changes should only be committed when the user explicitly asks to commit. The agent may propose committing (e.g., "Should I commit these changes?"), but must not proceed with `git add` or `git commit` until the user confirms. Never combine implementation and commit in the same response.

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                      # Unified entry point (runs all 3 steps)
│   ├── parse_tournament.py          # Excel → JSON parser
│   ├── parse_web.py                 # Web scraper → JSON parser (same output format)
│   ├── generate_schedule.py         # JSON → schedule JSON
│   └── generate_website.py          # JSON → HTML website
├── tournaments/
│   └── <tournament-name>/           # One folder per tournament
│       ├── config/
│       │   ├── tournament.yaml      # Name, description, input source
│       │   ├── venue.yaml           # Days, sessions, courts, end times
│       │   ├── match_rules.yaml     # Match durations, rest periods per category
│       │   ├── court_preferences.yaml # Court preferences per category
│       │   ├── divisions.yaml       # Division → category mapping, tabs, format overrides
│       │   └── scheduling.yaml      # Priorities, day constraints
│       ├── input/                   # Input files (Excel workbooks)
│       ├── scraped/                 # Cached web scrape data
│       └── output/
│           ├── divisions/           # Generated division JSON files
│           ├── schedules/           # Generated schedule JSON files
│           └── webpages/            # Generated HTML website
├── docs/
│   ├── requirements/
│   │   ├── requirements.md
│   │   └── scheduling-rules.md
│   ├── architecture/
│   │   ├── scheduling-proposal.md
│   │   └── tournament-config.md     # Config file architecture and format
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

# Web scraping with actual winner names in later bracket rounds:
python src/main.py --tournament tournaments/kumpoo-2025 --source web --get-winners

# Override Excel file path:
python src/main.py --tournament tournaments/kumpoo-2025 --source excel --file "path/to/draws.xlsx"
```

The pipeline:
```
Tournament Config (YAML) ──────────────────────────┐
        │                                          │
Excel (.XLSX) or Web URL                           │
        │                                          │
        ▼                                          ▼
  parse_tournament.py / parse_web.py  →  output/divisions/*.json
  generate_schedule.py  ← config      →  output/schedules/*.json
  generate_website.py   ← config      →  output/webpages/index.html
```

Individual scripts can still be run standalone with `--tournament`:
1. `python src/parse_tournament.py --tournament tournaments/kumpoo-2025`
2. `python src/parse_web.py --tournament tournaments/kumpoo-2025`
3. `python src/generate_schedule.py --tournament tournaments/kumpoo-2025`
4. `python src/generate_website.py --tournament tournaments/kumpoo-2025`

## Key Conventions

- **Do not hand-edit files under `tournaments/*/output/`** — they are generated. Change source scripts or config instead.
- Python 3 with `openpyxl`, `requests`, `beautifulsoup4`, `lxml`, `pyyaml`. Install via `pip install -r requirements.txt`.
- No template engines or frontend frameworks — pure Python string formatting for HTML generation.
- Website tabs are derived from categories present in the data and configured in `divisions.yaml`.
- Both input modes (Excel and web) produce identical JSON output format — downstream pipeline is shared.

## Tournament Configuration

Each tournament is configured via 6 YAML files in `tournaments/<name>/config/`. See `docs/architecture/tournament-config.md` for full specification.

| Config file | Purpose |
|---|---|
| `tournament.yaml` | Tournament name, description, input source |
| `venue.yaml` | Days, sessions, court availability, slot duration |
| `match_rules.yaml` | Match durations and rest periods per category |
| `court_preferences.yaml` | Court preferences/restrictions per category |
| `divisions.yaml` | Event names, level→category mapping, tab display, format overrides |
| `scheduling.yaml` | Scheduling priorities, day constraints (global + per-division), elite divisions |

## Web Scraper (parse_web.py)

Scrapes tournament data from tournamentsoftware.com as an alternative to the Excel input.

- 0.5-second delay between HTTP requests to avoid throttling
- Bypasses cookie consent wall via POST to `/cookiewall/Save`
- Scrapes `draws.aspx` for draw list, `draw.aspx` for format/size, `drawmatches.aspx` for match data, `clubs.aspx` for club list
- Scraped data is cached in `tournaments/<name>/scraped/` for reuse; `--rescrape` forces fresh fetch
- Format detection: "Cup-kaavio" = elimination, "Lohko" = round-robin, group draws detected by ` - Group X` suffix
- Round detection for elimination brackets: uses player recurrence to detect round boundaries
- Club per player is NOT available from the web (only country code `[FIN]`) — set to `null`
- Draw positions are inferred from match order in Round 1
- `--full-results` flag adds optional `result`, `duration`, `scheduled_time`, `court` fields to match entries
- By default, later-round elimination matches use structural placeholders (`Winner R1-M1`) instead of actual winner names from scraped data
- `--get-winners` flag uses actual winner names from scraped data in later bracket rounds (reveals tournament results)

## Excel File Structure

- Sheets named `{EVENT} {LEVEL}-{Main Draw|Playoff}` (e.g., `MS C-Main Draw`, `BS U17-Playoff`)
- Column A = draw position, B = status (WDN/SUB), C = club, E = player name
- **Critical**: Use `str(c.value).strip()` when reading cells — raw `c.value is not None` catches ghost whitespace rows

### Three sheet formats

| Format | Detection | Example |
|---|---|---|
| Elimination bracket | Header row has "Round 1" / "Quarterfinals" in columns E+ | MS A, MS B, MD C |
| Round-robin | Header has numbered columns ("1", "2", "3") + "Standings" row | WS C, BS U11, MD 35 |
| Group + Playoff | Column A contains group headers like "BS U17 - Group A" | BS U17, MS 45 |

### Doubles pattern

- Elimination doubles: partner 1 on row *before* the A-numbered row (no A value), partner 2 on the A-numbered row
- Round-robin doubles: both names in one cell separated by `\n`

## Schedule Generator (generate_schedule.py)

Generates match schedules respecting court availability, player rest, and round ordering. All constraints are read from the tournament's config files.

- **Courts**: Defined in `venue.yaml` — days, court numbers, per-court end times
- **Match durations**: From `match_rules.yaml` — per category (e.g., Elite 45 min, default 30 min)
- **Rest periods**: From `match_rules.yaml` — per category (e.g., Elite 60 min, default 30 min)
- **Court preferences**: From `court_preferences.yaml` — required/preferred/fallback/last-resort per category
- **Sessions**: From `venue.yaml` — named time blocks within each day
- **Scheduling priorities**: From `scheduling.yaml` — priority ordering and day constraints
- **Scheduling algorithm**: Greedy slot assignment sorted by priority
- **Same-day rule**: All matches in the same round of the same division are automatically scheduled on a single day. Hard error if they don't fit.
- **Day constraints**: Global (all divisions) and per-division overrides in `scheduling.yaml` via `day_constraints` and `division_day_constraints`
- **Pool round parallelism**: Round-robin matches use graph coloring so independent matches can run simultaneously
- **Worst-case rest buffering**: Later-round matches trace prerequisites back to R1; scheduling guarantees rest for worst-case bracket outcomes
- **Bye matches**: Loaded but not scheduled (no court time needed)
- **Match IDs**: Format `"{div_code}:{round_name}:M{num}"` used for prerequisite tracking

## Website Generator (generate_website.py)

Generates a self-contained single-page HTML website with inline CSS and vanilla JavaScript.

- **Tournament name**: Read from `tournament.yaml` for title, header, and footer
- **Tab structure**: Derived from categories in data + tab order from `divisions.yaml`
- **Schedule cross-reference**: Lookup keyed by `(division_code, round_name, match_num)` → time/court/date annotation on match cards
- **Bracket rendering**: Tree-style CSS connectors using `::before`/`::after` pseudo-elements (not SVG)
- **Collapsible cards**: Division cards toggle via `.open` CSS class
- **Schedule grid**: Time rows × court columns; multi-slot matches use appropriate `rowspan`
- **Responsive**: Mobile breakpoint at 600px with horizontal scroll for tables and brackets

## Testing Changes

After modifying any script, run the full pipeline:
```bash
python src/main.py --tournament tournaments/kumpoo-2025
python src/main.py --tournament tournaments/kumpoo-2025 --source web
```
Then open `tournaments/kumpoo-2025/output/webpages/index.html` in a browser and verify:
- All category tabs present in the data work correctly
- Elimination divisions show full bracket (R1 through Final) with tree-style connectors
- Group+playoff divisions show groups + playoff bracket
- Round-robin divisions show VS match cards
- Schedule annotations (time + court) on match cards
- Schedule tab shows session sub-tabs with time × court grids
- Multi-slot matches (e.g., 45-min Elite) span correct number of rows in schedule grid
- No "Bye" entries in player lists

## Creating a New Tournament

1. Create `tournaments/<name>/` with subdirectories: `config/`, `input/`, `scraped/`, `output/`
2. Copy and modify the 6 YAML config files from an existing tournament
3. Place input Excel file in `input/` (or configure web URL in `tournament.yaml`)
4. Run: `python src/main.py --tournament tournaments/<name>`
