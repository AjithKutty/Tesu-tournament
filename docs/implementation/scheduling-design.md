# Scheduling Flow Design

This document describes how `generate_schedule.py` schedules matches, including the multi-pass fallback chain and the special semi-final pair scheduling path.

## 1. Match Sorting

All matches are sorted into a single list before scheduling begins:

```python
sorted_matches = sorted(matches, key=lambda m: (
    m.priority,              # Lower number = scheduled first
    m.pool_round,            # Groups non-conflicting RR matches (0, 1, 2...)
    -len(m.known_players),   # Most-constrained first (doubles before singles)
    m.match_num,             # Determinism
    m.division_code          # Determinism
))
```

Key implications:
- **Priority is king** — a match with priority 5 always schedules before priority 50.
- **Within same priority**: pool rounds are interleaved (R1 matches first, then R2, then R3), doubles before singles.
- **Playoff matches** use `pool_round=99` to sort after all pool matches at the same priority level.

## 2. Bounds Computation (per match, before passes)

For each match, `earliest` (lower bound) and `latest` (upper bound) are computed from hard constraints.

### Earliest

Accumulated via `earliest = max(earliest, ...)`:

1. **Prerequisite rest**: Each feeder match's end + `min_prereq_rest` (cross-division rest).
2. **Round completion**: All prior-round matches must finish first. For playoff rounds, this includes ALL pool rounds (Group A Pool, Group B Pool, etc.).
3. **Pool round completion**: Previous pool round (R1 before R2) must finish.
4. **Day constraint**: If match is pinned to a day (config or same-day enforcement), snap to that day's start.
5. **Earliest start time**: From `earliest_start` config (e.g., Finals not before Sunday 14:00).
6. **Slot snapping**: Rounded up to next slot boundary.

### Latest

Accumulated via `latest = min(latest, ...)`:

1. **Day constraint**: Day's end minute.
2. **Time deadline**: `deadline - match.duration_min`.
3. **Round time limit** (soft/hard): First match of round's start + time limit - duration. Saved separately as `latest_without_rtl` for fallback relaxation. Hard limits are never relaxed.

## 3. Regular Match Scheduling — The Three Passes

After bounds are computed, the scheduler tries to place the match through up to three progressively relaxed passes. Each pass scans slots from `earliest` to `latest` and tries each eligible court.

### Pass 1: Normal Pass

**Court check**: `court_sched.can_book(court, slot, duration, overrun_buffer)`
- If a court has a buffer conflict but is otherwise free, it's added to `court_overrides` for an inline buffer override attempt.

**Player rest check**: `player_tracker.can_play_at(effective_players, slot, duration, div_code, category)`
- Full bidirectional rest enforcement via `compute_rest_between()` for ALL division pairs.
- Checks: cross-division rest, same-category rest, same-division rest (max of all applicable).
- Also enforces match density limits (max N matches in M minutes per player).

**Potential overlap check**: `player_tracker.check_potential_overlap(effective_players, slot, duration, category, div_code, scope)`
- Only runs if `player_tracker.potential_history` has entries (populated by earlier matches in configured rounds).
- Enforces full `compute_rest_between()` rest for ALL potential player pairs regardless of category.
- `scope` from config: `"all"` (default, check all categories) or `"same_category"` (category-specific).

**Inline buffer override**: If no direct court found but `court_overrides` has courts where only `_buffer_break` slots conflict:
- Re-checks player rest and potential overlap.
- Deletes buffer blocks from `court_sched.booked`, books the match.

### Pass 2: Round Time Limit Relaxation

**Triggered when**: Pass 1 failed AND a soft round time limit was the blocker (`round_time_limited=True`, `round_time_hard=False`).

**What's relaxed**: The `latest` bound is widened to `latest_without_rtl` (the bound before the round time limit was applied).

**What stays strict**:
- Court check: tries both normal and buffer override (two inner attempts).
- Player rest: still uses `can_play_at()` (full rest).
- Potential overlap: uses `check_potential_overlap_relaxed()` — same-category rest + cross-category overlap prevention only (no cross-category rest).

### Pass 3: Cross-Division Rest Relaxation

**Triggered when**: All previous passes failed. This is the **last resort**.

**What's relaxed**:
- Player rest: uses `can_play_at_relaxed()` — same-division rest only, cross-division reduced to overlap prevention (rest=0).
- Potential overlap: **skipped entirely** — no potential conflict checking at all.
- Latest bound: uses `latest_without_rtl` for soft limits, original `latest` for hard limits.

**What stays strict**:
- Court check: tries both normal and buffer override.
- Same-division rest is still enforced.
- Time overlap between confirmed players is still prevented.

### Summary Table

| Check | Pass 1 (Normal) | Pass 2 (RTL Relaxation) | Pass 3 (Cross-Div Relaxation) |
|---|---|---|---|
| **Court** | `can_book` + inline buffer | Normal + buffer override | Normal + buffer override |
| **Latest bound** | `latest` (with RTL) | `latest_without_rtl` | `latest_without_rtl` (soft) / `latest` (hard) |
| **Confirmed rest** | `can_play_at` (full) | `can_play_at` (full) | `can_play_at_relaxed` (same-div only) |
| **Potential overlap** | `check_potential_overlap` (full rest, all cats) | `check_potential_overlap_relaxed` (same-cat rest, cross-cat overlap) | **Skipped entirely** |
| **When triggered** | Always (first attempt) | If Pass 1 fails + soft RTL | If Pass 1+2 fail |

### Trace Recording

- **Scheduled**: Records match_id, priority, placed time, court, players, plus warnings list:
  - `"round time limit exceeded"` (from Pass 2)
  - `"cross-division rest relaxed"` (from Pass 3)
  - `"court buffer overridden"` (from any pass with buffer override)
- **Unscheduled**: Records per-slot rejections from Pass 1 (court busy, player conflicts) and buffer override rejections, plus the end reason.

## 4. Semi-Final Pair Scheduling

When `semi_final_same_time: true` is configured, both SF matches of a division must start at the same time on different courts. This is handled by a **separate scheduling path** that bypasses the normal 3-pass flow.

### Entry Point

When the main loop encounters a SF match:
1. Check if `match.id` is in `sf_already_placed` — if so, skip (partner already handled it).
2. Look up the SF pair in `sf_pairs[(div_code, round_name)]`.
3. If pair has exactly 2 matches, call `_schedule_sf_pair()` and `continue`.
4. If pair has != 2 matches (e.g., only 1 SF due to bye), falls through to normal scheduling.

### Bounds Computation

Similar to regular matches but with one critical addition:

1. **Prerequisites**: Both SFs' prerequisites checked, max of all ends + rest.
2. **Round completion**: Checks previous round (including pool-to-playoff link).
3. **Day constraint / same-day**: Same as regular.
4. **Time deadline**: Checked for both SFs, tightest used.
5. **Earliest start**: Checked for both SFs.
6. **Final-aware latest** (unique to SF pairs):
   ```
   sd_rest = get_same_division_rest(config, m1.division_code)
   final_duration = m1.duration_min
   sf_latest = latest - m1.duration_min - sd_rest - final_duration
   latest = min(latest, sf_latest)
   ```
   This ensures the SF ends early enough that the Final can fit: `SF_end + rest + Final_duration <= day_end`.

### SF Normal Pass

For each slot from `earliest` to `latest`:

1. **Find 2 available courts**: Get eligible courts for m1, filter to those with `can_book()` or `can_book_override_buffer()`. Need at least 2.

2. **Try each court pair** `(c1, c2)` via `combinations(available_courts, 2)`:
   - **m1 on c1**: Check `can_play_at()` + `check_potential_overlap()` for m1's effective_players.
   - **m2 on c2**: Check `can_play_at()` + `check_potential_overlap()` for m2's effective_players.
   - Both must pass.

3. **Book both**: Override buffers if needed, book courts, update confirmed + potential players, record trace.

### SF Relaxed Pass

If normal pass fails, retry with relaxed constraints:

- **Player rest**: Uses `can_play_at_relaxed()` (same-division rest only).
- **Potential overlap**: **Skipped entirely** (no `check_potential_overlap` call).
- Court search logic is identical to normal pass.
- Trace entries include `"warning": "SF pair: cross-division rest relaxed"`.

### SF Unschedulable

If both passes fail, both SFs are marked unschedulable with reason: `"SF pair: no slot with 2 available courts meeting all constraints"`.

### Key Differences: SF Pair vs Regular Scheduling

| Aspect | Regular (3 passes) | SF Pair (2 passes) |
|---|---|---|
| **Courts needed** | 1 | 2 simultaneously |
| **Matches per attempt** | 1 | 2 (both checked per slot) |
| **Final-aware latest** | No | Yes (tightens latest to leave room for Final) |
| **Number of passes** | 3 (normal, RTL relax, cross-div relax) | 2 (normal, cross-div relax) |
| **RTL relaxation pass** | Yes (Pass 2) | **No** — missing entirely |
| **Normal potential check** | Full rest, all categories | Full rest, all categories |
| **Relaxed potential check** | `check_potential_overlap_relaxed` (Pass 2) | **Skipped** (no potential check in relaxed pass) |
| **Relaxed confirmed check** | `can_play_at_relaxed` (Pass 3) | `can_play_at_relaxed` (Pass 2) |
| **Last resort behavior** | Skip potential check entirely (Pass 3) | Skip potential check (Pass 2) |
| **Trace detail** | Per-slot rejection breakdown | Simple scheduled/unscheduled |

### Notable Gap

The SF pair scheduling has **no round time limit relaxation pass**. The regular flow has 3 progressively relaxed passes, but the SF flow jumps directly from full enforcement to cross-division rest relaxation. If the round time limit is the only blocker for an SF pair, there's no intermediate fallback — it goes straight to the most aggressive relaxation or fails entirely.

## 5. PlayerTracker Methods Reference

### Confirmed Player Methods

| Method | Rest enforcement | Density | Used in |
|---|---|---|---|
| `can_play_at()` | Full (cross-div + same-cat + same-div) | Yes | Pass 1, Pass 2, SF Normal |
| `can_play_at_relaxed()` | Same-div only, cross-div=overlap | Yes | Pass 3, SF Relaxed |
| `earliest_for_match()` | Full rest (forward only) | No | Pre-loop earliest computation |

### Potential Player Methods

| Method | Same-category | Cross-category | Used in |
|---|---|---|---|
| `check_potential_overlap()` | Full rest via `compute_rest_between()` | Full rest via `compute_rest_between()` | Pass 1, SF Normal |
| `check_potential_overlap_relaxed()` | Full rest via `compute_rest_between()` | Overlap only (rest=0) | Pass 2 |
| *(skipped)* | — | — | Pass 3, SF Relaxed |

### Recording Methods

| Method | What it records | When called |
|---|---|---|
| `update()` | Confirmed player -> `history` | After booking, if match has real (non-placeholder) players |
| `update_potential()` | Effective players -> `potential_history` | After booking, if match's round is in PCA config |
