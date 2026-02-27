# Kumpoo Tervasulan Eliitti 2025 — Tournament Website

Badminton tournament website generator. Reads draw data from either an Excel export or a tournamentsoftware.com URL, generates match schedules, and builds a single-page HTML website.

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                      # Unified entry point (runs all 3 steps)
│   ├── parse_tournament.py          # Excel → JSON parser
│   ├── parse_web.py                 # Web scraper → JSON parser (same output format)
│   ├── generate_schedule.py         # JSON → schedule JSON
│   └── generate_website.py          # JSON → HTML website
├── output/
│   ├── divisions/                   # Generated JSON files (one per division)
│   │   ├── tournament_index.json    # Master index of all divisions
│   │   └── *.json                   # Per-division data files
│   ├── schedules/                   # Generated schedule JSON files
│   │   ├── schedule_index.json      # Schedule session index
│   │   └── *.json                   # Per-session schedule files
│   └── webpages/
│       └── index.html               # Generated single-page website
├── docs/
│   ├── requirements/
│   │   ├── requirements.md
│   │   └── scheduling-rules.md
│   ├── architecture/
│   │   └── scheduling-proposal.md
│   └── implementation/
│       ├── implementation-plan.md
│       ├── website-schedule-plan.md
│       └── web-scraper-plan.md
├── requirements.txt                 # Python deps (openpyxl, requests, beautifulsoup4, lxml)
├── CLAUDE.md
└── Draws Kumpoo...XLSX              # Source Excel file from Badminton Finland
```

## Workflow

```bash
# Excel mode (default):
python src/main.py
python src/main.py --source excel --file "path/to/draws.xlsx"

# Web scraping mode:
python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

# Web scraping with match results, scores, durations:
python src/main.py --source web --url "..." --full-results
```

The pipeline:
```
Excel (.XLSX) or Web URL
        │
        ▼
  parse_tournament.py / parse_web.py  →  output/divisions/*.json
  generate_schedule.py                →  output/schedules/*.json
  generate_website.py                 →  output/webpages/index.html
```

Individual scripts can still be run standalone:
1. `python src/parse_tournament.py` — Reads the Excel file and writes JSON files into `output/divisions/`
2. `python src/parse_web.py "URL"` — Scrapes tournamentsoftware.com and writes identical JSON files
3. `python src/generate_schedule.py` — Reads division data and generates schedule into `output/schedules/`
4. `python src/generate_website.py` — Reads divisions + schedules and generates `output/webpages/index.html`

## Key Conventions

- **Do not hand-edit `output/webpages/index.html`** — it is generated output. Change `src/generate_website.py` instead.
- **Do not hand-edit `output/divisions/*.json`** — they are generated output. Fix `src/parse_tournament.py` or `src/parse_web.py` instead.
- **Do not hand-edit `output/schedules/*.json`** — they are generated output. Fix `src/generate_schedule.py` instead.
- Python 3 with `openpyxl`, `requests`, `beautifulsoup4`, `lxml`. Install via `pip install -r requirements.txt`.
- No template engines or frontend frameworks — pure Python string formatting for HTML generation.
- Single-page website with 8 tabs: Open A, Open B, Open C, Junior, Veterans, Elite, Clubs, Schedule.
- Both input modes (Excel and web) produce identical JSON output format — downstream pipeline is shared.

## Web Scraper (parse_web.py)

Scrapes tournament data from tournamentsoftware.com as an alternative to the Excel input.

- Bypasses cookie consent wall via POST to `/cookiewall/Save`
- Scrapes `draws.aspx` for draw list, `draw.aspx` for format/size, `drawmatches.aspx` for match data, `clubs.aspx` for club list
- Format detection: "Cup-kaavio" = elimination, "Lohko" = round-robin, group draws detected by ` - Group X` suffix
- Round detection for elimination brackets: uses player recurrence to detect round boundaries (since byes are not listed on the web)
- Club per player is NOT available from the web (only country code `[FIN]`) — set to `null`
- Draw positions are inferred from match order in Round 1
- `--full-results` flag adds optional `result`, `duration`, `scheduled_time`, `court` fields to match entries

## Excel File Structure

Source: `Draws Kumpoo Tervasulan Eliitti 2025 vain kaaviot.XLSX` (from badmintonfinland.tournamentsoftware.com)

- 32 sheets, one per division draw
- Sheet naming: `{EVENT} {LEVEL}-{Main Draw|Playoff}` (e.g., `MS C-Main Draw`, `BS U17-Playoff`)
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

## Division Categories

| Category | Tab ID | Events |
|---|---|---|
| Open A | opena | MS, MD, WD, XD |
| Open B | openb | MS, WS, MD, XD |
| Open C | open | MS, WS, MD, WD, XD |
| Junior | junior | BS/BD U11, U13, U15, U17 |
| Veterans | veterans | MS/MD/XD 35+, MS/MD 45+ |
| Elite | elite | MS/WS/XD V |

## Testing Changes

After modifying any script, run the full pipeline with both input modes:
```bash
python src/main.py                          # Excel mode
python src/main.py --source web --url "..."  # Web mode
```
Then open `output/webpages/index.html` in a browser and verify:
- All 8 tabs work (Open A/B/C, Junior, Veterans, Elite, Clubs, Schedule)
- Elimination divisions show full bracket (R1 through Final) with tree-style connectors
- Group+playoff divisions show groups + playoff bracket
- Round-robin divisions show VS match cards
- Schedule annotations (time + court) on match cards
- Schedule tab shows session sub-tabs with time × court grids
- 45-min Elite matches span two rows in schedule grid
- No "Bye" entries in player lists
