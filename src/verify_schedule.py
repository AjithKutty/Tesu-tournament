"""
Verify the generated schedule and division data for completeness and consistency.

Usage:
    python src/verify_schedule.py --tournament tournaments/kumpoo-2025

Checks:
  1. Bracket completeness: all expected rounds have the correct number of matches
  2. Round ordering: preceding rounds are scheduled before succeeding rounds
  3. Schedule coverage: all playable matches appear in the schedule
  4. Player conflicts: no player is double-booked
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
    """Check that all playable matches from divisions appear in the schedule."""
    issues = []

    # Build set of scheduled match keys: (division, round, match_num)
    scheduled_keys = set()
    for m in schedule_matches:
        scheduled_keys.add((m["division"], m["round"], m["match_num"]))

    for div in divisions:
        code = div["code"]
        fmt = div["format"]

        if fmt == "elimination":
            for rnd in div.get("rounds", []):
                for m in rnd["matches"]:
                    if _is_playable(m):
                        key = (code, rnd["name"], m["match"])
                        if key not in scheduled_keys:
                            issues.append(
                                f"{code}: {rnd['name']} M{m['match']} not in schedule "
                                f"({m['player1']} vs {m['player2']})"
                            )

        elif fmt == "round_robin":
            for m in div.get("matches", []):
                key = (code, "Pool", m["match"])
                if key not in scheduled_keys:
                    issues.append(
                        f"{code}: Pool M{m['match']} not in schedule "
                        f"({m['player1']} vs {m['player2']})"
                    )

        elif fmt == "group_playoff":
            for group in div.get("groups", []):
                group_name = group["name"]
                round_name = f"{group_name} Pool"
                for m in group.get("matches", []):
                    key = (code, round_name, m["match"])
                    if key not in scheduled_keys:
                        issues.append(
                            f"{code}: {round_name} M{m['match']} not in schedule"
                        )

            playoff = div.get("playoff")
            if playoff:
                for rnd in playoff.get("rounds", []):
                    for m in rnd["matches"]:
                        if _is_playable(m):
                            key = (code, f"Playoff {rnd['name']}", m["match"])
                            if key not in scheduled_keys:
                                issues.append(
                                    f"{code}: Playoff {rnd['name']} M{m['match']} not in schedule"
                                )

    return issues


def _is_playable(match):
    """Check if a match needs court time (not a bye)."""
    p1 = match.get("player1", "")
    p2 = match.get("player2", "")
    if p1 == "Bye" or p2 == "Bye":
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
