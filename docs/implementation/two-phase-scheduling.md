# Two-Phase Scheduling Design

## Problem

In single-phase scheduling, each match exhausts all fallback passes (normal, RTL relaxation, cross-division rest relaxation) before the next match is processed. This creates a problem: a high-priority match that fails the normal pass immediately relaxes its constraints and grabs a slot — potentially taking a slot that a lower-priority match could have used without any relaxation at all.

Example scenario:
- MD B QF (priority 39) fails Pass 1 due to a potential conflict with another high-priority match
- It immediately falls to Pass 3 (cross-division rest relaxation) and takes a Saturday evening slot
- MS 35 Pool M5 (priority 50) arrives later and can't find a slot — the one it would have used is now taken by MD B QF

The result: more matches end up with relaxed constraints than necessary, leading to more verifier warnings (SEVERE/FAIL).

## Solution: Two-Phase Scheduling

Split the scheduling loop into two phases:

**Phase 1** (normal pass only): All matches are processed in priority order, but only the normal pass (Pass 1) is attempted. Matches that fail Pass 1 are **deferred** — added to a `deferred_ids` set instead of immediately escalating to relaxed passes. This allows lower-priority matches to take their natural slots first.

**Phase 2** (full fallback chain): Only deferred matches are processed, in the same priority order. They retry Pass 1 (the court/player landscape has changed since Phase 1), then if needed Pass 2 (RTL relaxation) and Pass 3 (cross-division rest relaxation). Matches that still fail after all passes are marked unschedulable.

### Why This Helps

- Lower-priority matches are no longer displaced by higher-priority matches using relaxed constraints
- Deferred matches benefit from a different court/player landscape in Phase 2 — slots freed by lower-priority matches may resolve their conflicts
- Fewer matches need constraint relaxation overall, reducing verifier warnings

## Implementation

### Core Structure

The loop body is extracted into a nested function `_process_match(match)` inside `schedule_matches()`. This function captures all shared state (scheduled, court_sched, player_tracker, etc.) via closure. A `scheduling_phase` variable (1 or 2) controls behavior.

```python
deferred_ids = set()
scheduling_phase = 1

def _process_match(match):
    # ... all match processing logic ...
    # References scheduling_phase and deferred_ids from closure

# Phase 1: Pass 1 only, defer failures
for match in sorted_matches:
    _process_match(match)

# Phase 2: full 3-pass chain for deferred matches
if deferred_ids:
    scheduling_phase = 2
    for match in [m for m in sorted_matches if m.id in deferred_ids]:
        _process_match(match)
```

### Phase-Gated Behavior

The `_process_match` function checks `scheduling_phase` at four decision points:

#### 1. Skip already-placed matches

Phase 2 matches may have been placed as SF pair partners in Phase 1, or their prerequisites may have been resolved. Skip them:

```python
if match.id in scheduled or match.id in sf_already_placed:
    return
```

#### 2. Prerequisite deferral chains

If a match's prerequisite is deferred (not failed, just waiting for Phase 2), the match itself must also be deferred. This prevents scheduling a QF before its R2 feeder has been resolved.

```python
if scheduling_phase == 1 and prereq_id in deferred_ids:
    deferred_ids.add(match.id)
    return
```

The same logic applies to:
- **Round completion**: if any previous-round match is deferred, defer this match
- **Pool round completion**: if the previous pool round has deferred matches, defer this match

In Phase 2, deferral chains don't apply — deferred prerequisites are processed first (lower priority = earlier in sort order) and are either scheduled or marked unschedulable by the time dependent matches are reached.

#### 3. SF pair scheduling

Semi-final pairs use `allow_relaxation` parameter:

```python
sf_placed = _schedule_sf_pair(
    ...,
    allow_relaxation=(scheduling_phase == 2),
)
if not sf_placed and scheduling_phase == 1:
    for m in pair:
        deferred_ids.add(m.id)
```

- **Phase 1**: `allow_relaxation=False` — only the normal pass is tried. If it fails, both SFs are deferred (not marked unschedulable).
- **Phase 2**: `allow_relaxation=True` — normal pass + relaxed pass. If both fail, SFs are marked unschedulable.

#### 4. Post-Pass-1 deferral

After Pass 1 (normal + inline buffer override) fails:

```python
if not placed and scheduling_phase == 1:
    deferred_ids.add(match.id)
    sched_trace.append({
        "match_id": match.id, "status": "DEFERRED",
        "priority": match.priority,
        ...
    })
    return
```

In Phase 1, the function returns here — Pass 2 and Pass 3 are never reached. In Phase 2, execution continues to the fallback passes.

### Scheduling Trace

Deferred matches get a `"DEFERRED"` status entry in the trace during Phase 1. When they're processed in Phase 2, a second entry is added with either `"SCHEDULED"` (with any applicable warnings like "cross-division rest relaxed") or `"UNSCHEDULED"`.

## Flow Diagram

```
Phase 1: for each match (priority order)
  |
  +-- prerequisite deferred? --> defer this match
  +-- round completion deferred? --> defer this match
  +-- SF pair?
  |     +-- normal pass succeeds --> SCHEDULED
  |     +-- normal pass fails --> defer both SFs
  +-- Pass 1 (normal + buffer override)
        +-- succeeds --> SCHEDULED
        +-- fails --> DEFERRED (skip Pass 2/3)

Phase 2: for each deferred match (same priority order)
  |
  +-- already placed? --> skip
  +-- prerequisite failed? --> UNSCHEDULABLE
  +-- SF pair?
  |     +-- normal pass succeeds --> SCHEDULED
  |     +-- relaxed pass succeeds --> SCHEDULED (with warning)
  |     +-- both fail --> UNSCHEDULABLE
  +-- Pass 1 (retry with updated landscape)
  |     +-- succeeds --> SCHEDULED
  +-- Pass 2 (RTL relaxation)
  |     +-- succeeds --> SCHEDULED (with warning)
  +-- Pass 3 (cross-div rest relaxation)
        +-- succeeds --> SCHEDULED (with warning)
        +-- fails --> UNSCHEDULABLE
```

## Results

Tested with kumpoo-2026 tournament (229 matches):

| Metric | Single-phase | Two-phase | Change |
|---|---|---|---|
| **FAIL** | 11 | 8 | -27% |
| **SEVERE** | 5 | 4 | -20% |
| **WARN** | 25 | 20 | -20% |
| **Total** | 41 | 32 | -22% |

6 matches were deferred in Phase 1:
- 2 Quarter-Final matches (failed due to potential conflicts)
- 1 Pool match (failed due to cross-division rest)
- 3 Final matches (failed due to cross-division rest)

All 6 were successfully placed in Phase 2:
- 2 using RTL relaxation (round time limit exceeded)
- 4 using cross-division rest relaxation

The Finals that previously overlapped at the same time slot are now spread across the afternoon (14:00, 14:30, 15:45) because lower-priority matches took their natural slots first in Phase 1, leaving different (better) slots available for the deferred Finals in Phase 2.
