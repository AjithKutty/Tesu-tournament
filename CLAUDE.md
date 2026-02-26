# Kumpoo Tervasulan Eliitti 2025 — Tournament Website

Badminton tournament website generator for the "Kumpoo Tervasulan Eliitti 2025" tournament hosted by TeSu (Tervasulka).

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                      # Unified entry point (runs all 3 steps)
│   ├── parse_tournament.py          # Excel → JSON parser
│   ├── generate_schedule.py         # JSON → schedule JSON
│   └── generate_website.py          # JSON → HTML website
├── output/
│   ├── divisions/                   # Generated JSON files (one per sheet)
│   │   ├── tournament_index.json    # Master index of all divisions
│   │   └── *.json                   # Per-division data files
│   ├── schedules/                   # Generated schedule JSON files
│   │   ├── schedule_index.json      # Schedule session index
│   │   └── *.json                   # Per-session schedule files
│   └── webpages/
│       └── index.html               # Generated single-page website
├── docs/
│   ├── requirements/
│   │   └── scheduling-rules.md
│   ├── architecture/
│   │   └── scheduling-proposal.md
│   └── implementation/
│       ├── implementation-plan.md
│       └── website-schedule-plan.md
├── requirements.txt                 # Python deps (openpyxl)
├── CLAUDE.md
└── Draws Kumpoo...XLSX              # Source Excel file from Badminton Finland
```

## Workflow

```
python src/main.py    # Runs all three steps and produces output/webpages/index.html
```

The pipeline:
```
Excel (.XLSX)  →  parse_tournament.py  →  output/divisions/*.json
                  generate_schedule.py →  output/schedules/*.json
                  generate_website.py  →  output/webpages/index.html
```

Individual scripts can still be run standalone:
1. `python src/parse_tournament.py` — Reads the Excel file and writes 32 JSON files into `output/divisions/`
2. `python src/generate_schedule.py` — Reads division data and generates schedule into `output/schedules/`
3. `python src/generate_website.py` — Reads divisions + schedules and generates `output/webpages/index.html`

## Key Conventions

- **Do not hand-edit `output/webpages/index.html`** — it is generated output. Change `src/generate_website.py` instead.
- **Do not hand-edit `output/divisions/*.json`** — they are generated output. Fix `src/parse_tournament.py` instead.
- **Do not hand-edit `output/schedules/*.json`** — they are generated output. Fix `src/generate_schedule.py` instead.
- Python 3 with `openpyxl` as the only external dependency. Install via `pip install -r requirements.txt`.
- No template engines or frontend frameworks — pure Python string formatting for HTML generation.
- Single-page website with 8 tabs: Open A, Open B, Open C, Junior, Veterans, Elite, Clubs, Schedule.

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

After modifying any script, run the full pipeline:
```bash
python src/main.py
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
