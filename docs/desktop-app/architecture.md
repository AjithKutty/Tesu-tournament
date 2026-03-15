# Architecture — Tournament Manager Desktop Application

## 1. System Overview

```
+-------------------------------------------------------------------+
|  Electron Main Process (main.ts)                                   |
|  - Window management, file dialogs, print/PDF                     |
|  - Spawns Python backend as child_process                         |
|  - IPC bridge (contextBridge) to renderer                         |
+-------------------------------------------------------------------+
        |                                      |
        | IPC                                  | child_process.spawn
        v                                      v
+------------------------+          +---------------------------+
| Electron Renderer      |  REST    | Python FastAPI Backend    |
| (React + TypeScript)   | <------> | (localhost:8741)          |
| - Schedule Board       |  JSON    | - Wraps existing modules  |
| - Match Cards (DnD)    |          | - In-memory state         |
| - Conflict Panel       |          | - Tournament config       |
| - Print Preview        |          | - Validation engine       |
| - Config Editor        |          | - Import/export           |
+------------------------+          +---------------------------+
                                           |
                                    imports as modules
                                           v
                                   +----------------------+
                                   | Existing Pipeline    |
                                   |  parse_tournament.py |
                                   |  parse_web.py        |
                                   |  generate_schedule.py |
                                   |  generate_website.py |
                                   +----------------------+
```

The Python backend is the **source of truth** for all schedule state and tournament configuration. The frontend queries and mutates state via REST API calls. The backend wraps the existing pipeline scripts as importable modules — no rewrite of existing code.

**Key design principle**: All tournament-specific data is parameterised. Nothing is hardcoded for a specific tournament — names, dates, court counts, session boundaries, division categories, match durations, rest periods, and court restrictions are all part of the tournament configuration.

---

## 2. Tournament Configuration Model

The tournament configuration is a JSON document that drives all scheduling behaviour. The app provides a UI to create/edit this config, and also ships with templates.

### 2.1 Configuration Schema

```python
class CourtAvailability(BaseModel):
    court: int                        # Court number (1-based)
    available_from: str               # "09:00"
    available_to: str                 # "22:00"

class DayConfig(BaseModel):
    label: str                        # "Saturday", "Sunday", "Day 1"
    date: str | None = None           # "2025-11-15" (optional)
    courts: list[CourtAvailability]   # Which courts and when

class SessionConfig(BaseModel):
    name: str                         # "Saturday Morning"
    day_index: int                    # 0 = first day, 1 = second day
    start_time: str                   # "09:00"
    end_time: str                     # "13:00"

class CategoryConfig(BaseModel):
    id: str                           # "elite", "junior", "open_a"
    label: str                        # "Elite", "Junior", "Open A"
    color: str                        # "#805ad5"
    duration_minutes: int             # 45
    rest_minutes: int                 # 60
    required_courts: list[int] | None = None     # [5,6,7,8] — must use these
    preferred_courts: list[int] | None = None    # [9,10,11,12] — try these first
    sf_final_day_index: int | None = None        # 1 = must be on day 2 (0-based)

class TournamentConfig(BaseModel):
    name: str                         # "Kumpoo Tervasulan Eliitti 2025"
    slot_duration_minutes: int = 30   # Grid slot size
    days: list[DayConfig]
    sessions: list[SessionConfig]
    categories: list[CategoryConfig]
    division_category_map: dict[str, str] = {}  # "MS A" → "open_a"
```

### 2.2 Default Template (Tervasulka-style)

```json
{
  "name": "",
  "slot_duration_minutes": 30,
  "days": [
    {
      "label": "Saturday",
      "courts": [
        {"court": 1, "available_from": "09:00", "available_to": "22:00"},
        {"court": 2, "available_from": "09:00", "available_to": "22:00"},
        ...
        {"court": 12, "available_from": "09:00", "available_to": "22:00"}
      ]
    },
    {
      "label": "Sunday",
      "courts": [
        {"court": 1, "available_from": "09:00", "available_to": "16:00"},
        ...
        {"court": 4, "available_from": "09:00", "available_to": "16:00"},
        {"court": 5, "available_from": "09:00", "available_to": "18:00"},
        ...
        {"court": 8, "available_from": "09:00", "available_to": "18:00"}
      ]
    }
  ],
  "sessions": [
    {"name": "Saturday Morning", "day_index": 0, "start_time": "09:00", "end_time": "13:00"},
    {"name": "Saturday Afternoon", "day_index": 0, "start_time": "13:00", "end_time": "18:00"},
    {"name": "Saturday Evening", "day_index": 0, "start_time": "18:00", "end_time": "22:00"},
    {"name": "Sunday Morning", "day_index": 1, "start_time": "09:00", "end_time": "13:00"},
    {"name": "Sunday Afternoon", "day_index": 1, "start_time": "13:00", "end_time": "18:00"}
  ],
  "categories": [
    {"id": "elite", "label": "Elite", "color": "#805ad5", "duration_minutes": 45, "rest_minutes": 60, "required_courts": [5,6,7,8], "sf_final_day_index": 1},
    {"id": "open_a", "label": "Open A", "color": "#3182ce", "duration_minutes": 30, "rest_minutes": 30, "preferred_courts": [5,6,7,8], "sf_final_day_index": 1},
    {"id": "open_b", "label": "Open B", "color": "#3182ce", "duration_minutes": 30, "rest_minutes": 30, "sf_final_day_index": 1},
    {"id": "open_c", "label": "Open C", "color": "#3182ce", "duration_minutes": 30, "rest_minutes": 30, "sf_final_day_index": 1},
    {"id": "junior", "label": "Junior", "color": "#38a169", "duration_minutes": 30, "rest_minutes": 30, "preferred_courts": [9,10,11,12], "sf_final_day_index": 1},
    {"id": "veterans", "label": "Veterans", "color": "#dd6b20", "duration_minutes": 30, "rest_minutes": 30, "sf_final_day_index": 1}
  ],
  "division_category_map": {}
}
```

### 2.3 How Configuration Drives the System

| Feature | Uses Configuration |
|---|---|
| Schedule grid dimensions | `days[].courts[]` → columns; `sessions[].start/end` + `slot_duration_minutes` → rows |
| Session tabs | `sessions[]` → tab labels and boundaries |
| Match card colors | `categories[].color` → left border color per division |
| Match duration / row span | `categories[].duration_minutes` / `slot_duration_minutes` → number of rows |
| Court eligibility | `categories[].required_courts` and `preferred_courts` |
| Rest validation | `categories[].rest_minutes` |
| SF/Final day rule | `categories[].sf_final_day_index` |
| Court availability | `days[].courts[].available_from/to` |
| Auto-scheduling | All of the above fed into the scheduling algorithm |

---

## 3. Python Backend (FastAPI)

### 3.1 State Model

```python
class TournamentState:
    """In-memory state for the active tournament session."""
    config: TournamentConfig           # Tournament configuration
    matches: list[Match]               # All schedulable matches
    match_by_id: dict[str, Match]      # Quick lookup
    scheduled: dict[str, tuple]        # match_id → (court, minute)
    court_sched: CourtSchedule         # Court booking tracker
    player_tracker: PlayerTracker      # Player availability tracker
    pinned: set[str]                   # Manually placed match IDs
    results: dict[str, str]            # match_id → score string
    divisions: list[dict]              # Raw division JSON data
```

Key design decisions:
- `CourtSchedule` and `PlayerTracker` are **rebuilt from scratch** after any mutation (move/swap/unschedule). Fast enough for 300+ matches.
- A new `CourtSchedule.unbook()` method is added to support removals.
- `pinned` matches are preserved during schedule regeneration.
- `results` are stored separately and applied to resolve "Winner of..." placeholders.
- `config` drives all scheduling rules — no hardcoded constants in the API layer.

### 3.2 API Endpoints

#### Configuration

```
GET /api/config
  Response: TournamentConfig

POST /api/config
  Request: TournamentConfig
  Response: TournamentConfig
  Note: Creates or replaces the tournament configuration.

GET /api/config/templates
  Response: { "templates": [{"id": "standard_2day_12court", "name": "Standard 2-day 12-court", ...}] }

POST /api/config/save
  Request: { "path": "C:/path/to/config.json" }  (optional; default: auto-save location)
  Response: { "path": "..." }

POST /api/config/load
  Request: { "path": "C:/path/to/config.json" }
  Response: TournamentConfig
```

#### Import

```
POST /api/import/excel
  Request: multipart/form-data with file field
  Response: {
    "tournament_name": "...",
    "division_count": 32,
    "match_count": 234,
    "player_count": 156,
    "divisions": [{"code": "MS A", "name": "...", "suggested_category": "open_a"}, ...]
  }

POST /api/import/web
  Request: { "url": "https://...", "full_results": false }
  Response: (same as above)
```

#### Division-Category Mapping

```
POST /api/config/division-map
  Request: { "division_category_map": {"MS A": "open_a", "MS V": "elite", ...} }
  Response: TournamentConfig
  Note: Updates the division → category mapping after import.
```

#### Schedule

```
GET /api/schedule
  Response: {
    "matches": [MatchCard, ...],
    "conflicts": [Conflict, ...],
    "unscheduled": ["match_id", ...],
    "sessions": [SessionInfo, ...]
  }

POST /api/schedule/generate
  Request: { "keep_pinned": true }
  Response: (same as GET /api/schedule)

POST /api/schedule/move
  Request: { "match_id": "MS A:Round 1:M1", "court": 5, "time_minute": 60 }
  Response: {
    "match": MatchCard,
    "conflicts": [Conflict, ...]
  }

POST /api/schedule/swap
  Request: { "match_id_a": "...", "match_id_b": "..." }
  Response: {
    "matches": [MatchCard, MatchCard],
    "conflicts": [Conflict, ...]
  }

POST /api/schedule/unschedule
  Request: { "match_id": "..." }
  Response: { "match": MatchCard }

POST /api/schedule/pin
  Request: { "match_id": "...", "pinned": true }
  Response: { "match": MatchCard }

GET /api/schedule/validate
  Response: { "conflicts": [Conflict, ...] }

POST /api/schedule/validate-move
  Request: { "match_id": "...", "court": 5, "time_minute": 60 }
  Response: { "conflicts": [Conflict, ...] }
  Note: Preview only — does NOT commit the move.
```

#### Results

```
POST /api/results/update
  Request: { "match_id": "...", "score": "21-15 21-18" }
  Response: {
    "match": MatchCard,
    "resolved_matches": [MatchCard, ...]
  }

POST /api/results/fetch-web
  Request: { "url": "https://..." }
  Response: {
    "updated_matches": [MatchCard, ...],
    "new_results_count": 5
  }
```

#### Print & Export

```
POST /api/print/match-cards
  Request: { "time_minute": 60 } or { "match_ids": ["...", "..."] }
  Response: HTML string (print-optimized, includes tournament name from config)

POST /api/export/website
  Response: { "path": "output/webpages/index.html" }

POST /api/export/schedule
  Response: { "path": "output/schedules/" }
```

### 3.3 Pydantic Models

```python
class MatchCard(BaseModel):
    id: str                        # "MS A:Round 1:M1"
    division_code: str             # "MS A"
    division_name: str             # "Men's Singles A"
    category_id: str               # "open_a"
    category_label: str            # "Open A"
    category_color: str            # "#3182ce"
    round_name: str                # "Round 1"
    match_num: int                 # 1
    player1: str
    player2: str
    duration_min: int              # from category config
    is_sf_or_final: bool
    has_real_players: bool
    prerequisites: list[str]
    result: str | None = None
    court: int | None = None
    time_minute: int | None = None
    time_display: str | None = None
    day: str | None = None
    pinned: bool = False
    conflict_ids: list[str] = []

class Conflict(BaseModel):
    id: str
    type: str                      # "double_booking", "rest_violation", "wrong_court", etc.
    severity: str                  # "error" or "warning"
    match_ids: list[str]
    message: str
    player: str | None = None

class SessionInfo(BaseModel):
    name: str
    day_label: str
    start_time: str
    end_time: str
    start_minute: int
    end_minute: int
    courts: list[int]
    match_count: int
```

### 3.4 Backend File Structure

```
src/api/
  server.py                       # FastAPI app, CORS, lifespan
  routes/
    config_routes.py              # /api/config/*
    import_routes.py              # /api/import/*
    schedule_routes.py            # /api/schedule/*
    results_routes.py             # /api/results/*
    export_routes.py              # /api/export/*
    print_routes.py               # /api/print/*
  models/
    schemas.py                    # Pydantic models (MatchCard, Conflict, etc.)
    config_schemas.py             # TournamentConfig, CategoryConfig, etc.
  state/
    tournament_state.py           # TournamentState class
  services/
    config_service.py             # Config load/save, templates, category auto-mapping
    import_service.py             # Wraps parse_tournament / parse_web
    schedule_service.py           # Wraps generate_schedule, config-aware
    conflict_service.py           # Scoped + full validation, config-driven rules
    result_service.py             # Result entry + placeholder resolution
    print_service.py              # Match card HTML generation
  templates/
    standard_2day_12court.json    # Built-in template
    small_1day_6court.json        # Built-in template
```

### 3.5 Config-Driven Scheduling Adaptation

The existing `generate_schedule.py` has hardcoded constants. Rather than modifying it extensively, the API backend **adapts** the config into the format the existing code expects:

1. **Time model**: Convert `days[].courts[].available_from/to` into minute offsets (same scheme: day 1 starts at 0, day 2 at 1440, etc.)
2. **Court eligibility**: Convert `categories[].required_courts/preferred_courts` into the `get_eligible_courts()` format
3. **Durations & rest**: Override per-match `duration_min` and `rest_min` from the category config
4. **Sessions**: Generate `SESSIONS` list from config
5. **Validation rules**: Feed config values into `validate_schedule()` instead of hardcoded constants

This adaptation layer lives in `schedule_service.py` and `conflict_service.py`.

### 3.6 Modifications to Existing Code

**`src/generate_schedule.py`** — Add one method:

```python
class CourtSchedule:
    def unbook(self, court, minute, duration_min):
        """Remove a booking. Inverse of book()."""
        slots_needed = (duration_min + SLOT_DURATION - 1) // SLOT_DURATION
        for i in range(slots_needed):
            self.booked.pop((court, minute + i * SLOT_DURATION), None)
```

No other modifications to existing files. The API layer wraps and adapts, rather than rewriting.

---

## 4. Frontend Architecture (Electron + React)

### 4.1 Technology Stack

| Library | Purpose |
|---|---|
| Electron 28+ | Desktop shell, file dialogs, print |
| React 18 | UI components |
| TypeScript 5 | Type safety |
| Vite 5 | Build tooling |
| @dnd-kit/core | Drag-and-drop |
| @tanstack/react-query 5 | Server state management (API caching) |
| Zustand 4 | Client UI state |
| electron-vite | Electron + Vite integration |

### 4.2 Component Tree

```
App
├── WelcomeScreen (shown when no tournament loaded)
│   ├── NewTournamentButton → opens ConfigWizard
│   ├── LoadConfigButton → file picker
│   └── TemplateList → quick-start templates
│
├── ConfigWizard (modal)
│   ├── Step 1: Tournament name + dates
│   ├── Step 2: Court setup per day
│   ├── Step 3: Session boundaries
│   ├── Step 4: Category definitions (color, duration, rest, courts)
│   └── Step 5: Review + save
│
├── Toolbar
│   ├── ImportButton → opens ImportDialog
│   ├── GenerateButton → POST /api/schedule/generate
│   ├── ValidateButton → GET /api/schedule/validate
│   ├── PrintButton → opens PrintPreview
│   ├── ExportButton → POST /api/export/website
│   └── ConfigButton → opens ConfigWizard for editing
│
├── SessionTabs (dynamically generated from config.sessions)
│
├── MainContent
│   ├── ScheduleBoard
│   │   ├── CourtHeader (dynamic: config.days[day_index].courts)
│   │   ├── TimeColumn (dynamic: session start/end, slot duration)
│   │   └── GridCell[] (drop targets)
│   │       └── MatchCard (draggable)
│   │           ├── Category color bar (from config)
│   │           ├── Division + Round label
│   │           ├── Player names
│   │           ├── Pin icon (if pinned)
│   │           ├── Result badge (if completed)
│   │           └── Warning icon (if conflict)
│   │
│   └── UnscheduledPanel (bottom drawer)
│       └── MatchCard[] (draggable onto grid)
│
├── ConflictPanel (right sidebar)
│   ├── Error count + Warning count
│   └── ConflictItem[] (clickable → scrolls to match)
│
├── MatchDetailModal (on card click)
│   ├── Full match details
│   ├── Score entry form (Set 1, 2, 3)
│   └── Pin/unpin toggle
│
├── ImportDialog (modal)
│   ├── Tab: Excel file picker
│   ├── Tab: Web URL input
│   └── After import: DivisionMappingEditor
│
├── DivisionMappingEditor (modal/screen after import)
│   ├── Table: Division code | Suggested category | Override dropdown
│   └── Confirm button
│
└── PrintPreview (modal)
    ├── Time slot selector
    ├── Match card preview grid
    ├── Print button
    └── Export PDF button
```

### 4.3 State Management

**React Query** (server state):
- `useQuery('config')` → `GET /api/config`
- `useQuery('schedule')` → `GET /api/schedule`
- `useMutation('move')` → `POST /api/schedule/move` with optimistic update
- `useMutation('swap')` → `POST /api/schedule/swap`
- Cache invalidation after mutations

**Zustand store** (UI state):
```typescript
interface ScheduleStore {
  selectedSession: string;        // Session name from config
  selectedMatch: string | null;   // match ID for detail modal
  swapMode: { first: string | null };
  filters: {
    categories: string[];         // filter by category IDs
    search: string;
  };
  zoom: number;
  conflictPanelOpen: boolean;
  unscheduledPanelOpen: boolean;
  configWizardOpen: boolean;
}
```

### 4.4 Drag-and-Drop Flow

Using `@dnd-kit/core`:

1. **DragStart**: Store dragged match ID, highlight eligible grid cells based on category court rules from config
2. **DragOver**: Show ghost card at cursor position; debounced call to `POST /api/schedule/validate-move` (200ms) to preview conflicts
3. **DragEnd**: Call `POST /api/schedule/move`; optimistic UI update (move card immediately, revert if API error)
4. **Drop on unscheduled panel**: Call `POST /api/schedule/unschedule`

Swap mode (alternative to drag):
1. Click card A → stored in `swapMode.first`, card A highlighted with blue border
2. Click card B → call `POST /api/schedule/swap`; clear swap mode
3. Click same card or press Escape → cancel swap mode

### 4.5 Frontend File Structure

```
desktop/
  package.json
  electron-builder.yml
  electron/
    main.ts                       # Electron main process
    preload.ts                    # contextBridge for IPC
    pythonManager.ts              # Spawn/manage Python backend
  src/
    main.tsx                      # React entry point
    App.tsx                       # Root component
    api/
      client.ts                   # fetch wrapper for localhost:8741
      endpoints.ts                # Typed API functions
    components/
      Layout/
        AppShell.tsx
        Toolbar.tsx
        SessionTabs.tsx
        WelcomeScreen.tsx
      Config/
        ConfigWizard.tsx
        DaySetup.tsx
        SessionSetup.tsx
        CategoryEditor.tsx
        DivisionMappingEditor.tsx
      ScheduleBoard/
        ScheduleBoard.tsx
        CourtHeader.tsx
        TimeColumn.tsx
        GridCell.tsx
        MatchCard.tsx
      Panels/
        ConflictPanel.tsx
        UnscheduledPanel.tsx
      Modals/
        MatchDetailModal.tsx
        ImportDialog.tsx
        PrintPreview.tsx
    hooks/
      useSchedule.ts              # React Query hooks
      useConfig.ts                # Config query/mutation hooks
      useDragAndDrop.ts
      useConflicts.ts
    store/
      scheduleStore.ts            # Zustand
    types/
      api.ts                      # Matches Pydantic models
      config.ts                   # TournamentConfig types
    styles/
      global.css
      schedule-board.css
      match-card.css
      print.css
      config-wizard.css
    vite.config.ts
    tsconfig.json
```

---

## 5. Conflict Detection Design

### 5.1 Scoped Validation (Real-time, per move)

After each `POST /api/schedule/move` or `/swap`, the backend runs a scoped check on only the moved match and its related matches (same players). This returns in <50ms.

Checks performed (all config-driven):
1. **Player double-booking**: Any player in the moved match already playing at the same time
2. **Rest violation**: Any player in the moved match with less than `category.rest_minutes` gap to another match
3. **Court eligibility**: Match placed on a court not in `category.required_courts` (error) or not in `preferred_courts` (warning)
4. **Court availability**: Match placed on a court at a time outside `days[].courts[].available_from/to`
5. **Prerequisite ordering**: Match placed before its feeder match finishes
6. **SF/Final day rule**: SF/Final placed on a day other than `category.sf_final_day_index`

### 5.2 Full Validation (On-demand)

Wraps existing `validate_schedule()` logic but uses config values instead of hardcoded constants. Runs across all matches. Called by "Validate All" button and before export.

### 5.3 Conflict Lifecycle

Conflicts are recalculated after every state mutation and returned with the API response. The frontend replaces its conflict list with each response — no stale conflict accumulation.

---

## 6. Print/PDF Pipeline

1. Frontend sends `POST /api/print/match-cards` with time filter or match ID list
2. Backend generates print-optimized HTML with CSS `@media print` rules, including tournament name from config
3. Frontend passes HTML to Electron main process via IPC
4. Main process creates a hidden `BrowserWindow`, loads the HTML
5. For direct print: `win.webContents.print()` → opens OS print dialog
6. For PDF export: `win.webContents.printToPDF()` → saves via `dialog.showSaveDialog()`

Match card layout (A4, 4 per page in 2x2 grid):
```
+-------------------------------+
| TOURNAMENT NAME               |
| Court 5  |  10:30 Saturday    |
| MS A - Round 1 - Match 3     |
|                               |
| Player 1 (Club) [seed]       |
|          vs                   |
| Player 2 (Club)              |
|                               |
| Set 1: ___-___                |
| Set 2: ___-___                |
| Set 3: ___-___                |
+-------------------------------+
```

---

## 7. Data Flow

### Configuration Flow
```
User creates new tournament / loads config file
  → Frontend POST /api/config (or /api/config/load)
  → Backend stores TournamentConfig in memory
  → Backend adapts config into scheduling parameters
  → Returns config to frontend
  → Frontend renders grid/sessions/categories per config
```

### Import Flow
```
User selects Excel file / enters URL
  → Frontend POST /api/import/excel or /api/import/web
  → Backend calls parse_tournament.main() or parse_web.main()
  → Writes JSON to output/divisions/
  → Backend auto-suggests division → category mapping
  → Returns import summary + suggestions to frontend
  → User reviews/adjusts mapping in DivisionMappingEditor
  → Frontend POST /api/config/division-map
  → Backend loads matches into TournamentState with correct categories
```

### Schedule Generation Flow
```
User clicks "Generate"
  → Frontend POST /api/schedule/generate { keep_pinned: true }
  → Backend: read durations/rest/courts from config per category
  → Backend: pre-place pinned matches in CourtSchedule
  → Backend: run schedule_matches() for remaining matches
  → Backend: run validate_schedule() with config-driven rules
  → Returns full ScheduleState to frontend
  → Frontend renders grid
```

### Move Flow
```
User drags card to new cell
  → Frontend optimistically moves card
  → Frontend POST /api/schedule/move { match_id, court, time_minute }
  → Backend: unbook old slot, book new slot, rebuild PlayerTracker
  → Backend: run scoped validation using config rules
  → Returns updated match + conflicts
  → Frontend applies response (or reverts on error)
```

### Result Entry Flow
```
User enters score in modal
  → Frontend POST /api/results/update { match_id, score }
  → Backend: store result, find downstream "Winner of..." matches
  → Backend: resolve placeholders with actual winner name
  → Returns updated match + resolved downstream matches
  → Frontend updates affected cards
```

---

## 8. Dependencies

### Python (add to requirements.txt)
```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.6
pydantic>=2.5.0
```

### Frontend (desktop/package.json)
```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "@dnd-kit/core": "^6.1.0",
    "@dnd-kit/sortable": "^8.0.0",
    "@dnd-kit/utilities": "^3.2.0",
    "@tanstack/react-query": "^5.17.0",
    "zustand": "^4.5.0"
  },
  "devDependencies": {
    "electron": "^28.0.0",
    "electron-vite": "^2.0.0",
    "vite": "^5.0.0",
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.3.0",
    "electron-builder": "^24.9.0"
  }
}
```

---

## 9. Security

- Backend listens on `localhost:8741` only — not exposed to network
- No authentication needed (single-user desktop app)
- File uploads validated: only `.xlsx` extension accepted
- Web scraping URLs validated against `tournamentsoftware.com` domain
- No user data leaves the machine except when scraping the web

---

## 10. Packaging

- **Python backend**: Bundled via PyInstaller into a standalone `.exe`
- **Electron app**: Packaged via electron-builder for Windows
- **Installer**: Single `.exe` installer containing both Electron app and Python backend
- The Electron main process spawns the Python `.exe` on startup and kills it on exit
