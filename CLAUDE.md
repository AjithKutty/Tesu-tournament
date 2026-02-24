# Kumpoo Tervasulan Eliitti 2025 — Tournament Website

Badminton tournament website generator for the "Kumpoo Tervasulan Eliitti 2025" tournament hosted by TeSu (Tervasulka).

## Project Structure

```
Tesu-Tournament/
├── parse_tournament.py          # Excel → JSON parser
├── generate_website.py          # JSON → HTML website generator
├── requirements.txt             # Python deps (openpyxl)
├── index.html                   # Generated website (DO NOT edit by hand)
├── divisions/                   # Generated JSON files (one per sheet)
│   ├── tournament_index.json    # Master index of all divisions
│   └── *.json                   # Per-division data files
├── scheduling-rules.md          # Court scheduling rules
└── Draws Kumpoo...XLSX          # Source Excel file from Badminton Finland
```

## Workflow

```
Excel (.XLSX)  →  parse_tournament.py  →  divisions/*.json  →  generate_website.py  →  index.html
```

1. `python parse_tournament.py` — Reads the Excel file and writes 32 JSON files into `divisions/`
2. `python generate_website.py` — Reads the JSON files and generates `index.html`

## Key Conventions

- **Do not hand-edit `index.html`** — it is generated output. Change `generate_website.py` instead.
- **Do not hand-edit `divisions/*.json`** — they are generated output. Fix `parse_tournament.py` instead.
- Python 3 with `openpyxl` as the only external dependency. Install via `pip install -r requirements.txt`.
- No template engines or frontend frameworks — pure Python string formatting for HTML generation.

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

After modifying either script:
```bash
python parse_tournament.py      # Re-parse Excel
python generate_website.py      # Re-generate website
```
Then open `index.html` in a browser and verify:
- All 7 tabs work (Open A/B/C, Junior, Veterans, Elite, Clubs)
- Elimination divisions show full bracket (R1 through Final)
- Group+playoff divisions show groups + playoff bracket
- Round-robin divisions show VS match cards
- No "Bye" entries in player lists
