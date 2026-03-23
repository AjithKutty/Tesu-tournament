# Court Buffer Optimization Trials

## Background

Analysis of the kumpoo-2026 tournament revealed a counterintuitive finding: **removing court buffers on Saturday worsens scheduling outcomes**, even though it increases court availability. With Saturday buffers active, all 229 matches are scheduled. Without them, 4 matches fail to schedule.

Court buffers are not just break periods — they act as **implicit rest enforcement** by creating forced gaps in court availability. The greedy first-fit scheduler packs matches densely when all courts are available, causing cascading rest conflicts for players in multiple divisions. Buffers prevent this by creating periodic breathing room.

## Current Saturday Buffer Configuration

```yaml
court_buffers:
  - courts: [1, 2, 3, 4, 5, 6, 7, 8]
    duration: 30          # 30-minute break
    interval: 120         # every 2 hours from day start
    courts_at_once: 4     # block 4 courts at a time, rotating
    end_time: "17:00"     # no buffers in the evening
```

This produces:
- 11:00–11:30: Courts 1-4 blocked (5-12 available)
- 13:00–13:30: Courts 5-8 blocked (1-4, 9-12 available)
- 15:00–15:30: Courts 1-4 blocked (5-12 available)

## Why Buffers Improve Scheduling

1. **Forced player rest.** A player finishing a match at 10:30 on court 3 cannot have another match on courts 1-4 until 11:30. This 30-minute gap naturally satisfies `cross_division_rest: 30` without the scheduler needing to solve for it.

2. **Match density smoothing.** Without buffers, the scheduler packs 12 matches per slot continuously in the morning. With buffers, density drops to 8 matches during buffer windows, spreading load across the day.

3. **Court rotation distributes players across time.** The `courts_at_once: 4` rotation alternates which courts are blocked. This forces the scheduler to use different court groups at different times, preventing tight player clusters on any one group of courts.

4. **Cascading deferral prevention.** Dense packing causes more Pass 1 failures (rest conflicts), which cascade through prerequisite chains. Buffers reduce the initial failure rate, breaking the cascade.

## Optimization Opportunities

### 1. Align buffer timing with rest-heavy periods

The divisions with the most player overlap (MD C and MD B, sharing ~12 players) typically have R2 matches clustering around 12:00-13:00. Placing a buffer precisely in this window would force separation between these matches.

**Approach**: Instead of periodic intervals, use explicit buffer times targeting known scheduling pressure points.

```yaml
# Hypothetical: explicit buffer times
court_buffers:
  - courts: [5, 6, 7, 8]
    times: ["12:00", "15:00"]    # target Open division court group
    duration: 30
```

**Trade-off**: Requires knowledge of where conflicts concentrate. Less portable across tournaments.

### 2. Buffer rotation aligned with court preference groups

Current court preferences:
- Open A/B/C: prefer courts 5-8
- Veterans: prefer courts 1-4
- Junior: prefer courts 9-12

If the buffer rotation targets the court group with the most cross-division player overlap (courts 5-8 for Open divisions), it creates rest gaps specifically where they're most needed.

**Approach**: Separate buffer configs per court group with different intervals.

```yaml
court_buffers:
  - courts: [5, 6, 7, 8]       # Open division courts
    duration: 30
    interval: 90                 # more frequent — higher player overlap
    courts_at_once: 4
  - courts: [1, 2, 3, 4]       # Veterans courts
    duration: 15
    interval: 120                # less frequent — fewer conflicts
    courts_at_once: 2
```

**Trade-off**: More complex configuration. Risk of over-constraining specific court groups.

### 3. Shorter, more frequent buffers

Instead of 30-minute buffers every 2 hours, use 15-minute buffers every 90 minutes. This creates more frequent but smaller gaps — one slot duration (15 min) is often enough to enforce the 30-minute cross-division rest when combined with match duration.

```yaml
court_buffers:
  - courts: [1, 2, 3, 4, 5, 6, 7, 8]
    duration: 15                 # 1 slot only
    interval: 90                 # every 1.5 hours
    courts_at_once: 4
```

**Trade-off**: Loses less court capacity per buffer (15 min vs 30 min), but more frequent interruptions. Net court-time loss: 4 buffers x 15 min x 4 courts = 240 court-minutes vs current 3 buffers x 30 min x 4 courts = 360 court-minutes.

**Expected impact**: Most promising for improving scheduling. Frequent small gaps should prevent dense packing while preserving more total court capacity.

### 4. Extend buffers into Saturday evening

Current `end_time: "17:00"` stops buffers in the evening. Saturday evening (18:00-21:10) is where MS C QFs, late pool matches, and remaining R2 matches compete for limited slots. A buffer at 18:00 or 19:00 could help separate MS C QFs from pool matches.

```yaml
court_buffers:
  - courts: [1, 2, 3, 4, 5, 6, 7, 8]
    duration: 30
    interval: 120
    courts_at_once: 4
    end_time: "19:00"           # extend buffer window into evening
```

**Trade-off**: Saturday evening has fewer courts to spare (some end at 21:10). A buffer at 19:00 leaves only 2 hours for remaining matches.

### 5. Asymmetric buffer duration by court group

Block more courts for shorter durations, or fewer courts for longer durations, depending on scheduling pressure:

```yaml
court_buffers:
  - courts: [5, 6, 7, 8]       # Open courts: brief but frequent
    duration: 15
    interval: 90
    courts_at_once: 4
  - courts: [1, 2, 3, 4]       # Veterans courts: longer but infrequent
    duration: 30
    interval: 180
    courts_at_once: 2
```

**Trade-off**: Different court groups get different rest patterns. Veterans players (who tend to need more rest) get longer gaps on their preferred courts.

## Measurement Approach

For each trial configuration, measure:
- **Scheduled count**: must remain 229/229 (no regressions)
- **FAIL count**: potential overlap violations (lower is better)
- **SEVERE count**: potential rest violations (lower is better)
- **WARN count**: round time limits, court preferences (lower is better)
- **Deferred count**: matches deferred in Phase 1 (lower suggests better Phase 1 fit)
- **Match density variance**: standard deviation of matches per 30-min window (lower is more even)
- **Saturday evening utilization**: matches scheduled 18:00-21:10 (should stay reasonable)

## Priority

Option 3 (shorter, more frequent buffers) is the most promising starting point — it preserves the scheduling benefits while reducing court capacity loss. Option 4 (evening extension) is a low-risk addition to try alongside it.

Options 1, 2, and 5 require more tournament-specific tuning and should be explored after the simpler options are validated.
