# Badminton Tournament Manager

A toolkit for managing badminton tournament scheduling. Includes a Python pipeline for parsing draw data, generating schedules, and building a tournament website — plus an Electron desktop app for interactive schedule management on tournament day.

## Features

- **Import tournament data** from Excel exports or by scraping tournamentsoftware.com
- **Auto-generate schedules** respecting court availability, rest periods, and division rules
- **Visual schedule board** — time x court grid with drag-and-drop match placement
- **Conflict detection** — double-bookings, rest violations, court restrictions highlighted in real-time
- **Score entry** — record match results and auto-resolve "Winner of..." placeholders in later rounds
- **Print match cards** — filter by time slot, print directly or export to PDF
- **Export** — generate the tournament website or schedule JSON at any point
- **Configurable** — tournament name, days, courts, sessions, categories, durations, and rules are all parameterised via a JSON config. Not tied to any specific tournament.

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and **npm** (for the desktop app)

## Installation

### Python dependencies

```bash
pip install -r requirements.txt
```

This installs: `openpyxl`, `requests`, `beautifulsoup4`, `lxml`, `fastapi`, `uvicorn`, `python-multipart`, `pydantic`.

### Desktop app dependencies

```bash
cd desktop
npm install
```

## Usage

### Option 1: Command-Line Pipeline

Run the full pipeline to parse data, generate a schedule, and build the website in one step:

```bash
# From an Excel file (default):
python src/main.py
python src/main.py --source excel --file "path/to/draws.xlsx"

# From a tournamentsoftware.com URL:
python src/main.py --source web --url "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=..."

# Web scraping with match results and scores:
python src/main.py --source web --url "..." --full-results
```

Output is written to `output/`:
- `output/divisions/*.json` — parsed division data
- `output/schedules/*.json` — generated schedule
- `output/webpages/index.html` — tournament website (open in a browser)

Individual steps can be run separately:

```bash
python src/parse_tournament.py                # Step 1: Excel → JSON
python src/parse_web.py "URL"                 # Step 1 alt: Web → JSON
python src/generate_schedule.py               # Step 2: JSON → schedule
python src/generate_website.py                # Step 3: JSON → website
```

### Option 2: Desktop Application

The desktop app provides an interactive GUI for managing the schedule during the tournament.

#### Development mode

Run the Python backend and Electron app in separate terminals:

```bash
# Terminal 1: Start the API backend with auto-reload
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1 --reload

# Terminal 2: Start the Electron app with Vite dev server
cd desktop
npm run dev
```

The Vite dev server runs on `http://localhost:5173` with hot-reload. The API backend runs on `http://127.0.0.1:8741`.

#### Production build

```bash
cd desktop
npm run build
```

This runs TypeScript compilation, Vite bundling, and electron-builder packaging.

#### Using the desktop app

1. **Import data** — Click "Import" in the toolbar. Choose Excel file upload or enter a web URL. After import, map divisions to categories (the app auto-suggests based on naming patterns).

2. **Generate schedule** — Click "Generate" to auto-schedule all matches. The scheduler respects court availability, category durations, rest periods, and court restrictions from the tournament config.

3. **Adjust the schedule** — Drag match cards to move them to different time slots and courts. Drag onto another card to swap positions. Double-click a card to enter swap mode, then click the target card.

4. **Enter results** — Click a match card to open the detail modal. Enter the score (e.g. `21-15 21-18`) and save. The app auto-resolves "Winner of..." placeholders in downstream bracket matches.

5. **Check conflicts** — The conflict panel (right sidebar) shows scheduling errors and warnings. Click a conflict to highlight the affected match. Use "Validate" in the toolbar for a full schedule check.

6. **Print match cards** — Click "Print" to open the print dialog. Optionally select a specific time slot to print only matches starting at that time. Print directly or save as PDF.

7. **Export** — Click "Export" to regenerate the tournament website. Right-click for schedule JSON export.

### Option 3: API Backend Only

The FastAPI backend can be used independently for integrations or custom frontends:

```bash
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1
```

**Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Get tournament config |
| POST | `/api/config` | Set tournament config |
| GET | `/api/config/templates` | List built-in config templates |
| POST | `/api/config/load` | Load config from file |
| POST | `/api/config/save` | Save config to file |
| POST | `/api/config/division-map` | Set division-to-category mapping |
| POST | `/api/import/excel` | Import from Excel file (multipart) |
| POST | `/api/import/web` | Import from web URL |
| GET | `/api/schedule` | Get full schedule state |
| POST | `/api/schedule/generate` | Generate/regenerate schedule |
| POST | `/api/schedule/move` | Move a match to court + time |
| POST | `/api/schedule/swap` | Swap two matches |
| POST | `/api/schedule/unschedule` | Remove a match from the schedule |
| POST | `/api/schedule/pin` | Pin/unpin a match |
| GET | `/api/schedule/validate` | Run full validation |
| POST | `/api/schedule/validate-move` | Preview conflicts for a move |
| POST | `/api/results/update` | Update match result/score |
| POST | `/api/results/fetch-web` | Fetch results from web (stub) |
| POST | `/api/print/match-cards` | Generate printable HTML for match cards |
| POST | `/api/export/website` | Export tournament website |
| POST | `/api/export/schedule` | Export schedule JSON |

## Tournament Configuration

The desktop app uses a `TournamentConfig` JSON to define all tournament parameters. A built-in template (`standard_2day_12court`) is included. The config controls:

- **Tournament name** and metadata
- **Days** with court availability windows per court
- **Sessions** (named time blocks, e.g. "Saturday Morning")
- **Categories** with match duration, rest period, required/preferred courts, and semi-final/final day rules
- **Division-to-category mapping** — assigns each division (e.g. "MS A") to a category (e.g. "elite")
- **Slot duration** — grid resolution in minutes (default 30)

Example config structure:

```json
{
  "name": "My Tournament 2025",
  "slot_duration_minutes": 30,
  "days": [
    {
      "label": "Saturday",
      "date": "2025-03-15",
      "courts": [
        { "court": 1, "available_from": "09:00", "available_to": "20:00" },
        { "court": 2, "available_from": "09:00", "available_to": "20:00" }
      ]
    }
  ],
  "sessions": [
    { "name": "Saturday Morning", "day_index": 0, "start_time": "09:00", "end_time": "13:00" }
  ],
  "categories": [
    {
      "id": "open",
      "label": "Open",
      "color": "#4a90d9",
      "duration_minutes": 30,
      "rest_minutes": 30
    }
  ],
  "division_category_map": {
    "MS A": "open",
    "WS A": "open"
  }
}
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Electron Shell                  │
│  ┌───────────────────────────────────────────┐  │
│  │           React Frontend (Vite)           │  │
│  │  ┌─────────┐ ┌──────────┐ ┌───────────┐  │  │
│  │  │ Schedule │ │ Conflict │ │   Print   │  │  │
│  │  │  Board   │ │  Panel   │ │  Dialog   │  │  │
│  │  │ (DnD)   │ │          │ │           │  │  │
│  │  └─────────┘ └──────────┘ └───────────┘  │  │
│  │       @dnd-kit  │  React Query  │ Zustand │  │
│  └───────────────────────────────────────────┘  │
│                      │ REST API                  │
│  ┌───────────────────────────────────────────┐  │
│  │         Python FastAPI Backend             │  │
│  │    TournamentState (in-memory store)       │  │
│  │    ┌────────────┐  ┌───────────────────┐  │  │
│  │    │ Scheduling │  │ Conflict          │  │  │
│  │    │ Engine     │  │ Detection         │  │  │
│  │    └────────────┘  └───────────────────┘  │  │
│  │    Wraps: parse_tournament.py,            │  │
│  │    parse_web.py, generate_schedule.py,    │  │
│  │    generate_website.py                    │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Electron |
| Frontend | React 18, TypeScript, Vite |
| Drag-and-drop | @dnd-kit/core |
| Server state | @tanstack/react-query |
| Client state | Zustand |
| Backend | Python, FastAPI, Uvicorn, Pydantic |
| Data parsing | openpyxl (Excel), BeautifulSoup4 (web scraping) |
| Website generation | Pure Python string formatting |

## Testing

### Python pipeline

```bash
# Run full pipeline with Excel input
python src/main.py

# Run full pipeline with web input
python src/main.py --source web --url "..."

# Verify output
# Open output/webpages/index.html in a browser
```

### Desktop app

```bash
cd desktop

# Type check
npx tsc --noEmit

# Production build
npx vite build
```

### API backend

```bash
cd src
python -m uvicorn api.server:app --port 8741 --host 127.0.0.1

# Health check
curl http://127.0.0.1:8741/api/health
```

## Project Documentation

Detailed design documents are in `docs/`:

- `docs/desktop-app/app-requirements.md` — User stories and acceptance criteria
- `docs/desktop-app/architecture.md` — System architecture, API design, component design
- `docs/desktop-app/implementation-plan.md` — 6-phase implementation plan
- `docs/requirements/requirements.md` — Original pipeline requirements
- `docs/requirements/scheduling-rules.md` — Scheduling rules and constraints
- `docs/architecture/scheduling-proposal.md` — Scheduling algorithm design
