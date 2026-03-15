# App Requirements — Tournament Manager Desktop Application

## 1. Overview

A **reusable** desktop application for badminton tournament directors to configure tournaments, manage match schedules, enter results, detect conflicts, and print match cards. The app is not tied to any specific tournament — all tournament-specific data (name, dates, courts, divisions, scheduling rules) is parameterised via a tournament configuration that the user creates or loads.

**Technology**: Electron (React + TypeScript frontend) + Python FastAPI backend on localhost.

**Target user**: Any badminton tournament director running a multi-day tournament with multiple courts and divisions.

---

## 2. User Stories

### US-0: Tournament Configuration

**As a** tournament director, **I want to** configure the tournament parameters (name, dates, courts, divisions, scheduling rules) **so that** the app works for my specific tournament.

#### Sub-stories

- **US-0.1**: As a TD, I want to create a new tournament configuration by specifying: tournament name, dates (number of days, day labels), court count per day, session boundaries, and time slot duration.
- **US-0.2**: As a TD, I want to define division categories (e.g., "Open A", "Junior", "Elite") and assign visual properties (color, label) to each.
- **US-0.3**: As a TD, I want to configure scheduling rules per category: match duration, rest period, court restrictions (required courts, preferred courts), and SF/Final day requirements.
- **US-0.4**: As a TD, I want to save and load tournament configurations as JSON files so I can reuse them across years or share with other directors.
- **US-0.5**: As a TD, I want to start from a template configuration (e.g., "2-day, 12-court tournament") and customise it, rather than building from scratch.
- **US-0.6**: As a TD, I want the app to auto-detect division categories from the imported draw data when possible, and let me review/adjust the mapping.

#### Acceptance Criteria

- [ ] "New Tournament" wizard allows setting: name, dates, court count per day, court availability hours per day, sessions, slot duration
- [ ] Category editor allows adding/removing/renaming categories with configurable color, match duration, rest period, and court restrictions
- [ ] Division-to-category mapping is editable (which divisions belong to which category)
- [ ] Configuration saved as a `.json` file; can be loaded to restore all settings
- [ ] Built-in templates provided (e.g., "Standard 2-day 12-court", "Small 1-day 6-court")
- [ ] Changing configuration after import triggers a warning about re-generating the schedule
- [ ] All downstream features (grid, conflicts, printing) adapt to the configured parameters

---

### US-1: Import Tournament Data

**As a** tournament director, **I want to** import draw data from an Excel file or a tournamentsoftware.com URL **so that** I can start building the schedule.

#### Sub-stories

- **US-1.1**: As a TD, I want to select an Excel (.xlsx) file from my computer via a file picker dialog.
- **US-1.2**: As a TD, I want to paste a tournamentsoftware.com URL and have the app scrape the draw data.
- **US-1.3**: As a TD, I want to see a progress indicator during import so I know the app is working.
- **US-1.4**: As a TD, I want to see a summary of imported data (number of divisions, matches, players) after import completes.
- **US-1.5**: As a TD, I want the app to suggest category mappings for imported divisions based on naming patterns, which I can review and adjust.

#### Acceptance Criteria

- [ ] File picker opens native OS file dialog, filters to `.xlsx` files
- [ ] Web URL input validates against `tournamentsoftware.com` domain
- [ ] Import progress shown during parsing (indeterminate spinner is acceptable)
- [ ] After import, UI displays: total divisions, total matches, total players
- [ ] Import errors shown as user-friendly messages (file not found, network error, invalid format)
- [ ] Imported data persists in the app session until a new import is performed
- [ ] Both import modes produce identical internal data representation
- [ ] After import, user is shown a division-to-category mapping screen for review

---

### US-2: Visual Schedule Board

**As a** tournament director, **I want to** see all matches on a time x court grid **so that** I can understand and manage the full schedule at a glance.

#### Sub-stories

- **US-2.1**: As a TD, I want to view the schedule as a grid with time slots as rows and courts as columns, adapting to the configured court count and session hours.
- **US-2.2**: As a TD, I want to switch between session tabs as defined in the tournament configuration.
- **US-2.3**: As a TD, I want match cards to be color-coded by category using the configured category colors.
- **US-2.4**: As a TD, I want to drag a match card from one time/court slot to another to manually adjust the schedule.
- **US-2.5**: As a TD, I want to click two match cards sequentially to swap their positions.
- **US-2.6**: As a TD, I want matches with longer durations to span multiple rows proportionally (e.g., a 45-min match spans 1.5 rows on a 30-min grid).
- **US-2.7**: As a TD, I want to see a panel of unscheduled matches that I can drag onto the grid.
- **US-2.8**: As a TD, I want to auto-generate a schedule that places all matches optimally, which I can then fine-tune manually.

#### Acceptance Criteria

- [ ] Grid displays the correct number of courts and time slots per the tournament configuration
- [ ] Session tabs are dynamically generated from the configuration (not hardcoded to 5)
- [ ] Match cards show: division code, round, match number, player names (truncated if long)
- [ ] Drag-and-drop snaps to slot boundaries (configured slot duration)
- [ ] Drag feedback: ghost card follows cursor, eligible drop cells highlighted
- [ ] Swap mode: first click highlights card, second click performs swap
- [ ] Matches with non-standard durations visually span the correct number of rows
- [ ] Unscheduled panel lists matches not yet placed, filterable by category
- [ ] Auto-generate populates the grid using the scheduling algorithm
- [ ] Each match card shows a pin icon if manually placed
- [ ] After any move/swap, the conflict panel updates

---

### US-3: Print Match Cards

**As a** tournament director, **I want to** print match cards for matches starting at a specific time **so that** court officials have the information they need.

#### Sub-stories

- **US-3.1**: As a TD, I want to select a time slot and print all match cards starting at that time.
- **US-3.2**: As a TD, I want to select specific matches and print only those cards.
- **US-3.3**: As a TD, I want to preview the print layout before printing.
- **US-3.4**: As a TD, I want to export match cards as a PDF file.
- **US-3.5**: As a TD, I want to print directly to a connected printer.
- **US-3.6**: As a TD, I want the tournament name to appear on printed match cards.

#### Acceptance Criteria

- [ ] Print selection by time slot (e.g., "10:00" prints all matches at 10:00)
- [ ] Print selection by individual match(es)
- [ ] Print preview displays cards in a 2x2 grid layout (4 per A4 page)
- [ ] Each match card shows: tournament name, court number, scheduled time, day, division name, round, match number, both player/pair names with clubs and seeds, blank score area (Set 1/2/3)
- [ ] PDF export saves to user-chosen location via save dialog
- [ ] Direct print opens native OS print dialog
- [ ] Cards have cut lines for easy separation
- [ ] Cards are readable at printed size (~9cm x 6cm)

---

### US-4: Result Updates

**As a** tournament director, **I want to** record match results **so that** the bracket progresses and the schedule can be updated.

#### Sub-stories

- **US-4.1**: As a TD, I want to click a match card and enter the score (set by set).
- **US-4.2**: As a TD, I want to fetch the latest results from tournamentsoftware.com automatically.
- **US-4.3**: As a TD, I want to see which matches have results and which are pending.
- **US-4.4**: As a TD, I want "Winner of..." placeholders to resolve automatically when prerequisite results are entered.

#### Acceptance Criteria

- [ ] Click on match card opens detail modal with score entry fields (Set 1, Set 2, Set 3)
- [ ] Score entry validates format (e.g., 21-15, must be valid badminton scores)
- [ ] After entering a result, downstream "Winner of..." matches update to show the actual winner's name
- [ ] Web fetch shows progress and reports how many new results were found
- [ ] Completed matches show a green checkmark and the score on the card
- [ ] In-progress/pending matches are visually distinct from completed ones

---

### US-5: Conflict Detection

**As a** tournament director, **I want to** see scheduling conflicts highlighted in real-time **so that** I can fix them immediately.

#### Sub-stories

- **US-5.1**: As a TD, I want conflicting match cards to have a red border and warning icon.
- **US-5.2**: As a TD, I want a conflict panel listing all current conflicts with descriptions.
- **US-5.3**: As a TD, I want to click a conflict to scroll to and highlight the involved matches.
- **US-5.4**: As a TD, I want to see conflict previews while dragging (before I drop).

#### Conflict Types Detected

| Type | Severity | Description |
|---|---|---|
| Player double-booking | Error | Same player scheduled in overlapping matches |
| Insufficient rest | Warning | Less than the configured rest period between a player's matches |
| Wrong court | Error | Match placed on a court outside its category's allowed courts |
| SF/Final on wrong day | Error | Semi-final or Final not on the configured final day |
| Prerequisite violation | Error | Match scheduled before its feeder match completes |
| Court unavailable | Error | Match placed on a court at a time when the court is not available |

#### Acceptance Criteria

- [ ] After every move/swap, conflicts for affected matches update within 500ms
- [ ] Full validation available on demand (button click)
- [ ] Conflict panel shows count by severity (errors vs warnings)
- [ ] Each conflict message includes involved match IDs, player names, and specific violation
- [ ] Clicking a conflict in the panel scrolls the grid to the involved matches
- [ ] Conflicting cards have distinct visual styling (red border)
- [ ] Drag-over preview shows potential conflicts before committing the move
- [ ] All conflict rules use configured values (rest periods, court assignments) not hardcoded ones

---

### US-6: Schedule Regeneration

**As a** tournament director, **I want to** regenerate the schedule for remaining matches after results come in **so that** newly concrete matches are optimally placed.

#### Sub-stories

- **US-6.1**: As a TD, I want to pin matches I've manually placed so they survive regeneration.
- **US-6.2**: As a TD, I want to regenerate only unscheduled/unpinned matches.
- **US-6.3**: As a TD, I want to see which matches were affected by regeneration.

#### Acceptance Criteria

- [ ] Pin toggle on each match card (click pin icon)
- [ ] Pinned matches show a lock icon and are not moved during regeneration
- [ ] Regenerate button clears unpinned placements and re-runs the scheduling algorithm
- [ ] After regeneration, newly placed matches are highlighted briefly
- [ ] Regeneration respects all configured scheduling rules

---

### US-7: Rule Enforcement

**As a** tournament director, **I want to** be warned when I violate scheduling rules **so that** I don't make mistakes.

#### Sub-stories

- **US-7.1**: As a TD, I want the app to warn me if I place a match on an ineligible court.
- **US-7.2**: As a TD, I want the app to warn me if a player doesn't have enough rest.
- **US-7.3**: As a TD, I want the app to warn me but still allow the placement (warnings, not hard blocks).
- **US-7.4**: As a TD, I want the scheduling rules to reflect my tournament configuration, not hardcoded defaults.

#### Scheduling Rules (all derived from tournament configuration)

| Rule | Configured By |
|---|---|
| Court restrictions per category | Category config: `required_courts`, `preferred_courts` |
| Rest period per category | Category config: `rest_minutes` |
| Match duration per category | Category config: `duration_minutes` |
| SF/Final day restriction | Tournament config: `finals_day` |
| Court availability per day | Tournament config: `days[].courts[].available_from/to` |
| Slot duration | Tournament config: `slot_duration_minutes` |

#### Acceptance Criteria

- [ ] All rules derive from the tournament configuration, not hardcoded values
- [ ] Warnings do NOT prevent placement (user can override)
- [ ] Each warning clearly explains which rule is violated and suggests a fix
- [ ] A "Validate All" button runs full validation across the entire schedule
- [ ] Modifying the tournament configuration updates the rules immediately

---

## 3. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NF-1 | **Platform**: Windows 10+ desktop application |
| NF-2 | **Performance**: Schedule board renders smoothly with 300+ match cards; drag-and-drop feels responsive (<100ms visual feedback) |
| NF-3 | **Startup**: App launches and is ready within 5 seconds (backend startup included) |
| NF-4 | **Data persistence**: Tournament config + schedule state saved to JSON files; survives app restart |
| NF-5 | **Offline**: App works offline after initial data import (web fetch requires internet) |
| NF-6 | **Single user**: No multi-user or concurrent access needed |
| NF-7 | **Print quality**: Match cards legible when printed on standard A4 paper |
| NF-8 | **Reusability**: No tournament-specific data hardcoded; app works for any tournament configuration |

---

## 4. Glossary

| Term | Definition |
|---|---|
| Tournament configuration | JSON file defining name, dates, courts, sessions, categories, and scheduling rules |
| Division | A single competitive draw (e.g., Men's Singles A) |
| Category | A grouping of divisions with shared scheduling rules (e.g., "Elite" with 45-min matches on courts 5-8) |
| Session | A contiguous block of play (e.g., "Saturday Morning 09:00-13:00"), defined in tournament config |
| Match card | A visual card on the schedule board representing one match |
| Pin | Lock a match to its current time/court so it's not moved by regeneration |
| Conflict | A scheduling rule violation (error or warning) |
| Placeholder | A "Winner of R1-M1" entry that resolves when the feeder match result is entered |
| Rest period | Minimum time between a player's consecutive matches (configured per category) |
| Slot | A time unit on the schedule grid (duration configured in tournament config, default 30 min) |
