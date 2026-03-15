# Plan: Add Schedule Page + Time/Court Annotations to Division Draws

## Context
The tournament website (`index.html`) shows division draws but has no schedule visualization. The schedule data exists in the tournament's `output/schedules/*.json`. We need:
1. A Schedule tab in the single-page website showing a time-slot x court grid for each session
2. Time/court annotations on the existing division draw match cards

## File to modify
- **`src/generate_website.py`** — the sole file to change
- Reads: tournament config (`tournament.yaml`, `divisions.yaml`, `venue.yaml`)
- Reads: `tournaments/<name>/output/divisions/*.json` + `tournaments/<name>/output/schedules/*.json`
- Outputs: `tournaments/<name>/output/webpages/index.html`

## Implementation

### 1. Config-driven rendering

The website generator reads tournament config to determine:
- **Tournament name** from `tournament.yaml` (for page title, header, footer)
- **Tab structure** from `divisions.yaml` (category tabs, badge classes)
- **Session names** from `venue.yaml` (for schedule tab sub-tabs)

Only categories present in the actual division data produce tabs. Tab order follows `divisions.yaml`.

### 2. Schedule data loader

`load_schedule_data()` function that:
- Reads `schedules/schedule_index.json`
- Loads each session file
- Returns:
  - `all_sessions`: list of session dicts (with matches) for the schedule page
  - `schedule_lookup`: dict keyed by `(division_code, round_name, match_num)` → `{"time", "court", "date"}` for cross-referencing

### 3. Time/court on existing division draws

Thread `schedule_lookup` and `division_code` through the rendering call chain. Each match card gets a small annotation showing scheduled time and court.

### 4. Schedule grid

Session sub-tabs with `<table class="schedule-grid">`:
- **Columns**: Time | Court 1 | Court 2 | ... | Court N (courts from `venue.yaml`)
- **Rows**: One per slot interval (from `venue.yaml` slot_duration)
- **Cells**: Match info with category color-coding
- **Multi-slot matches**: Use `rowspan` for matches exceeding one slot

### 5. CSS

- Category badge classes from `divisions.yaml`
- Responsive design with horizontal scroll for schedule grid on mobile
- `.match-schedule` annotation styling for time/court on match cards

## Verification
```bash
python src/generate_website.py --tournament tournaments/<name>
```
Then:
1. Page title and header show tournament name from config
2. Only categories present in data appear as tabs
3. Tab order matches `divisions.yaml`
4. Time/court annotations appear on match cards
5. Schedule grid shows correct sessions and courts from `venue.yaml`
6. Multi-slot matches span appropriate number of rows
7. Mobile responsive (horizontal scroll on schedule grid)
