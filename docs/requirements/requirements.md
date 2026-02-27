# Requirements — Badminton Tournament Website Generator

## 1. Purpose

A tool that reads tournament draw data — either from an Excel spreadsheet or by scraping a tournamentsoftware.com webpage — generates a match schedule, and produces a self-contained single-page HTML website for players, officials, and spectators.

The tool must be tournament-agnostic: it works with any badminton tournament hosted on tournamentsoftware.com, not only the specific tournament whose data is currently checked in. The user chooses their input source at the command line.

---

## 2. Functional Requirements

### 2.1 Input

| ID | Requirement |
|----|-------------|
| IN-1 | The system accepts two input modes, selectable via CLI: (a) an Excel workbook (.XLSX), or (b) a tournamentsoftware.com URL. |
| IN-2 | **Excel mode**: The workbook contains one sheet per division draw, following the naming convention `{EVENT} {LEVEL}-{Main Draw\|Playoff}` (e.g. `MS A-Main Draw`, `BS U17-Playoff`). |
| IN-3 | **Web mode**: The system scrapes tournament draw data from a tournamentsoftware.com draws page URL, bypassing the cookie consent wall automatically. |
| IN-4 | The system must support the three draw formats produced by tournamentsoftware.com: elimination brackets, round-robin pools, and group-stage + playoff combinations — regardless of input mode. |
| IN-5 | Scheduling parameters (court count, operating hours, match durations, rest periods, court preferences, session boundaries) must be configurable, not hard-coded to a single tournament. |
| IN-6 | Both input modes must produce the same JSON output format so that downstream pipeline stages (schedule generation, website generation) work without modification. |
| IN-7 | The Excel file path and web URL must be passable as CLI arguments (`--file`, `--url`). |
| IN-8 | An optional `--full-results` flag enables scraping of additional match data (results, scores, durations, scheduled times) when using web mode. By default, only draw/seeding information equivalent to the Excel export is scraped. |

### 2.2 Data Parsing (Common to Both Input Modes)

| ID | Requirement |
|----|-------------|
| PA-1 | Parse each draw to extract: event code, level, draw type, category, and whether the event is singles or doubles. |
| PA-2 | Detect the draw format automatically (elimination, round-robin, or group + playoff). |
| PA-3 | Extract player/pair entries including: draw position, player name(s), club affiliation (when available), seed, and status (e.g. WDN, SUB). |
| PA-4 | For doubles events, correctly associate both partners. |
| PA-5 | Build structural match data: bracket rounds with match pairings for elimination; all-play-all pairings for round-robin; group matches plus playoff bracket for group + playoff. |
| PA-6 | Handle byes (empty draw positions) by auto-advancing the opponent to the next round. |
| PA-7 | Produce one JSON file per division plus a master index JSON listing all divisions, their metadata, and a deduplicated list of all participating clubs. |
| PA-8 | Playoff draws must be linked back to their corresponding main-draw group-stage division. |

### 2.2.1 Excel-Specific Parsing

| ID | Requirement |
|----|-------------|
| PX-1 | Detect sheet format from header row content (elimination: "Round 1"/"Quarterfinals"; round-robin: numbered columns + "Standings"; group+playoff: group headers in column A). |
| PX-2 | For elimination doubles, read partner 1 from the row before the draw-position row and partner 2 from the draw-position row. For round-robin doubles, split newline-separated names in a single cell. |
| PX-3 | Filter out ghost rows caused by whitespace-only cell values (use `str(cell.value).strip()`). |
| PX-4 | Read club abbreviations from column C for each player entry. |

### 2.2.2 Web-Specific Parsing

| ID | Requirement |
|----|-------------|
| PW-1 | Bypass the tournamentsoftware.com cookie consent wall by posting to `/cookiewall/Save` with the required form data. |
| PW-2 | Discover all draws by scraping the `draws.aspx` page for draw links. |
| PW-3 | Group draw links into logical divisions: links with ` - Group X` suffix belong to a group+playoff division; the link with the bare division name is the playoff bracket. |
| PW-4 | Detect format from the `draw.aspx` page metadata: "Cup-kaavio" indicates elimination; small-size draws without "Cup" are round-robin. |
| PW-5 | Scrape match data from `drawmatches.aspx`, parsing the `<table class="matches">` for player names, seeds, scheduled times, courts, results, and durations. |
| PW-6 | Strip country codes (e.g. `[FIN]`) from player names; these are not club affiliations. |
| PW-7 | Infer draw positions for elimination brackets from match order: match 1 → positions 1,2; match 2 → positions 3,4; etc. |
| PW-8 | For elimination brackets, group chronological matches into rounds based on expected match counts per round (R1=size/2, QF=size/4, etc.). Generate structural "Winner R1-M1" placeholders for unplayed later rounds. |
| PW-9 | Scrape the club list from `clubs.aspx` for the tournament index. Per-player club affiliation is not available from the web (set to `null`). |
| PW-10 | Extract the tournament name from the page title/heading rather than hardcoding it. |
| PW-11 | Include a 0.5-second delay between web requests to avoid throttling. |
| PW-12 | When `--full-results` is enabled, include optional `result`, `duration`, `scheduled_time`, and `court` fields on match entries. |

### 2.3 Schedule Generation (JSON to Schedule JSON)

| ID | Requirement |
|----|-------------|
| SC-1 | Read all division JSON files and generate a court-by-court, time-slot-by-time-slot match schedule across all tournament sessions. |
| SC-2 | Support configurable tournament duration: number of days, court availability per day (which courts, opening/closing times). |
| SC-3 | Support configurable match durations per category (e.g. 30 min standard, 45 min for elite). |
| SC-4 | Support configurable rest periods per category (e.g. 30 min standard, 60 min for elite). |
| SC-5 | Enforce court eligibility rules: certain divisions may be restricted to or prefer specific courts. |
| SC-6 | Prevent player double-booking: no player may be scheduled on two courts at the same time. |
| SC-7 | Enforce rest periods: a player's next match cannot start until their mandatory rest period has elapsed after the previous match ended. |
| SC-8 | Respect round ordering: a match cannot be scheduled until all its prerequisite matches (feeder matches from earlier rounds) have been scheduled. |
| SC-9 | For later-round matches where actual players are unknown (placeholders like "Winner of R1-M1"), use worst-case player tracing to ensure rest constraints are met for all players who could potentially reach that match. |
| SC-10 | Schedule matches at fixed time-slot intervals (e.g. every 30 minutes). |
| SC-11 | Matches within the same round of a division should be scheduled as close together in time as possible. |
| SC-12 | Support the rule that semi-finals and finals of all divisions must be played on a designated day (e.g. Sunday). |
| SC-13 | Use priority-based scheduling: higher-priority categories (e.g. Elite pools) are scheduled first to minimize cascading conflicts. |
| SC-14 | For round-robin pools, compute pool rounds (a graph-coloring approach) so that matches sharing a player are assigned different rounds, enabling parallelism. |
| SC-15 | Produce one schedule JSON file per session plus a session index JSON. |
| SC-16 | Validate the generated schedule and report warnings for any constraint violations (double-bookings, rest violations, round-order violations, court restriction violations). |

### 2.4 Website Generation (JSON to HTML)

| ID | Requirement |
|----|-------------|
| WE-1 | Produce a single, fully self-contained HTML file with all CSS and JavaScript inline — no external dependencies, no build step. |
| WE-2 | Organize divisions into category tabs. The tab structure is derived from the categories present in the data. |
| WE-3 | Include a Clubs tab listing all participating clubs and their player counts. |
| WE-4 | Include a Schedule tab with sub-tabs for each session, displaying a time-slot x court grid. |
| WE-5 | Render elimination divisions as collapsible cards containing a draw-position table and a horizontal scrollable bracket with tree-style connectors. |
| WE-6 | Render round-robin divisions as collapsible cards containing a player table and VS match cards. |
| WE-7 | Render group + playoff divisions as collapsible cards containing per-group player tables with match cards, followed by a playoff bracket. |
| WE-8 | Annotate every match card with its scheduled time and court number (if available in the schedule data). |
| WE-9 | In the schedule grid, matches with longer durations (e.g. 45 min) must span multiple rows accordingly. |
| WE-10 | Display summary statistics: total divisions, total clubs, total players. |
| WE-11 | The website must be responsive and usable on both desktop and mobile devices. |
| WE-12 | Division cards are collapsed by default and expand on click. |

---

## 3. Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NF-1 | **Portability**: The generated HTML file must work offline — openable directly from the filesystem in any modern browser without a web server. |
| NF-2 | **Minimal dependencies**: The generator requires Python 3 with `openpyxl` (Excel mode) and `requests` + `beautifulsoup4` + `lxml` (web mode). No template engines, frontend frameworks, or build tools. |
| NF-3 | **Single command**: The entire pipeline (parse, schedule, generate) must be executable with a single command (`python src/main.py`). Input source is selected via `--source excel` (default) or `--source web --url <URL>`. Individual steps must also be runnable independently. |
| NF-4 | **Determinism**: Given the same input Excel file and configuration, the pipeline must produce identical output. |
| NF-5 | **Performance**: The full pipeline should complete within seconds for tournaments of up to ~300 matches and ~150 players. |
| NF-6 | **Extensibility**: New division formats or categories should be addable without restructuring existing code. |
| NF-7 | **No manual editing of output**: All files under `output/` are generated artifacts. Changes must be made in the source scripts. |

---

## 4. Data Flow

```
Excel Workbook (.XLSX)              tournamentsoftware.com URL
        │                                      │
        ▼                                      ▼
  parse_tournament.py                    parse_web.py
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
         output/divisions/*.json       (one per division + tournament_index.json)
                       │
                       ▼
              generate_schedule.py
                       │
                       ▼
            output/schedules/*.json    (one per session + schedule_index.json)
                       │
                       ▼
              generate_website.py
                       │
                       ▼
         output/webpages/index.html    (single self-contained page)
```

Both input paths produce identical JSON output format, so the downstream pipeline is shared.

---

## 5. Excel Input Format Specification

The input workbook is expected to follow the export format from tournamentsoftware.com (commonly used by national badminton federations).

### 5.1 Sheet Naming

Each sheet represents one draw and is named: `{EVENT_CODE} {LEVEL}-{DRAW_TYPE}`

- **Event codes**: `MS` (Men's Singles), `WS` (Women's Singles), `MD` (Men's Doubles), `WD` (Women's Doubles), `XD` (Mixed Doubles), `BS` (Boys' Singles), `BD` (Boys' Doubles)
- **Levels**: Open levels (`A`, `B`, `C`), Junior age groups (`U11`, `U13`, `U15`, `U17`), Veterans age groups (`35`, `45`), Elite (`V`)
- **Draw types**: `Main Draw`, `Playoff`

### 5.2 Column Layout

| Column | Content |
|--------|---------|
| A | Draw position number (integer) |
| B | Status code (e.g. `WDN` = withdrawn, `SUB` = substitute) |
| C | Club name |
| E | Player name (or both names newline-separated in round-robin doubles) |

### 5.3 Format Detection Rules

| Format | Detection criteria |
|--------|-------------------|
| Elimination bracket | Header row contains "Round 1", "Quarterfinals", "Semifinals", or "Final" in columns E onward |
| Round-robin pool | Header row contains numbered columns ("1", "2", "3") and a "Standings" row exists |
| Group + Playoff | Column A contains group header strings matching `"{EVENT} {LEVEL} - Group {LETTER}"` |

### 5.4 Doubles Handling

- **Elimination**: Partner 1 appears on the row immediately before the draw-position row (no value in column A); Partner 2 appears on the draw-position row.
- **Round-robin**: Both partner names appear in a single cell in column E, separated by a newline character.

---

## 6. Web Input Format Specification

The web input source is a tournamentsoftware.com tournament draws page.

### 6.1 URL Format

The entry URL follows the pattern:
```
https://{federation}.tournamentsoftware.com/sport/draws.aspx?id={tournament-uuid}
```

The tournament UUID is extracted from this URL. The federation subdomain (e.g. `badmintonfinland`) is part of the base URL.

### 6.2 Pages Scraped

| Page | URL Pattern | Data Extracted |
|------|-------------|----------------|
| Draws list | `/sport/draws.aspx?id={ID}` | All draw names and draw numbers |
| Draw metadata | `/sport/draw.aspx?id={ID}&draw={N}` | Format type ("Cup-kaavio"), draw size ("Size 16"), player autosuggest list |
| Draw matches | `/sport/drawmatches.aspx?id={ID}&draw={N}` | Player names, seeds, scheduled times, courts, results, durations |
| Clubs | `/sport/clubs.aspx?id={ID}` | Club names and player counts |

### 6.3 Cookie Wall Bypass

All pages require cookie consent. The bypass procedure:
1. `GET` the target page — server redirects to `/cookiewall/?returnurl=...`
2. `POST` to `/cookiewall/Save` with form data: `ReturnUrl`, `SettingsOpen=false`, `CookiePurposes=[1,2,4,16]`
3. Subsequent requests in the same HTTP session proceed normally

### 6.4 Draw Name Conventions

Draw names on the web follow the pattern `{EVENT_CODE} {LEVEL}` (e.g. `MS A`, `BS U17`, `XD V`).
Group-stage draws append ` - Group {LETTER}` (e.g. `BS U17 - Group A`).
The playoff draw for the same division uses the bare name (e.g. `BS U17`).

### 6.5 Data Availability Comparison

| Data Point | Excel | Web |
|---|---|---|
| Player names and seeds | Yes | Yes |
| Club per player | Yes (abbreviations) | No (only country code) |
| Draw positions | Yes (explicit) | Inferred from match order |
| Round structure | Yes (column headers) | Inferred from match count |
| Bracket placeholders | Yes ("Winner R1-M1") | Generated structurally |
| Match results/scores | No | Yes (with `--full-results`) |
| Scheduled times | No | Yes (with `--full-results`) |
| Court assignments | No | Yes (with `--full-results`) |

---

## 7. Output JSON Schemas

### 7.1 Division JSON

```json
{
  "tournament": "<tournament name>",
  "name": "<full division name, e.g. Men's Singles C>",
  "code": "<short code, e.g. MS C>",
  "category": "<tab category, e.g. Open C>",
  "format": "elimination | round_robin | group_playoff",
  "draw_type": "main_draw | playoff",
  "is_doubles": false,
  "drawSize": 32,
  "players": [
    {
      "position": 1,
      "name": "Player Name",
      "club": "Club Name",
      "seed": null,
      "status": null
    }
  ],
  "rounds": [
    {
      "name": "Round 1",
      "matches": [
        {
          "match": 1,
          "player1": "Player A",
          "player2": "Player B",
          "note": null
        }
      ]
    }
  ],
  "clubs": ["Club A", "Club B"]
}
```

For group + playoff divisions, additional fields:
```json
{
  "groups": [
    {
      "name": "Group A",
      "players": [...],
      "matches": [...]
    }
  ],
  "playoff": {
    "rounds": [...]
  }
}
```

### 7.2 Tournament Index JSON

```json
{
  "tournament": "<tournament name>",
  "divisions": [
    {
      "file": "<filename>.json",
      "name": "<division name>",
      "code": "<division code>",
      "category": "<category>",
      "draw_type": "main_draw",
      "format": "elimination"
    }
  ],
  "clubs": ["Club A", "Club B"]
}
```

### 7.3 Schedule Session JSON

```json
{
  "session": "Saturday Morning",
  "date": "Saturday",
  "time_range": "09:00 - 13:00",
  "courts": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
  "slots": [
    {
      "time": "09:00",
      "matches": [
        {
          "court": 1,
          "division": "MS C",
          "round": "Round 1",
          "match": 1,
          "player1": "Player A",
          "player2": "Player B",
          "duration": 30
        }
      ]
    }
  ]
}
```

### 7.4 Schedule Index JSON

```json
{
  "sessions": [
    {
      "name": "Saturday Morning",
      "file": "Saturday_Morning.json",
      "date": "Saturday",
      "time_range": "09:00 - 13:00"
    }
  ]
}
```

---

## 8. Scheduling Constraints (Configurable)

These constraints are provided here as defaults from the current tournament. They should be treated as configurable parameters, not hard-coded assumptions.

| Parameter | Default value |
|-----------|---------------|
| Tournament days | 2 (Saturday + Sunday) |
| Courts (Saturday) | 12 (courts 1–12), 9:00–22:00 |
| Courts (Sunday) | Courts 1–4: 9:00–16:00; Courts 5–8: 9:00–18:00 |
| Time slot interval | 30 minutes |
| Standard match duration | 30 minutes |
| Elite match duration | 45 minutes |
| Standard rest period | 30 minutes |
| Elite rest period | 60 minutes |
| Elite court restriction | Courts 5–8 only |
| SF/Final day | Sunday |

---

## 9. Website Features

### 9.1 Tab Structure

The website is organized into tabs derived from the division categories present in the data, plus two special tabs:

- **Division tabs** (one per category, e.g. Open A, Open B, Open C, Junior, Veterans, Elite)
- **Clubs tab** — alphabetical list of clubs with player counts
- **Schedule tab** — session sub-tabs with time x court grids

### 9.2 Visual Design

- Clean, modern card-based layout
- Category-specific color coding (e.g. Junior = green, Open = blue, Veterans = orange, Elite = purple)
- CSS custom properties for theming
- Responsive breakpoint at 600px for mobile
- Tree-style bracket connectors using CSS pseudo-elements

### 9.3 Interactivity

- Tab switching (CSS + minimal vanilla JavaScript)
- Collapsible division cards (click to expand/collapse)
- No external JavaScript libraries

---

## 10. Glossary

| Term | Definition |
|------|-----------|
| Division | A single competitive draw within the tournament (e.g. Men's Singles A) |
| Category | A grouping of related divisions displayed on one tab (e.g. Open A) |
| Event code | Two-letter abbreviation for the event type (MS, WS, MD, WD, XD, BS, BD) |
| Level | The skill/age tier within an event (A, B, C, U11, U13, U15, U17, 35, 45, V) |
| Draw type | Whether a sheet is the main draw or a playoff bracket |
| Elimination | Single-elimination (cup/knockout) bracket format |
| Round-robin | All-play-all pool format |
| Group + Playoff | Preliminary round-robin groups followed by a knockout bracket |
| Session | A contiguous block of play within a day (e.g. Saturday Morning) |
| Bye | An empty draw position; the opponent auto-advances |
| Seed | A ranking designation (e.g. [1], [3/4]) giving a player a protected draw position |
