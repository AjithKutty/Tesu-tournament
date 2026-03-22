"""
Verify the generated schedule and division data for completeness and consistency.

Usage:
    python src/verify_schedule.py --tournament tournaments/kumpoo-2025

Checks:
  1. Bracket completeness: all expected rounds have the correct number of matches
  2. Round ordering: preceding rounds are scheduled before succeeding rounds
  3. Schedule coverage: all playable matches appear in the schedule
  4. Player conflicts: no player is double-booked
  5. No double-bye matches
  6. Scheduling constraints: same-day rule, pool time limits, time deadlines, round completion, SF same-time
  7. Potential player conflicts: same player could be in overlapping later-round matches
  8. Court buffer violations: matches scheduled over court buffer break slots
  9. Court preference violations: matches on less-preferred courts when better were available
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, get_tournament_name


def load_divisions(divisions_dir):
    """Load all main_draw division JSON files."""
    idx_path = os.path.join(divisions_dir, "tournament_index.json")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)

    divisions = []
    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue
        filepath = os.path.join(divisions_dir, entry["file"])
        with open(filepath, encoding="utf-8") as f:
            divisions.append(json.load(f))

    return divisions


def load_schedule(schedules_dir):
    """Load all scheduled matches from session files."""
    idx_path = os.path.join(schedules_dir, "schedule_index.json")
    if not os.path.exists(idx_path):
        return []

    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)

    all_matches = []
    for sess_info in index["sessions"]:
        sess_path = os.path.join(schedules_dir, sess_info["file"])
        if not os.path.exists(sess_path):
            continue
        with open(sess_path, encoding="utf-8") as f:
            sess_data = json.load(f)
        for m in sess_data["matches"]:
            m["_session"] = sess_data["session"]
            m["_date"] = sess_data["date"]
            all_matches.append(m)

    return all_matches


# ── Check 1: Bracket Completeness ────────────────────────────────

def expected_round_structure(draw_size):
    """Return expected rounds with match counts for an elimination bracket."""
    if draw_size <= 1:
        return []

    num_rounds = int(math.log2(draw_size))
    rounds = []
    for i in range(num_rounds):
        remaining = num_rounds - i
        if remaining == 1:
            name = "Final"
        elif remaining == 2:
            name = "Semi-Final"
        elif remaining == 3:
            name = "Quarter-Final"
        else:
            name = f"Round {i + 1}"
        rounds.append({"name": name, "expected_matches": draw_size // (2 ** (i + 1))})
    return rounds


def check_bracket_completeness(divisions):
    """Check that elimination brackets have all expected rounds with correct match counts."""
    issues = []

    for div in divisions:
        code = div["code"]
        fmt = div["format"]

        if fmt == "elimination":
            draw_size = div.get("drawSize", 0)
            if draw_size == 0:
                continue

            expected = expected_round_structure(draw_size)
            actual_rounds = {rnd["name"]: rnd for rnd in div.get("rounds", [])}

            for exp in expected:
                rnd_name = exp["name"]
                exp_matches = exp["expected_matches"]

                if rnd_name not in actual_rounds:
                    issues.append(f"{code}: Missing round '{rnd_name}' (expected {exp_matches} matches)")
                    continue

                actual = actual_rounds[rnd_name]
                actual_total = len(actual["matches"])

                # Count playable (non-bye) matches
                playable = sum(1 for m in actual["matches"]
                               if m.get("player1") != "Bye" and m.get("player2") != "Bye"
                               and not m.get("notes", "").endswith("auto-advances"))

                if actual_total == 0:
                    issues.append(
                        f"{code}: Round '{rnd_name}' has 0 matches "
                        f"(expected {exp_matches} total including byes)"
                    )
                elif actual_total != exp_matches:
                    issues.append(
                        f"{code}: Round '{rnd_name}' has {actual_total} matches "
                        f"(expected {exp_matches})"
                    )

        elif fmt == "group_playoff":
            # Check playoff bracket if present
            playoff = div.get("playoff")
            if playoff and playoff.get("drawSize", 0) > 0:
                draw_size = playoff["drawSize"]
                expected = expected_round_structure(draw_size)
                actual_rounds = {rnd["name"]: rnd for rnd in playoff.get("rounds", [])}

                for exp in expected:
                    rnd_name = exp["name"]
                    exp_matches = exp["expected_matches"]

                    if rnd_name not in actual_rounds:
                        issues.append(
                            f"{code} Playoff: Missing round '{rnd_name}' "
                            f"(expected {exp_matches} matches)"
                        )
                        continue

                    actual_total = len(actual_rounds[rnd_name]["matches"])
                    if actual_total != exp_matches:
                        issues.append(
                            f"{code} Playoff: Round '{rnd_name}' has {actual_total} matches "
                            f"(expected {exp_matches})"
                        )

    return issues


# ── Check 2: Schedule Round Ordering ─────────────────────────────

ROUND_ORDER = {
    "Pool": 0,
    "Round 1": 1, "Round 2": 2,
    "Quarter-Final": 3, "Semi-Final": 4, "Final": 5,
}

GROUP_POOL_ORDER = 0
PLAYOFF_OFFSET = 10


def _round_sort_key(round_name):
    """Get a numeric sort key for a round name.

    Returns (phase, order) where:
      phase 0 = pool/group pool (independent, not compared across groups)
      phase 1 = elimination rounds
      phase 2 = playoff rounds
    """
    # Handle "Group X Pool" rounds — all share same key (independent)
    if "Pool" in round_name and "Playoff" not in round_name:
        return (0, 0, round_name)  # same phase, distinguish by name

    # Handle "Playoff Round 1", "Playoff Semi-Final", etc.
    if round_name.startswith("Playoff "):
        base = round_name.replace("Playoff ", "")
        return (2, ROUND_ORDER.get(base, 0), round_name)

    return (1, ROUND_ORDER.get(round_name, 0), round_name)


def _time_to_minutes(date_str, time_str):
    """Convert date + time to comparable minutes value."""
    # Simple: assume days are ordered as they appear
    h, m = map(int, time_str.split(":"))
    day_offset = 0
    if date_str == "Sunday":
        day_offset = 24 * 60
    elif date_str == "Saturday":
        day_offset = 0
    return day_offset + h * 60 + m


def check_round_ordering(schedule_matches):
    """Check that each scheduled match starts after its feeder matches.

    This checks per-match prerequisite ordering, not whole-round ordering.
    In a bracket, QF-M1 only needs R1-M1 and R1-M2 to finish — not all
    of R1.  So we parse 'Winner XX-MN' references to find each match's
    specific feeders and verify they're scheduled earlier.
    """
    issues = []

    # Build lookup: (division, round, match_num) -> (time_minutes, date, time_str)
    match_times = {}
    for m in schedule_matches:
        key = (m["division"], m["round"], m["match_num"])
        t = _time_to_minutes(m["_date"], m["time"])
        match_times[key] = (t, m["_date"], m["time"])

    # Also check against the division data for prerequisite info
    # For now, check that pool rounds finish before playoff rounds
    # within the same division
    by_division = {}
    for m in schedule_matches:
        div = m["division"]
        if div not in by_division:
            by_division[div] = []
        by_division[div].append(m)

    for div_code, matches in by_division.items():
        # Separate pool and playoff matches
        pool_matches = [m for m in matches if "Pool" in m["round"] and "Playoff" not in m["round"]]
        playoff_matches = [m for m in matches if m["round"].startswith("Playoff ")]

        if pool_matches and playoff_matches:
            pool_latest = max(_time_to_minutes(m["_date"], m["time"]) + m.get("duration_min", 30)
                              for m in pool_matches)
            playoff_earliest_match = min(playoff_matches,
                                          key=lambda m: _time_to_minutes(m["_date"], m["time"]))
            playoff_earliest = _time_to_minutes(playoff_earliest_match["_date"],
                                                 playoff_earliest_match["time"])

            if pool_latest > playoff_earliest:
                pool_latest_match = max(pool_matches,
                                         key=lambda m: _time_to_minutes(m["_date"], m["time"]))
                issues.append(
                    f"{div_code}: Pool matches run until "
                    f"{pool_latest_match['_date']} {pool_latest_match['time']} "
                    f"but Playoff starts at "
                    f"{playoff_earliest_match['_date']} {playoff_earliest_match['time']}"
                )

    return issues


# ── Check 3: Schedule Coverage ───────────────────────────────────

def check_schedule_coverage(divisions, schedule_matches):
    """Check that all playable matches from divisions appear in the schedule.

    Only reports the first round with missing matches per division —
    later rounds that depend on failed earlier rounds are suppressed
    since they are cascading failures.
    """
    issues = []

    # Build set of scheduled match keys: (division, round, match_num)
    scheduled_keys = set()
    for m in schedule_matches:
        scheduled_keys.add((m["division"], m["round"], m["match_num"]))

    for div in divisions:
        code = div["code"]
        fmt = div["format"]

        if fmt == "elimination":
            # Check rounds in order; stop at the first round with failures
            for rnd in div.get("rounds", []):
                round_issues = []
                for m in rnd["matches"]:
                    if _is_playable(m):
                        key = (code, rnd["name"], m["match"])
                        if key not in scheduled_keys:
                            round_issues.append(
                                f"{code}: {rnd['name']} M{m['match']} not in schedule "
                                f"({m['player1']} vs {m['player2']})"
                            )
                if round_issues:
                    issues.extend(round_issues)
                    remaining = [r["name"] for r in div["rounds"]
                                 if r["name"] != rnd["name"]
                                 and _round_sort_key(r["name"]) > _round_sort_key(rnd["name"])]
                    if remaining:
                        issues.append(
                            f"{code}: skipping later rounds ({', '.join(remaining)}) "
                            f"— depend on unscheduled {rnd['name']} matches"
                        )
                    break

        elif fmt == "round_robin":
            for m in div.get("matches", []):
                key = (code, "Pool", m["match"])
                if key not in scheduled_keys:
                    issues.append(
                        f"{code}: Pool M{m['match']} not in schedule "
                        f"({m['player1']} vs {m['player2']})"
                    )

        elif fmt == "group_playoff":
            group_has_failures = False
            for group in div.get("groups", []):
                group_name = group["name"]
                round_name = f"{group_name} Pool"
                for m in group.get("matches", []):
                    key = (code, round_name, m["match"])
                    if key not in scheduled_keys:
                        issues.append(
                            f"{code}: {round_name} M{m['match']} not in schedule"
                        )
                        group_has_failures = True

            playoff = div.get("playoff")
            if playoff:
                if group_has_failures:
                    issues.append(
                        f"{code}: skipping playoff rounds — depend on unscheduled group matches"
                    )
                else:
                    # Check playoff rounds in order; stop at first failure
                    for rnd in playoff.get("rounds", []):
                        round_issues = []
                        for m in rnd["matches"]:
                            if _is_playable(m):
                                key = (code, f"Playoff {rnd['name']}", m["match"])
                                if key not in scheduled_keys:
                                    round_issues.append(
                                        f"{code}: Playoff {rnd['name']} M{m['match']} not in schedule"
                                    )
                        if round_issues:
                            issues.extend(round_issues)
                            remaining = [r["name"] for r in playoff["rounds"]
                                         if r["name"] != rnd["name"]
                                         and _round_sort_key(r["name"]) > _round_sort_key(rnd["name"])]
                            if remaining:
                                issues.append(
                                    f"{code}: skipping later playoff rounds ({', '.join(remaining)}) "
                                    f"— depend on unscheduled Playoff {rnd['name']} matches"
                                )
                            break

    return issues


def _is_playable(match):
    """Check if a match needs court time (not a bye)."""
    p1 = match.get("player1", "")
    p2 = match.get("player2", "")
    if p1 == "Bye" or p2 == "Bye":
        return False
    if p1.startswith("Bye") or p2.startswith("Bye"):
        return False
    notes = match.get("notes", "")
    if "auto-advances" in notes or "Empty slot" in notes:
        return False
    return True


# ── Check 5: Double-Bye Matches ──────────────────────────────────

def check_double_byes(divisions):
    """Check that no match has both players as Bye."""
    issues = []

    for div in divisions:
        code = div["code"]
        fmt = div["format"]

        if fmt == "elimination":
            for rnd in div.get("rounds", []):
                for m in rnd["matches"]:
                    if m.get("player1") == "Bye" and m.get("player2") == "Bye":
                        issues.append(
                            f"{code}: {rnd['name']} M{m['match']} has both players as Bye"
                        )

        elif fmt == "group_playoff":
            playoff = div.get("playoff")
            if playoff:
                for rnd in playoff.get("rounds", []):
                    for m in rnd["matches"]:
                        if m.get("player1") == "Bye" and m.get("player2") == "Bye":
                            issues.append(
                                f"{code} Playoff: {rnd['name']} M{m['match']} has both players as Bye"
                            )

    return issues


# ── Check 4: Player Conflicts ───────────────────────────────────

def check_player_conflicts(schedule_matches):
    """Check that no player is scheduled in two matches at the same time."""
    issues = []

    # Build player schedule: player -> list of (start_minutes, duration, match_id)
    player_schedule = {}
    for m in schedule_matches:
        t = _time_to_minutes(m["_date"], m["time"])
        dur = m.get("duration_min", 30)
        match_desc = f"{m['division']} {m['round']} M{m['match_num']}"

        for p_field in ("player1", "player2"):
            p = m.get(p_field, "")
            if not p or p == "Bye" or p.startswith("Winner ") or p.startswith("Slot "):
                continue
            # Split doubles
            for name in p.split(" / "):
                name = name.strip()
                if name:
                    if name not in player_schedule:
                        player_schedule[name] = []
                    player_schedule[name].append((t, dur, match_desc, m["_date"], m["time"]))

    for player, matches in player_schedule.items():
        matches.sort()
        for i in range(len(matches) - 1):
            t1, dur1, desc1, date1, time1 = matches[i]
            t2, dur2, desc2, date2, time2 = matches[i + 1]
            if t2 < t1 + dur1:
                issues.append(
                    f"Double-booking: {player} in {desc1} ({date1} {time1}) "
                    f"and {desc2} ({date2} {time2})"
                )

    return issues


# ── Check 7: Potential Player Conflicts ─────────────────────────

def check_potential_player_conflicts(schedule_matches, schedules_dir):
    """Check for potential double-bookings in later-round matches.

    Uses the scheduling trace to find all possible players for each match
    (including placeholder matches where the winner is unknown), and flags
    cases where the same player could be in two overlapping matches.

    Only reports conflicts involving at least one placeholder match —
    confirmed double-bookings are caught by check_player_conflicts.
    """
    issues = []
    from collections import defaultdict

    # Load scheduling trace for the possible-players info
    trace_path = os.path.join(schedules_dir, "scheduling_trace.json")
    if not os.path.exists(trace_path):
        return issues

    with open(trace_path, encoding="utf-8") as f:
        trace = json.load(f)

    # Build match_id -> (time_minutes, duration, possible_players, desc)
    match_info = {}
    for m in schedule_matches:
        match_id = f"{m['division']}:{m['round']}:M{m['match_num']}"
        t = _time_to_minutes(m["_date"], m["time"])
        dur = m.get("duration_min", 30)
        match_info[match_id] = {
            "time": t, "dur": dur,
            "date": m["_date"], "time_str": m["time"],
            "desc": f"{m['division']} {m['round']} M{m['match_num']}",
        }

    # Merge possible players from trace
    for entry in trace:
        mid = entry.get("match_id")
        if mid in match_info and entry.get("status") == "SCHEDULED":
            match_info[mid]["players"] = set(entry.get("players", []))
            # Track if this match has placeholders
            p1 = entry.get("player1", "")
            p2 = entry.get("player2", "")
            match_info[mid]["has_placeholder"] = (
                p1.startswith("Winner ") or p1.startswith("Slot ") or
                p2.startswith("Winner ") or p2.startswith("Slot ")
            )

    # Build player -> list of (time, end, match_id, has_placeholder) for potential matches
    player_potential = defaultdict(list)
    for mid, info in match_info.items():
        for player in info.get("players", []):
            player_potential[player].append((
                info["time"], info["time"] + info["dur"],
                mid, info.get("has_placeholder", False),
                info["date"], info["time_str"],
            ))

    # Check for overlapping matches for the same player
    seen = set()
    for player, matches in player_potential.items():
        matches.sort()
        for i in range(len(matches) - 1):
            t1, end1, id1, placeholder1, date1, time1 = matches[i]
            t2, end2, id2, placeholder2, date2, time2 = matches[i + 1]
            if t2 < end1:
                # Only report if at least one match has a placeholder
                if not (placeholder1 or placeholder2):
                    continue

                # Skip same-division same-round conflicts — structurally
                # impossible (a player advances to only one match per round
                # within a division, e.g., can't be in both SF-M1 and SF-M2)
                div1 = id1.split(":")[0]
                div2 = id2.split(":")[0]
                rnd1 = id1.split(":")[1]
                rnd2 = id2.split(":")[1]
                if div1 == div2 and rnd1 == rnd2:
                    continue

                key = (min(id1, id2), max(id1, id2), player)
                if key not in seen:
                    seen.add(key)
                    issues.append(
                        f"Potential conflict: {player} could be in "
                        f"{id1} ({date1} {time1}) and "
                        f"{id2} ({date2} {time2})"
                    )

    return issues


# ── Check 8: Court Buffer Violations ────────────────────────────

def check_court_buffer_violations(schedules_dir):
    """Check if any matches were scheduled by overriding court buffer breaks.

    Reads the scheduling trace to find matches with buffer override warnings.
    """
    issues = []
    trace_path = os.path.join(schedules_dir, "scheduling_trace.json")
    if not os.path.exists(trace_path):
        return issues

    with open(trace_path, encoding="utf-8") as f:
        trace = json.load(f)

    for entry in trace:
        if entry.get("warning") == "court buffer overridden":
            slots = entry.get("buffer_slots_overridden", [])
            issues.append(
                f"Buffer override: {entry['match_id']} at {entry['placed']} court {entry['court']} "
                f"— overrode buffer at {', '.join(slots)}"
            )

    return issues


# ── Check 6: Scheduling Constraints ─────────────────────────────

def check_scheduling_constraints(schedule_matches, config):
    """Check scheduling constraints:
    - Same-day rule: all matches in same round+division on same day
    - Pool time limit: pool matches finish within configured window (WARN)
    - Time deadlines: rounds finish by configured deadline
    - Round completion: later rounds start after previous rounds finish
    - Semi-final same-time: both SF matches at same time

    Returns (errors, warnings) — pool time limit violations are warnings.
    """
    issues = []
    warnings = []
    from collections import defaultdict
    from config import (get_round_time_limit, get_time_deadlines,
                        get_round_completion, build_venue_model)

    # Build (division, round_group) -> {date: [match_descs]}
    round_days = defaultdict(lambda: defaultdict(list))
    # Build (division, round_group) -> [(start_minutes, end_minutes)]
    round_times = defaultdict(list)

    for m in schedule_matches:
        div = m["division"]
        rnd = m["round"]
        if " Pool" in rnd and rnd != "Pool":
            round_group = "Group Pool"
        else:
            round_group = rnd
        date = m["_date"]
        round_days[(div, round_group)][date].append(
            f"M{m['match_num']} at {m['time']}"
        )
        t = _time_to_minutes(m["_date"], m["time"])
        dur = m.get("duration_min", 30)
        round_times[(div, round_group)].append((t, t + dur, m["time"], m["match_num"]))

    # 1. Same-day rule
    for (div, round_group), day_matches in sorted(round_days.items()):
        if len(day_matches) > 1:
            day_list = ", ".join(
                f"{d} ({len(ids)} matches)" for d, ids in day_matches.items()
            )
            issues.append(
                f"Same-day: {div} {round_group} split across days: {day_list}"
            )

    # 2. Round time limits (applies to any round, not just pools)
    round_groups = defaultdict(list)
    for m in schedule_matches:
        div = m["division"]
        rnd = m["round"]
        round_groups[(div, rnd)].append({
            "start": _time_to_minutes(m["_date"], m["time"]),
            "end": _time_to_minutes(m["_date"], m["time"]) + m.get("duration_min", 30),
            "category": m.get("category", ""),
        })

    for (div, rnd), entries in sorted(round_groups.items()):
        if not entries:
            continue
        category = entries[0]["category"]
        limit = get_round_time_limit(config, rnd, category, div)
        if limit is None:
            continue
        first_start = min(e["start"] for e in entries)
        last_end = max(e["end"] for e in entries)
        span = last_end - first_start
        if span > limit:
            warnings.append(
                f"Round time limit: {div} {rnd} spans {span}min "
                f"(limit {limit}min)"
            )

    # 3. Time deadlines
    deadlines = get_time_deadlines(config)
    if deadlines:
        venue_model = build_venue_model(config)
        for dl in deadlines:
            dl_str = dl.get("deadline", "")
            parts = dl_str.split(" ", 1)
            if len(parts) != 2:
                continue
            day_name, time_str = parts
            dl_h, dl_m = map(int, time_str.split(":"))
            dl_minutes = _time_to_minutes(day_name, time_str)

            rounds = dl.get("rounds", [])
            divisions = dl.get("divisions")
            for m in schedule_matches:
                if m["round"] not in rounds:
                    continue
                if divisions and m["division"] not in divisions:
                    continue
                t = _time_to_minutes(m["_date"], m["time"])
                end = t + m.get("duration_min", 30)
                if end > dl_minutes and m["_date"] == day_name:
                    issues.append(
                        f"Time deadline: {m['division']} {m['round']} M{m['match_num']} "
                        f"ends at {m['_date']} {_add_minutes(m['time'], m.get('duration_min', 30))} "
                        f"(deadline: {dl_str})"
                    )

    # 4. Round completion
    rc_enabled, rc_exceptions = get_round_completion(config)
    if rc_enabled:
        round_order = ["Round 1", "Round 2", "Quarter-Final", "Semi-Final", "Final"]
        div_round_end = defaultdict(int)  # (div, round) -> latest end time
        div_round_start = defaultdict(lambda: float('inf'))  # (div, round) -> earliest start

        for m in schedule_matches:
            div = m["division"]
            rnd = m["round"]
            if div in rc_exceptions:
                continue
            t = _time_to_minutes(m["_date"], m["time"])
            end = t + m.get("duration_min", 30)
            div_round_end[(div, rnd)] = max(div_round_end[(div, rnd)], end)
            div_round_start[(div, rnd)] = min(div_round_start[(div, rnd)], t)

        for div_rnd, start in sorted(div_round_start.items()):
            div, rnd = div_rnd
            if rnd not in round_order:
                continue
            idx = round_order.index(rnd)
            if idx == 0:
                continue
            for prev_idx in range(idx - 1, -1, -1):
                prev_rnd = round_order[prev_idx]
                if (div, prev_rnd) in div_round_end:
                    prev_end = div_round_end[(div, prev_rnd)]
                    if start < prev_end:
                        issues.append(
                            f"Round completion: {div} {rnd} starts before "
                            f"{prev_rnd} finishes"
                        )
                    break

    # 5. Semi-final same-time
    sf_same_time = config["scheduling"].get("semi_final_same_time", False)
    if sf_same_time:
        sf_times = defaultdict(list)
        for m in schedule_matches:
            rnd = m["round"]
            bare = rnd.replace("Playoff ", "") if rnd.startswith("Playoff ") else rnd
            if bare == "Semi-Final":
                sf_times[(m["division"], rnd)].append(m["time"])

        for (div, rnd), times in sorted(sf_times.items()):
            if len(times) >= 2 and len(set(times)) > 1:
                issues.append(
                    f"SF same-time: {div} {rnd} at different times: {times}"
                )

    return issues, warnings


def _add_minutes(time_str, minutes):
    """Add minutes to HH:MM, return HH:MM."""
    hh, mm = map(int, time_str.split(":"))
    mm += minutes
    while mm >= 60:
        hh += 1
        mm -= 60
    return f"{hh:02d}:{mm:02d}"


# ── Check 9: Court Preference Violations ────────────────────────

def _to_venue_minute(venue_model, day_str, time_str):
    """Convert (day, HH:MM) to venue model minute offset."""
    for day in venue_model["days"]:
        if day["name"] == day_str:
            start_h, start_m = map(int, day["start_time"].split(":"))
            h, m = map(int, time_str.split(":"))
            offset = (h - start_h) * 60 + (m - start_m)
            return day["start_minute"] + offset
    return 0


def check_court_preferences(schedule_matches, config):
    """Check if matches are on optimal courts given their preferences.

    For each match, determines the preferred court order and checks if
    a more-preferred court was available (not occupied) at that time slot.
    """
    from collections import defaultdict
    from config import get_court_preference, build_venue_model

    issues = []
    venue_model = build_venue_model(config)
    slot_duration = venue_model["slot_duration"]
    round_prefs = config["court_preferences"].get("round_court_preferences", {})

    # Build court occupancy: (date, time, court) -> match_desc
    occupancy = {}
    for m in schedule_matches:
        dur = m.get("duration_min", 30)
        slots = (dur + slot_duration - 1) // slot_duration
        t = m["time"]
        for s in range(slots):
            occupancy[(m["_date"], t, m["court"])] = (
                f"{m['division']} {m['round']} M{m['match_num']}"
            )
            # Advance time
            hh, mm = map(int, t.split(":"))
            mm += slot_duration
            while mm >= 60:
                hh += 1
                mm -= 60
            t = f"{hh:02d}:{mm:02d}"

    # Check each match
    for m in schedule_matches:
        category = m.get("category", "")
        court = m["court"]
        day = m["_date"]
        time = m["time"]
        rnd = m.get("round", "")
        dur = m.get("duration_min", 30)

        # Get the court preference for this match
        pref = get_court_preference(config, category, day_name=day, round_name=rnd)

        # Apply round preferences (same logic as get_eligible_courts)
        bare_round = rnd.replace("Playoff ", "") if rnd.startswith("Playoff ") else rnd
        if bare_round in round_prefs and not pref.get("required_courts"):
            pref = dict(pref)
            rp = round_prefs[bare_round]
            for key in ("preferred_courts", "fallback_courts", "last_resort_courts"):
                if key in rp:
                    pref[key] = rp[key]

        # If required_courts, just check the match is on one of them
        if pref.get("required_courts"):
            if court not in pref["required_courts"]:
                issues.append(
                    f"Required court: {m['division']} {rnd} M{m['match_num']} "
                    f"on court {court} (required: {pref['required_courts']})"
                )
            continue

        # Build preference order
        preferred = pref.get("preferred_courts") or []
        fallback = pref.get("fallback_courts") or []

        # If match is on a preferred court, it's fine
        if court in preferred:
            continue

        # Match is on a fallback/other court — check if a preferred court was free
        slots_needed = (dur + slot_duration - 1) // slot_duration
        for pc in preferred:
            # Check if this preferred court was free for all slots of the match
            all_free = True
            t_check = time
            for s in range(slots_needed):
                if (day, t_check, pc) in occupancy:
                    occ = occupancy[(day, t_check, pc)]
                    # It's occupied by another match (not this one)
                    if occ != f"{m['division']} {rnd} M{m['match_num']}":
                        all_free = False
                        break
                # Check court exists at this time (available in venue)
                vm_min = _to_venue_minute(venue_model, day, t_check)
                court_exists = any(
                    crt == pc and s <= vm_min < e
                    for crt, s, e in venue_model["court_windows"]
                )
                if not court_exists:
                    all_free = False
                    break
                # Advance
                hh, mm = map(int, t_check.split(":"))
                mm += slot_duration
                while mm >= 60:
                    hh += 1
                    mm -= 60
                t_check = f"{hh:02d}:{mm:02d}"

            if all_free:
                issues.append(
                    f"Court preference: {m['division']} {rnd} M{m['match_num']} "
                    f"at {day} {time} on court {court} — "
                    f"preferred court {pc} was available"
                )
                break  # report only the best available preferred court
        else:
            # No preferred court was free from matches — check if one was
            # only blocked by court buffers (could have been overridden)
            for pc in preferred:
                only_buffer_blocking = True
                t_check = time
                for s_idx in range(slots_needed):
                    vm_min = _to_venue_minute(venue_model, day, t_check)
                    court_exists = any(
                        crt == pc and s <= vm_min < e
                        for crt, s, e in venue_model["court_windows"]
                    )
                    if not court_exists:
                        only_buffer_blocking = False
                        break
                    if (day, t_check, pc) in occupancy:
                        only_buffer_blocking = False
                        break
                    # Advance
                    hh, mm = map(int, t_check.split(":"))
                    mm += slot_duration
                    while mm >= 60:
                        hh += 1
                        mm -= 60
                    t_check = f"{hh:02d}:{mm:02d}"

                if only_buffer_blocking:
                    issues.append(
                        f"Court preference: {m['division']} {rnd} M{m['match_num']} "
                        f"at {day} {time} on court {court} — "
                        f"preferred court {pc} available with buffer override"
                    )
                    break

    return issues


# ── Main ─────────────────────────────────────────────────────────

def verify(config):
    """Run all verification checks. Returns the number of issues found."""
    divisions_dir = config["paths"]["divisions_dir"]
    schedules_dir = config["paths"]["schedules_dir"]

    divisions = load_divisions(divisions_dir)
    schedule = load_schedule(schedules_dir)

    all_issues = []
    total_checks = 0

    # Check 1: Bracket completeness
    print("Check 1: Bracket completeness...")
    issues = check_bracket_completeness(divisions)
    total_checks += 1
    if issues:
        all_issues.extend(issues)
        for issue in issues:
            print(f"  FAIL: {issue}")
    else:
        print("  PASS")

    # Check 2: Round ordering
    if schedule:
        print("Check 2: Round ordering...")
        issues = check_round_ordering(schedule)
        total_checks += 1
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  FAIL: {issue}")
        else:
            print("  PASS")

        # Check 3: Schedule coverage
        print("Check 3: Schedule coverage...")
        issues = check_schedule_coverage(divisions, schedule)
        total_checks += 1
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  FAIL: {issue}")
        else:
            print("  PASS")

        # Check 4: Player conflicts
        print("Check 4: Player conflicts...")
        issues = check_player_conflicts(schedule)
        total_checks += 1
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  FAIL: {issue}")
        else:
            print("  PASS")
    else:
        print("Check 2-4: Skipped (no schedule data)")

    # Check 5: Double-bye matches
    print("Check 5: No double-bye matches...")
    issues = check_double_byes(divisions)
    total_checks += 1
    if issues:
        all_issues.extend(issues)
        for issue in issues:
            print(f"  FAIL: {issue}")
    else:
        print("  PASS")

    # Check 6: Scheduling constraints (same-day, pool time limit, deadlines, round completion, SF same-time)
    if schedule:
        print("Check 6: Scheduling constraints...")
        errors, warnings = check_scheduling_constraints(schedule, config)
        total_checks += 1
        if errors or warnings:
            all_issues.extend(errors)
            all_issues.extend(warnings)
            for e in errors:
                print(f"  FAIL: {e}")
            for w in warnings:
                print(f"  WARN: {w}")
        if not errors and not warnings:
            print("  PASS")

    # Check 7: Potential player conflicts (later-round placeholder matches)
    if schedule:
        print("Check 7: Potential player conflicts...")
        issues = check_potential_player_conflicts(schedule, schedules_dir)
        total_checks += 1
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  WARN: {issue}")
        else:
            print("  PASS")

    # Check 8: Court buffer violations
    print("Check 8: Court buffer violations...")
    issues = check_court_buffer_violations(schedules_dir)
    total_checks += 1
    if issues:
        all_issues.extend(issues)
        for issue in issues:
            print(f"  WARN: {issue}")
    else:
        print("  PASS")

    # Check 9: Court preference violations
    if schedule:
        print("Check 9: Court preference violations...")
        issues = check_court_preferences(schedule, config)
        total_checks += 1
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  WARN: {issue}")
        else:
            print("  PASS")

    print()
    if all_issues:
        print(f"RESULT: {len(all_issues)} issues found across {total_checks} checks")
    else:
        print(f"RESULT: All {total_checks} checks passed")

    return len(all_issues)


def main():
    parser = argparse.ArgumentParser(description="Verify tournament schedule")
    parser.add_argument(
        "--tournament", required=True,
        help="Path to tournament directory",
    )
    args = parser.parse_args()

    config = load_config(args.tournament)
    tournament_name = get_tournament_name(config)

    print(f"Verifying: {tournament_name}")
    print(f"Divisions: {config['paths']['divisions_dir']}")
    print(f"Schedules: {config['paths']['schedules_dir']}")
    print()

    issue_count = verify(config)
    sys.exit(1 if issue_count > 0 else 0)


if __name__ == "__main__":
    main()
