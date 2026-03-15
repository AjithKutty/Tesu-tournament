# Badminton Tournament Manager

Tournament management toolkit: a Python pipeline that parses draw data (Excel or web), generates match schedules, and builds a static HTML website — plus an Electron desktop app for interactive schedule management during tournament day.

## Project Structure

```
Tesu-Tournament/
├── src/
│   ├── main.py                      # Unified CLI entry point (runs all 3 steps)
│   ├── parse_tournament.py          # Excel → JSON parser
│   ├── parse_web.py                 # Web scraper → JSON parser (same output format)
│   ├── generate_schedule.py         # JSON → schedule JSON
│   ├── generate_website.py          # JSON → HTML website
│   └── api/                         # FastAPI backend for the desktop app
│       ├── server.py                # FastAPI app with CORS, health endpoint
│       ├── models/
│       │   ├── config_schemas.py    # TournamentConfig, DayConfig, SessionConfig, CategoryConfig
│       │   └── schemas.py           # MatchCard, Conflict, SessionInfo, request/response models
│       ├── state/
│       │   └── tournament_state.py  # Core state: matches, schedule, validation, results
│       ├── routes/
│       │   ├── config_routes.py     # GET/POST /api/config, templates, division-map
│       │   ├── import_routes.py     # POST /api/import/excel, /api/import/web
│       │   ├── schedule_routes.py   # GET /api/schedule, POST move/swap/unschedule/pin/generate
│       │   ├── results_routes.py    # POST /api/results/update, /api/results/fetch-web
│       │   ├── print_routes.py      # POST /api/print/match-cards (returns HTML)
│       │   └── export_routes.py     # POST /api/export/website, /api/export/schedule
│       ├── services/
│       │   ├── config_service.py    # Config load/save, template listing, category auto-suggestion
│       │   ├── import_service.py    # Wraps parse_tournament / parse_web
│       │   └── print_service.py     # Match card HTML generation for printing
│       └── templates/
│           └── standard_2day_12court.json  # Built-in tournament config template
├── desktop/                         # Electron + React desktop application
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── electron/
│   │   ├── main.ts                  # Electron main process, spawns Python backend
│   │   └── preload.ts               # contextBridge: file dialogs, print, PDF export
│   └── src/
│       ├── main.tsx                 # React entry point with QueryClientProvider
│       ├── App.tsx                  # Root component, layout orchestrator
│       ├── types/api.ts             # TypeScript interfaces matching Pydantic models
│       ├── api/
│       │   ├── client.ts            # Fetch wrapper (apiGet, apiPost, apiPostFile, apiPostHtml)
│       │   └── endpoints.ts         # Typed API functions for all backend endpoints
│       ├── store/
│       │   └── scheduleStore.ts     # Zustand UI state (selection, panels, dialogs)
│       ├── hooks/
│       │   └── useSchedule.ts       # React Query hooks for data fetching + mutations
│       ├── styles/
│       │   ├── global.css           # CSS variables, base styles
│       │   ├── schedule-board.css   # Grid layout, court headers, time cells
│       │   └── match-card.css       # Card styles, conflict/pinned/completed variants
│       └── components/
│           ├── Layout/
│           │   ├── Toolbar.tsx       # Import, Generate, Validate, Print, Export buttons
│           │   └── SessionTabs.tsx   # Dynamic session tabs with match counts
│           ├── ScheduleBoard/
│           │   ├── ScheduleBoard.tsx       # CSS Grid board with DndContext
│           │   ├── MatchCard.tsx           # Match card display component
│           │   ├── DraggableMatchCard.tsx  # @dnd-kit draggable wrapper
│           │   └── DroppableCell.tsx       # @dnd-kit droppable grid cell
│           ├── Panels/
│           │   ├── ConflictPanel.tsx       # Right sidebar: errors/warnings list
│           │   └── UnscheduledPanel.tsx    # Bottom drawer: unplaced matches
│           └── Modals/
│               ├── ImportDialog.tsx        # Excel/web import with division mapping
│               ├── MatchDetailModal.tsx    # Score entry, pin, swap, unschedule
│               └── PrintDialog.tsx         # Time slot picker, print/PDF export
├── output/                          # Generated files (gitignored)
│   ├── divisions/                   # JSON files (one per division)
│   ├── schedules/                   # Schedule JSON files
│   └── webpages/
│       └── index.html               # Generated single-page website
├── docs/
│   ├── requirements/
│   │   ├── requirements.md
│   │   └── scheduling-rules.md
│   ├── architecture/
│   │   └── scheduling-proposal.md
│   ├── implementation/
│   │   ├── implementation-plan.md
│   │   ├── website-schedule-plan.md
│   │   └── web-scraper-plan.md
│   └── desktop-app/
│       ├── app-requirements.md      # User stories and acceptance criteria
│       ├── architecture.md          # System design, API, components, data flow
│       └── implementation-plan.md   # 6-phase task breakdown
├── requirements.txt                 # Python deps
├── CLAUDE.md
└── README.md
```

## Python Pipeline

### Workflow

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

### Starting the API backend standalone

```bash
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1
```

The backend runs on `http://127.0.0.1:8741`. Endpoints: `/api/health`, `/api/config`, `/api/import/*`, `/api/schedule/*`, `/api/results/*`, `/api/print/*`, `/api/export/*`.

## Desktop App

### Development

```bash
# Terminal 1: Start Python backend
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1 --reload

# Terminal 2: Start Electron + Vite dev server
cd desktop
npm install
npm run dev
```

In dev mode, Vite serves the React app on `http://localhost:5173` and Electron loads from there with hot-reload.

### Production build

```bash
cd desktop
npm run build    # tsc → vite build → electron-builder
```

### How the desktop app works

- **Electron main process** (`electron/main.ts`) spawns the Python backend as a child process, waits for its health check, then opens the window.
- **React frontend** communicates with the backend via REST API on port 8741.
- **Drag-and-drop**: Uses `@dnd-kit/core`. Drag a match card to an empty cell = move. Drag onto an occupied cell = swap. Double-click a card to enter swap mode, then click the target.
- **Conflict detection**: Backend validates scheduling rules (double-bookings, rest violations, court restrictions) and returns conflicts with each schedule mutation.
- **Printing**: Backend generates HTML match cards → Electron hidden BrowserWindow → system print dialog or PDF export.
- **Tournament config**: All tournament parameters (name, days, courts, sessions, categories, durations, rest periods, court restrictions) are configurable via TournamentConfig JSON. The app is not specific to any single tournament.

## Key Conventions

- **Do not hand-edit `output/`** — all files there are generated. Fix the source scripts or use the desktop app instead.
- Python 3 with `openpyxl`, `requests`, `beautifulsoup4`, `lxml`, `fastapi`, `uvicorn`, `pydantic`. Install via `pip install -r requirements.txt`.
- Both input modes (Excel and web) produce identical JSON output format — downstream pipeline is shared.
- The desktop app wraps the existing pipeline — it does not rewrite it. `TournamentState` in the backend calls into `generate_schedule.py`, `parse_tournament.py`, etc.
- `CourtSchedule.unbook()` in `generate_schedule.py` supports removing bookings for match move/swap operations.

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

Source: Excel export from badmintonfinland.tournamentsoftware.com

- One sheet per division draw
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

## Testing Changes

### Python pipeline

After modifying any script, run the full pipeline with both input modes:
```bash
python src/main.py                          # Excel mode
python src/main.py --source web --url "..."  # Web mode
```
Then open `output/webpages/index.html` in a browser and verify:
- All tabs work (Open A/B/C, Junior, Veterans, Elite, Clubs, Schedule)
- Elimination divisions show full bracket (R1 through Final) with tree-style connectors
- Group+playoff divisions show groups + playoff bracket
- Round-robin divisions show VS match cards
- Schedule tab shows session sub-tabs with time x court grids
- 45-min Elite matches span two rows in schedule grid
- No "Bye" entries in player lists

### Desktop app

```bash
cd desktop
npx tsc --noEmit       # Type check
npx vite build         # Production build (frontend + electron)
```

For end-to-end testing, start the Python backend and then the Electron app:
```bash
# Terminal 1
cd src && python -m uvicorn api.server:app --port 8741 --host 127.0.0.1

# Terminal 2
cd desktop && npm run dev
```

Verify:
- Import dialog opens and accepts Excel file or web URL
- Schedule generates and displays on the time x court grid
- Match cards can be dragged to different cells (move) or onto other cards (swap)
- Double-click enters swap mode, clicking another card swaps them
- Match detail modal opens on click, allows score entry
- Conflict panel shows errors/warnings and clicking highlights the match
- Print dialog allows time-slot selection and prints/exports PDF
- Validate button runs full schedule validation
- Export generates website HTML and schedule JSON

### API backend

```bash
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1
curl http://127.0.0.1:8741/api/health
```
