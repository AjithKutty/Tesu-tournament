# Kumpoo Tervasulan Eliitti 2025 — Tournament Website

A badminton tournament website generator that reads draw data from either an Excel export or a [tournamentsoftware.com](https://tournamentsoftware.com) URL, generates match schedules, and builds a self-contained single-page HTML website.

Built for the **Kumpoo Tervasulan Eliitti 2025** tournament organized by [Tervasulka badminton club](https://tervasulka.fi/).

## Features

- **Dual input modes**: Parse draws from an Excel workbook (Badminton Finland export) or scrape directly from tournamentsoftware.com
- **Automatic schedule generation**: Greedy scheduling algorithm with court preferences, rest periods, round ordering, and worst-case rest buffering
- **Single-page website**: 8 tabbed sections (Open A/B/C, Junior, Veterans, Elite, Clubs, Schedule) with collapsible division cards
- **Bracket visualization**: Tree-style elimination brackets with CSS connectors
- **Schedule grid**: Time x court grid with session sub-tabs (Saturday Morning/Afternoon/Evening, Sunday Morning/Afternoon)
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

   This installs: `openpyxl`, `requests`, `beautifulsoup4`, `lxml`.

## Usage

### Full pipeline (recommended)

Run all three steps (parse, schedule, generate website) in one command:

```bash
# From Excel file (default — looks for the .xlsx file in the project root):
python src/main.py

# From Excel file at a custom path:
python src/main.py --source excel --file "path/to/draws.xlsx"

# From tournamentsoftware.com URL:
python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

# From web with match results, scores, and durations:
python src/main.py --source web --url "..." --full-results
```

### Individual scripts

Each pipeline stage can be run independently:

```bash
# 1. Parse Excel → JSON
python src/parse_tournament.py

# 1. (Alternative) Scrape web → JSON
python src/parse_web.py "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

# 2. Generate schedule from division JSON
python src/generate_schedule.py

# 3. Generate website from divisions + schedule JSON
python src/generate_website.py
```

### Viewing the output

After running the pipeline, open the generated website in a browser:

```bash
# Linux/macOS
open output/webpages/index.html

# Windows
start output/webpages/index.html
```

## Pipeline

```
Excel (.XLSX) or Web URL
        │
        ▼
  parse_tournament.py / parse_web.py  →  output/divisions/*.json
  generate_schedule.py                →  output/schedules/*.json
  generate_website.py                 →  output/webpages/index.html
```

## Output

All generated files go into `output/` (git-ignored):

| Directory | Contents |
|-----------|----------|
| `output/divisions/` | One JSON file per division draw + `tournament_index.json` master index |
| `output/schedules/` | One JSON file per session + `schedule_index.json` session index |
| `output/webpages/` | `index.html` — the final single-page website |

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                  # Unified entry point (parse → schedule → website)
│   ├── parse_tournament.py      # Excel → JSON parser
│   ├── parse_web.py             # Web scraper → JSON parser
│   ├── generate_schedule.py     # JSON → schedule JSON
│   └── generate_website.py      # JSON → single-page HTML
├── output/                      # Generated files (git-ignored)
├── docs/
│   ├── requirements/            # Functional & scheduling requirements
│   ├── architecture/            # Scheduling algorithm design
│   └── implementation/          # Implementation plans
├── requirements.txt
├── CLAUDE.md                    # AI assistant project instructions
└── *.XLSX                       # Source Excel file (Badminton Finland export)
```

## Input Formats

### Excel mode

Expects an `.xlsx` workbook exported from badmintonfinland.tournamentsoftware.com with one sheet per division draw. Supports three draw formats:

- **Elimination bracket** — standard knockout draws (detected by "Round 1" header)
- **Round-robin** — all-vs-all pools (detected by numbered column headers)
- **Group + Playoff** — group stages followed by a knockout bracket

### Web scraping mode

Scrapes tournament data directly from tournamentsoftware.com. Handles cookie consent walls automatically. Note: club-per-player data is not available from the web (only country codes).

The `--full-results` flag additionally scrapes match results, scores, durations, scheduled times, and court assignments.

## Scheduling Rules

The schedule generator respects tournament-specific constraints:

- **Saturday**: 12 courts (1-12), 9:00-22:00
- **Sunday**: 8 courts (1-8); courts 1-4 until 16:00, courts 5-8 until 18:00
- **Match duration**: 30 minutes (standard), 45 minutes (Elite)
- **Rest periods**: 30 minutes (standard), 60 minutes (Elite)
- **Court preferences**: Elite and Open A on courts 5-8; Junior on courts 9-12
- **Semifinals and Finals**: Scheduled on Sunday only

## Division Categories

| Category | Website Tab | Events |
|----------|-------------|--------|
| Open A | Open A | MS, MD, WD, XD |
| Open B | Open B | MS, WS, MD, XD |
| Open C | Open C | MS, WS, MD, WD, XD |
| Junior | Junior | BS/BD U11, U13, U15, U17 |
| Veterans | Veterans | MS/MD/XD 35+, MS/MD 45+ |
| Elite | Elite | MS/WS/XD V |

## License

This project is not currently licensed for distribution.
