# Implementation Plan — Tournament Manager Desktop Application

## Overview

6 phases, each building on the previous. Three agent roles work on each phase:

| Agent | Role | Responsibilities |
|---|---|---|
| **Architect** | Design + review | Reviews phase design, validates API contracts, ensures config-driven architecture, reviews code for design compliance and consistency |
| **Coder** | Implementation | Writes code per the architecture document, follows conventions, implements features |
| **QA Engineer** | Testing + validation | Writes and runs tests, validates features against acceptance criteria in app-requirements.md, reports bugs back to Coder |

### Agent Workflow (per phase)

1. **Architect** reviews/refines the design for the phase — confirms API contracts, data models, and config integration
2. **Coder** implements all tasks in the phase
3. **QA Engineer** tests the implementation against acceptance criteria and reports issues
4. **Coder** fixes reported issues
5. Phase is complete when QA Engineer confirms all acceptance criteria pass

### Key Design Principle

**All tournament-specific data is parameterised.** Nothing is hardcoded for a specific tournament. The app works for any number of days, courts, divisions, categories, match durations, and rest periods — all driven by a `TournamentConfig` JSON file that the user creates or loads.

---

## Phase 1: FastAPI Backend Foundation

### Goal
Stand up the Python backend with configuration management, all API endpoints, and the scheduling engine wrapper.

### Tasks

1. **Add Python dependencies** — Update `requirements.txt` with fastapi, uvicorn, python-multipart, pydantic
2. **Add `CourtSchedule.unbook()` method** to `src/generate_schedule.py` (inverse of `book()`)
3. **Create `src/api/models/config_schemas.py`** — Pydantic models for TournamentConfig, DayConfig, SessionConfig, CategoryConfig, CourtAvailability
4. **Create `src/api/services/config_service.py`** — Config load/save from JSON file, built-in templates, division-to-category auto-suggestion based on naming patterns (e.g., "MS V" → elite, "BS U17" → junior)
5. **Create `src/api/templates/`** — Built-in config templates (`standard_2day_12court.json`, `small_1day_6court.json`)
6. **Create `src/api/routes/config_routes.py`** — `GET /api/config`, `POST /api/config`, `GET /api/config/templates`, `POST /api/config/save`, `POST /api/config/load`, `POST /api/config/division-map`
7. **Create `src/api/server.py`** — FastAPI app, CORS middleware (allow localhost origins), health endpoint, include all routers
8. **Create `src/api/models/schemas.py`** — Pydantic models: MatchCard, Conflict, ScheduleState, SessionInfo, request/response models
9. **Create `src/api/state/tournament_state.py`** — TournamentState class holding config + in-memory state, methods for load/generate/move/swap/unschedule/pin/validate. Adapts TournamentConfig into parameters for the existing scheduling engine.
10. **Create `src/api/services/import_service.py`** — Wraps `parse_tournament.main()` and `parse_web.main()`, auto-suggests category mapping, loads matches into state
11. **Create `src/api/services/schedule_service.py`** — Config-aware wrapper around `schedule_matches()`, converts config into time model / court eligibility / durations / rest periods. Handles pinned match pre-placement. Rebuilds CourtSchedule/PlayerTracker after mutations.
12. **Create `src/api/services/conflict_service.py`** — Scoped validation (per-move) + full validation. All rules read from config (rest periods, court restrictions, SF/Final day, court availability).
13. **Create `src/api/routes/import_routes.py`** — `POST /api/import/excel`, `POST /api/import/web`
14. **Create `src/api/routes/schedule_routes.py`** — `GET /api/schedule`, `POST /api/schedule/generate`, `/move`, `/swap`, `/unschedule`, `/pin`, `/validate`, `/validate-move`

### Config-Driven Adaptation

The key challenge is mapping `TournamentConfig` to the existing scheduling engine's format:

| Config field | Maps to |
|---|---|
| `days[].courts[].available_from/to` | `CourtSchedule._court_exists()` checks |
| `categories[].required_courts` | `get_eligible_courts()` court ordering |
| `categories[].preferred_courts` | `get_eligible_courts()` court ordering |
| `categories[].duration_minutes` | `Match.duration_min` |
| `categories[].rest_minutes` | `Match.rest_min` |
| `categories[].sf_final_day_index` | `Match.is_sf_or_final` + earliest time constraint |
| `sessions[]` | `SESSIONS` list for output splitting |
| `slot_duration_minutes` | `SLOT_DURATION` |

### Key Risk
`CourtSchedule` only adds bookings. The `unbook()` method must correctly reverse `book()`. `PlayerTracker` has no removal — rebuild from scratch after each mutation.

### Testing (QA Engineer)
- Start server: `python -m uvicorn src.api.server:app --port 8741`
- Create config: `curl -X POST -H "Content-Type: application/json" -d @config.json http://localhost:8741/api/config`
- Import Excel: `curl -X POST -F "file=@Draws...xlsx" http://localhost:8741/api/import/excel`
- Set division mapping: `curl -X POST -H "Content-Type: application/json" -d '{"division_category_map": {...}}' http://localhost:8741/api/config/division-map`
- Generate schedule: `curl -X POST http://localhost:8741/api/schedule/generate`
- Move match: `curl -X POST -H "Content-Type: application/json" -d '{"match_id":"MS A:Round 1:M1","court":5,"time_minute":60}' http://localhost:8741/api/schedule/move`
- Validate: `curl http://localhost:8741/api/schedule/validate`
- Verify: conflicts use configured rest periods, court restrictions, not hardcoded values
- Verify: different configs produce different scheduling behaviour

### Deliverables
- Config CRUD endpoints working with load/save
- All import, schedule, and validation endpoints functional
- TournamentState correctly adapts config to scheduling engine
- Scoped validation returns config-driven conflicts within 50ms
- No hardcoded tournament-specific values in the API layer

---

## Phase 2: Electron Shell + Basic UI

### Goal
Set up the Electron + React project and render a config-driven schedule grid from API data.

### Tasks

1. **Initialize `desktop/` project** — `npm init`, install Electron, React, TypeScript, Vite, electron-vite
2. **Create `electron/main.ts`** — Electron main process: create BrowserWindow, load renderer
3. **Create `electron/preload.ts`** — contextBridge exposing IPC methods for file dialog and print
4. **Create `electron/pythonManager.ts`** — Spawn `uvicorn` as child process on app startup, kill on quit, health check loop
5. **Create `src/main.tsx` + `src/App.tsx`** — React entry point, QueryClientProvider
6. **Create `src/api/client.ts`** — Fetch wrapper for `http://localhost:8741`
7. **Create `src/api/endpoints.ts`** — Typed API functions matching backend endpoints (including config endpoints)
8. **Create `src/types/api.ts`** — TypeScript interfaces matching Pydantic models
9. **Create `src/types/config.ts`** — TypeScript interfaces matching TournamentConfig schema
10. **Create `src/styles/global.css`** — Base CSS variables (category colors applied dynamically from config)
11. **Create `src/components/Layout/WelcomeScreen.tsx`** — Shown when no tournament loaded; buttons for New, Load, Templates
12. **Create `src/components/Config/ConfigWizard.tsx`** — Multi-step wizard: name+dates → courts → sessions → categories → review
13. **Create `src/components/Config/DivisionMappingEditor.tsx`** — Table: division | suggested category | dropdown override
14. **Create `src/components/Layout/AppShell.tsx`** — Main layout: toolbar top, content center, panels
15. **Create `src/components/Layout/Toolbar.tsx`** — Import, Generate, Validate, Print, Export, Config buttons
16. **Create `src/components/Layout/SessionTabs.tsx`** — Tabs dynamically generated from `config.sessions`
17. **Create `src/components/Modals/ImportDialog.tsx`** — File picker (IPC to main process for `dialog.showOpenDialog`) + URL text input
18. **Create `src/components/ScheduleBoard/ScheduleBoard.tsx`** — CSS Grid container, dimensions from config
19. **Create `src/components/ScheduleBoard/CourtHeader.tsx`** — Court number labels from `config.days[].courts`
20. **Create `src/components/ScheduleBoard/TimeColumn.tsx`** — Time slot labels from session start/end and slot duration
21. **Create `src/components/ScheduleBoard/GridCell.tsx`** — Single cell (no drop target yet)
22. **Create `src/components/ScheduleBoard/MatchCard.tsx`** — Card with category color from config, division, round, players
23. **Create `src/styles/schedule-board.css`** — Grid layout, court header, time column
24. **Create `src/styles/match-card.css`** — Card styles, dynamic category colors via CSS custom properties
25. **Create `src/hooks/useSchedule.ts`** — React Query hooks for `GET /api/schedule`
26. **Create `src/hooks/useConfig.ts`** — React Query hooks for config endpoints
27. **Create `src/store/scheduleStore.ts`** — Zustand store for UI state

### Testing (QA Engineer)
- `cd desktop && npm run dev` → Electron window opens
- Welcome screen shows New / Load / Template options
- Config wizard creates a valid config with custom days/courts/sessions/categories
- After import, DivisionMappingEditor shows all divisions with category suggestions
- After import + generate, grid shows match cards in correct positions
- Session tabs match the configured sessions (not hardcoded to 5)
- Court count matches the configured courts for the selected day
- Match cards show category colors from configuration
- Grid adapts when config is changed

### Deliverables
- Electron app launches, spawns Python backend, renders config-driven schedule grid
- Welcome screen + Config wizard working
- Import + division mapping working
- Static grid view adapts dynamically to any configuration

---

## Phase 3: Drag-and-Drop + Conflict Panel

### Goal
Make the schedule board interactive with drag-and-drop and config-driven real-time conflict detection.

### Tasks

1. **Install @dnd-kit** — `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`
2. **Create `src/hooks/useDragAndDrop.ts`** — DnD context setup, drag handlers
3. **Make MatchCard draggable** — Wrap with `useDraggable`, add DragOverlay for ghost preview
4. **Make GridCell a drop target** — Wrap with `useDroppable`, visual feedback on hover (green = eligible, red = conflict). Eligibility based on category court rules from config.
5. **Connect DragEnd to API** — Call `POST /api/schedule/move` on drop, optimistic UI
6. **Implement swap mode** — Click first card (highlight), click second card (swap via API), Escape to cancel
7. **Create `src/components/Panels/UnscheduledPanel.tsx`** — Bottom drawer listing unplaced matches, also draggable onto grid, filterable by category
8. **Create `src/components/Panels/ConflictPanel.tsx`** — Right sidebar showing conflict list, grouped by severity, clickable to scroll to match. Conflict messages reference configured rules.
9. **Create `src/hooks/useConflicts.ts`** — Extract conflicts from schedule query, provide helpers
10. **Add conflict styling to MatchCard** — Red border, warning icon when card has conflicts
11. **Add drag-over validation preview** — Debounced `POST /api/schedule/validate-move` during drag

### Testing (QA Engineer)
- Drag a card from one court to another → card moves, API called
- Drag a match to a court outside its category's `required_courts` → conflict appears
- Move a player's match too close to their other match → rest violation shown (using configured rest period, not hardcoded 30 min)
- Swap two cards → both update positions
- Drag from unscheduled panel onto grid → match placed
- Click conflict → grid scrolls to involved match
- Test with a different config (e.g., 6 courts, different rest periods) → conflicts reflect the config

### Deliverables
- Full drag-and-drop interaction working
- Swap mode working
- Config-driven real-time conflict detection and display
- Unscheduled panel functional

---

## Phase 4: Results + Regeneration

### Goal
Allow result entry, resolve bracket placeholders, and regenerate schedules while preserving manual adjustments.

### Tasks

1. **Create `src/api/services/result_service.py`** — Result storage, "Winner of..." placeholder resolution logic
2. **Create `src/api/routes/results_routes.py`** — `POST /api/results/update`, `POST /api/results/fetch-web`
3. **Create `src/components/Modals/MatchDetailModal.tsx`** — Full match details, score entry (3 sets), pin/unpin toggle
4. **Score validation** — Badminton score rules (first to 21, must win by 2, max 30, third set first to 21)
5. **Placeholder resolution** — When result entered, find all downstream matches referencing "Winner {round}-M{num}" and replace with actual winner name
6. **Web result fetching** — Call `parse_web.py` with `--full-results`, merge into TournamentState
7. **Pin/unpin UI** — Lock icon on cards, click to toggle, visual distinction for pinned cards
8. **Regeneration** — "Generate" with `keep_pinned=true`: clear unpinned placements, pre-book pinned matches, run scheduling algorithm for rest using configured rules
9. **Result display on cards** — Green checkmark + score text on completed match cards
10. **Visual distinction** — Placeholder matches (dashed border, italic), completed (green accent), pending (default)

### Testing (QA Engineer)
- Click card → modal opens with details and score entry
- Enter "21-15 21-18" → match shows as completed, downstream bracket updates
- Fetch results from web → multiple matches update
- Pin 5 matches, click Generate → those 5 stay, rest rescheduled
- Placeholder "Winner R1-M1" resolves to actual name after R1 M1 result entered
- Regeneration uses configured durations/rest/courts

### Deliverables
- Result entry working (manual + web fetch)
- Bracket placeholder resolution working
- Pin/unpin + regeneration working

---

## Phase 5: Printing + Export

### Goal
Print match cards and export schedule/website.

### Tasks

1. **Create `src/api/services/print_service.py`** — Generate print-optimized HTML with match card layout; includes tournament name from config
2. **Create `src/api/routes/print_routes.py`** — `POST /api/print/match-cards`
3. **Create `src/api/routes/export_routes.py`** — `POST /api/export/website`, `POST /api/export/schedule`
4. **Create `src/styles/print.css`** — A4 layout, 4 cards per page (2x2), cut lines, `@media print` rules
5. **Create `src/components/Modals/PrintPreview.tsx`** — Time slot selector, card preview, Print and Export PDF buttons
6. **Electron print IPC** — Main process receives HTML via IPC, creates hidden BrowserWindow, calls `print()` or `printToPDF()`
7. **PDF save dialog** — Use `dialog.showSaveDialog()` for PDF export location
8. **Website export** — Call existing `generate_website.py` via backend
9. **Schedule JSON export** — Write current schedule state to `output/schedules/` files
10. **Config export** — Save current tournament config alongside schedule export

### Match Card Layout (per card, ~9cm x 6cm)
```
+-------------------------------+
| TOURNAMENT NAME               |
| Court 5      10:30 Saturday   |
| MS A  -  Round 1  -  M3      |
|                               |
| Player 1 Name (Club) [seed]  |
|           vs                  |
| Player 2 Name (Club)         |
|                               |
| Set 1: ___-___                |
| Set 2: ___-___                |
| Set 3: ___-___                |
+-------------------------------+
```

### Testing (QA Engineer)
- Select "10:00" → preview shows all matches at 10:00
- Tournament name appears on every printed card
- Print → OS print dialog opens
- Export PDF → file saved to chosen location
- Cards are 4 per page, readable, with cut lines
- Export website → `output/webpages/index.html` generated and openable

### Deliverables
- Print preview, direct print, and PDF export all working
- Tournament name on all printed materials
- Website and schedule JSON export working

---

## Phase 6: Polish + Packaging

### Goal
Final polish, keyboard shortcuts, undo/redo, and Windows packaging.

### Tasks

1. **Keyboard shortcuts** — Arrow keys navigate grid, Enter opens match detail, Delete unschedules, Escape closes modals, Ctrl+Z undo, Ctrl+Y redo
2. **Undo/redo** — Stack of last 50 schedule mutations; each move/swap/unschedule pushes state snapshot
3. **Grid zoom** — Ctrl+mousewheel or +/- buttons to zoom in/out on the grid
4. **Loading states** — Spinners during import, generate, web fetch
5. **Empty states** — Welcome screen (no tournament), "Import data to begin" (config but no data), "Generate schedule" (data but no schedule)
6. **Error handling** — Toast notifications for API errors, friendly messages
7. **PyInstaller backend** — Bundle `src/api/server.py` + dependencies into standalone `.exe`
8. **Electron-builder** — Package Electron app + bundled Python backend into Windows installer
9. **App icon** — Badminton-themed icon for taskbar and installer
10. **End-to-end testing** — Full workflow with multiple different tournament configurations

### Testing (QA Engineer)
- Full workflow: config → import → map divisions → generate → drag → results → regenerate → print → export
- Same workflow with a completely different config (1-day, 6-court tournament) → app adapts correctly
- Undo/redo reverses moves correctly
- Keyboard shortcuts work as expected
- Packaged .exe installs and runs on clean Windows machine
- No hardcoded tournament names, court counts, or division codes anywhere in the UI

### Deliverables
- Polished, distributable Windows desktop application
- Works for any tournament configuration

---

## Phase Dependencies

```
Phase 1 (Backend + Config)
    ├──→ Phase 2 (Electron + Grid + Config UI) ──→ Phase 3 (DnD + Conflicts)
    │                                                      │
    ├──→ Phase 4 (Results) ←───────────────────────────────┘
    │
    └──→ Phase 5 (Print + Export)
                    │
                    └──→ Phase 6 (Polish + Packaging)
```

Phase 1 must be complete before any frontend work begins. Phases 2→3 are sequential (need grid before DnD). Phase 4 needs both Phase 1 endpoints and Phase 3 modals. Phase 5 needs Phase 1 endpoints and Phase 2 Electron shell. Phase 6 is last.

---

## Critical File References

| File | Relevant Lines | Usage |
|---|---|---|
| `src/generate_schedule.py` | 128-154 | Match class — wrapped by TournamentState |
| `src/generate_schedule.py` | 630-668 | CourtSchedule — add unbook(), used for move/unschedule |
| `src/generate_schedule.py` | 670-684 | PlayerTracker — rebuilt after mutations |
| `src/generate_schedule.py` | 689-714 | get_eligible_courts() — replaced by config-driven version |
| `src/generate_schedule.py` | 740-826 | schedule_matches() — called by generate endpoint with config-adapted params |
| `src/generate_schedule.py` | 831-891 | validate_schedule() — wrapped by conflict_service with config-driven rules |
| `src/generate_website.py` | 386-505 | CSS variables — base inspiration for frontend styles |
| `src/parse_tournament.py` | main() | Called by import_service for Excel mode |
| `src/parse_web.py` | main() | Called by import_service for web mode |
| `docs/requirements/scheduling-rules.md` | all | Example rules (now configurable, not hardcoded) |
