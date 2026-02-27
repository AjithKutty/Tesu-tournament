# Implementation Plan: Web Scraper Input Source

## Overview

Add `src/parse_web.py` as an alternative to `src/parse_tournament.py`. Both produce identical `output/divisions/*.json` files so the downstream pipeline (schedule + website generation) works unchanged.

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/parse_web.py` | Create | Web scraper (~400 lines) |
| `src/main.py` | Modify | Add argparse CLI, dispatch to Excel or web parser |
| `src/parse_tournament.py` | Modify | Accept file path as parameter (not hardcoded) |
| `requirements.txt` | Modify | Add `requests`, `beautifulsoup4`, `lxml` |

No changes to `generate_schedule.py` or `generate_website.py`.

## CLI Interface

```bash
# Default (Excel, existing file):
python src/main.py

# Excel with custom path:
python src/main.py --source excel --file "path/to/draws.xlsx"

# Web scraping:
python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-..."

# Web scraping with match results:
python src/main.py --source web --url "..." --full-results

# Standalone:
python src/parse_web.py "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-..."
```

---

## `src/parse_web.py` — Detailed Design

### Constants (mirrored from parse_tournament.py)

```python
EVENT_NAMES    # Same mapping: MS → "Men's Singles", etc.
LEVEL_CATEGORY # Same mapping: A → "Open A", U17 → "Junior", etc.
OUTPUT_DIR     # Same: output/divisions/
```

### Function: `bypass_cookiewall(session, base_url, target_path)`

1. `GET base_url + target_path` → server redirects to `/cookiewall/?returnurl=...`
2. `POST base_url + "/cookiewall/Save"` with form data:
   - `ReturnUrl = target_path`
   - `SettingsOpen = "false"`
   - `CookiePurposes = ["1", "2", "4", "16"]`
3. Session cookies are now set for all subsequent requests

### Function: `extract_tournament_info(session, base_url, tournament_id)`

Fetch the draws page and extract:
- Tournament name from `<h2>` heading (e.g. "Kumpoo Tervasulan Eliitti 2025")
- Returns `(tournament_name, tournament_id)`

### Function: `fetch_draw_list(session, base_url, tournament_id)`

Scrape `draws.aspx?id={tournament_id}`. Find all `<a>` tags with `draw=` in href.

Returns: `[{"draw_num": 1, "name": "BS U11"}, {"draw_num": 10, "name": "BS U17 - Group A"}, ...]`

### Function: `group_draws_by_division(draw_list)`

Group the flat draw list into logical divisions:

```
Input:  [BS U17 - Group A (draw=10), BS U17 - Group B (draw=11), BS U17 (draw=15), MS A (draw=27)]

Output: {
    "BS U17": {
        "type": "group_playoff",
        "groups": [{"draw_num": 10, "letter": "A"}, {"draw_num": 11, "letter": "B"}],
        "playoff": {"draw_num": 15}
    },
    "MS A": {
        "type": "standalone",
        "draw": {"draw_num": 27}
    }
}
```

Logic:
1. Regex `^(.+?) - Group ([A-Z])$` identifies group-stage draws → group by base name
2. Remaining draws that match an existing group base name → that group's playoff draw
3. Everything else → standalone draw (elimination or round-robin)

### Function: `fetch_draw_meta(session, base_url, tournament_id, draw_num)`

Scrape `draw.aspx?id={ID}&draw={N}`. Extract:
- Format text from `<span class="tag">` elements: "Cup-kaavio" = elimination
- Draw size from `<span class="tag">` with "Size N" text
- Player list from `<li data-asg-title="...">` autosuggest items

Returns: `{"format_text": "Cup-kaavio", "draw_size": 16, "players": ["Name1", "Name2"]}`

### Function: `detect_format(division_type, meta)`

```
group_playoff type     → "group_playoff"
"Cup" in format_text   → "elimination"
otherwise              → "round_robin"
```

### Function: `fetch_draw_matches(session, base_url, tournament_id, draw_num, is_doubles)`

Scrape `drawmatches.aspx?id={ID}&draw={N}`. Parse `<table class="matches">`.

**Row structure per match in the HTML table:**

Singles match (3 rows):
```
Row 1: [empty] [planned_time] [Player1 name + seed + country] [-] [Player2 name + seed + country] [result] [duration] [court]
Row 2: [Player1 name] [country]     ← detail row
Row 3: [country] [Player2 name]     ← detail row
```

Doubles match (5 rows):
```
Row 1: [empty] [planned_time] [P1a+P1b names + countries] [-] [P2a+P2b names + countries] [result] [duration] [court]
Row 2: [P1a name] [country]
Row 3: [P1b name] [country]
Row 4: [country] [P2a name]
Row 5: [country] [P2b name]
```

**Parsing approach**: Identify match boundaries by the presence of a `.plannedtime` cell in a row. Each such row starts a new match block. Accumulate subsequent detail rows until the next `.plannedtime` row.

From each match, extract:
- Player names (strip `[FIN]`/`[SWE]` country codes using regex `\[[A-Z]{2,3}\]`)
- Seeds (extract `[1]`, `[3/4]` using same regex as `extract_seed()` in parse_tournament.py)
- Scheduled time, court, result, duration (from main row cells)

Returns: list of match dicts:
```python
[{
    "player1": ["Luka Penttinen"],           # list of 1 (singles) or 2 (doubles) names
    "player2": ["Eetu Hanhineva"],
    "seed1": "1", "seed2": None,
    "time": "la 5.4.2025 9.00",
    "court": "Nallisport - 8",
    "result": "21-16 21-18",
    "duration": "28m",
}]
```

### Function: `build_elimination_division(matches, draw_size, is_doubles, full_results)`

1. **Assign rounds**: First `draw_size//2` matches → Round 1, next `draw_size//4` → Round 2/QF, etc.
   - Round name sequence derived from draw_size (same as `get_round_headers()` logic)
   - If fewer matches than expected (pre-tournament): only early rounds have data

2. **Extract players from Round 1**: Match 1 → positions 1,2; Match 2 → positions 3,4; etc.
   - Build player entries with position, name, club=None, seed, status=None
   - Handle byes: if a match has fewer than 2 real players

3. **Build rounds array**:
   - Rounds with actual match data: use real player names
   - Rounds without data (unplayed): generate "Winner R1-M1" placeholders (same as `build_full_bracket()`)
   - If `full_results`: add optional result/duration/time/court fields

4. Returns: `(players_list, rounds_list, draw_size)`

### Function: `build_roundrobin_division(matches, is_doubles, full_results)`

1. Collect unique players from all matches in order of appearance → assign positions 1..N
2. Build player entries (name, club=None, seed, status=None)
3. Generate all-vs-all match list (same as `generate_roundrobin_matches()`)
   - If `full_results`: add optional fields from scraped match data

Returns: `(players_list, matches_list)`

### Function: `build_group_playoff_division(group_draws, playoff_draw, session, ...)`

1. For each group draw:
   - Fetch matches from drawmatches.aspx
   - Build group object: `{"name": "Group A", "players": [...], "matches": [...]}`

2. For the playoff draw:
   - Fetch draw metadata for playoff draw_size
   - Build structural bracket with "Slot N" placeholders (mirrors `build_playoff_bracket()`)
   - Write standalone playoff JSON file

3. Returns: `(groups_list, playoff_dict, playoff_filename)`

### Function: `fetch_clubs(session, base_url, tournament_id)`

Scrape `clubs.aspx?id={ID}`. Parse `<table>` rows, extract club names from first column.
Returns: sorted list of club name strings.

### Function: `parse_draw_name(name)`

Parse web draw names like "MS A", "BS U17", "XD 35" into metadata dict.
Regex: `^([A-Z]{2})\s+(.+)$` → event_code + level.
Apply same EVENT_NAMES and LEVEL_CATEGORY mappings as parse_tournament.py.

Returns: `{"event_code", "level", "category", "full_name", "code", "is_doubles"}` or `None`

### Function: `division_to_filename(code, draw_type)`

Generate filename matching Excel parser convention: `"MS_A-Main_Draw.json"`, `"BS_U17-Playoff.json"`.
Formula: `code.replace(" ", "_") + "-" + draw_type_suffix + ".json"`

### Function: `process_tournament(url, full_results=False)`

Main orchestration:

```
1. Parse base_url and tournament_id from the input URL
2. Create requests.Session with browser-like User-Agent header
3. bypass_cookiewall()
4. tournament_name = extract_tournament_info()
5. draw_list = fetch_draw_list()
6. divisions = group_draws_by_division(draw_list)
7. club_names = fetch_clubs()
8. os.makedirs(OUTPUT_DIR, exist_ok=True)

9. index_entries = []
10. For each division:
    a. info = parse_draw_name(name) → skip if None
    b. Determine format (group_playoff / elimination / round_robin)
    c. Fetch matches + metadata from appropriate draws
    d. Build division JSON matching exact schema
    e. Write JSON file
    f. Add to index_entries

11. Write tournament_index.json (sorted by category order, then code)
12. Print summary
```

### Function: `main(url=None, full_results=False)`

Entry point. Parses URL from argument or command-line. Calls `process_tournament()`.

---

## `src/main.py` — Changes

Replace the current hardcoded function calls with argparse:

```python
import argparse

parser = argparse.ArgumentParser(description="Tournament website generator pipeline")
parser.add_argument("--source", choices=["excel", "web"], default="excel")
parser.add_argument("--file", default=None, help="Excel file path (for --source excel)")
parser.add_argument("--url", default=None, help="Tournament URL (for --source web)")
parser.add_argument("--full-results", action="store_true",
                    help="Include match results from web (only with --source web)")
args = parser.parse_args()
```

Step 1 dispatches based on `args.source`:
- `"excel"` → `parse_excel_main(filepath=args.file)`
- `"web"` → `parse_web_main(url=args.url, full_results=args.full_results)`

Steps 2 and 3 remain unchanged.

## `src/parse_tournament.py` — Changes

Minimal change: `main()` accepts optional `filepath` parameter.

```python
def main(filepath=None):
    filepath = filepath or EXCEL_FILE
    print(f"Reading: {filepath}")
    ...
```

## `requirements.txt` — Changes

```
openpyxl
requests
beautifulsoup4
lxml
```

---

## Data Gaps and Handling

| Gap | Handling |
|-----|---------|
| No club per player on web | Set `"club": null` for all player entries |
| No draw positions on web | Infer from match order in Round 1 |
| No explicit round names | Derive from draw_size: size 16 → [R1, QF, SF, F] |
| No bracket for unplayed rounds | Generate "Winner R1-M1" structural placeholders |
| `"sheet"` field doesn't apply | Use `"source"` field with the draw URL instead |
| Division `"clubs"` list empty | `tournament_index.json` has full club list from clubs.aspx |

## Robustness

- 0.5s delay between requests (avoid IP throttling)
- Retry cookie bypass if mid-session redirect to cookie wall
- Graceful skip for draws that fail to parse (log warning)
- UTF-8 encoding throughout for Finnish characters

## Verification Steps

1. `python src/main.py` — Excel mode still works (regression)
2. `python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-2b2d-489f-863c-42a62af6d7bd"` — produces JSON files
3. Compare JSON structure: same keys, same format values, same filenames
4. Full pipeline with web data: all 3 steps complete, `index.html` loads
5. `--full-results` adds result/duration fields to matches
