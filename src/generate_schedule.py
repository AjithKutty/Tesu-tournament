"""
Generate match schedules from division JSON files.

Usage:
    python generate_schedule.py
    python generate_schedule.py --tournament path/to/tournament

Reads:  divisions/tournament_index.json + divisions/*.json
Writes: schedules/Saturday_Morning.json, Saturday_Afternoon.json,
        Saturday_Evening.json, Sunday_Morning.json, Sunday_Afternoon.json,
        schedules/schedule_index.json
"""

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import date

from config import (load_config, get_tournament_name, get_priorities,
                    get_round_priority_map, get_elite_divisions,
                    get_day_constraints, get_match_duration,
                    get_overrun_buffer, compute_rest_between,
                    get_cross_division_rest, get_same_division_rest,
                    get_court_preference,
                    get_slot_duration, build_venue_model,
                    minute_to_display as config_minute_to_display)


# ── Helper functions ─────────────────────────────────────────────

def extract_player_names(player_str):
    """Extract individual player names from a match player string.
    Handles doubles ('Name1 / Name2') and singles ('Name').
    Returns empty list for Bye or Winner-of placeholders."""
    if not player_str or player_str == "Bye":
        return []
    if player_str.startswith("Winner ") or player_str.startswith("Slot "):
        return []
    return [n.strip() for n in player_str.split(" / ") if n.strip()]


def is_bye_match(match_data):
    """Check if a match is a bye (auto-advance, no court time needed)."""
    p1 = match_data.get("player1", "")
    p2 = match_data.get("player2", "")
    if p1 == "Bye" or p2 == "Bye":
        return True
    if p1.startswith("Bye") or p2.startswith("Bye"):
        return True
    return False


def make_match_id(div_code, round_name, match_num):
    return f"{div_code}:{round_name}:M{match_num}"


def parse_winner_ref(player_str):
    """Parse 'Winner R1-M1' to ('Round 1', 1). Returns None if not a reference."""
    m = re.match(r"Winner\s+(\w+)-M(\d+)", player_str)
    if not m:
        return None
    abbrev = m.group(1)
    num = int(m.group(2))
    abbrev_to_round = {
        "R1": "Round 1",
        "R2": "Round 2",
        "QF": "Quarter-Final",
        "SF": "Semi-Final",
        "F": "Final",
    }
    round_name = abbrev_to_round.get(abbrev, abbrev)
    return round_name, num


# ── Match loading ────────────────────────────────────────────────

class Match:
    def __init__(self, match_id, div_code, div_name, category, round_name,
                 match_num, player1, player2, known_players, duration_min,
                 priority, day_constraint, prerequisites, is_elite,
                 overrun_buffer=0):
        self.id = match_id
        self.division_code = div_code
        self.division_name = div_name
        self.category = category
        self.round_name = round_name
        self.match_num = match_num
        self.player1 = player1
        self.player2 = player2
        self.known_players = known_players
        self.duration_min = duration_min
        self.priority = priority
        self.day_constraint = day_constraint  # required day name (e.g. "Sunday") or None
        self.prerequisites = prerequisites
        self.is_elite = is_elite
        self.overrun_buffer = overrun_buffer  # extra minutes to keep court free before this match
        self.pool_round = 0  # scheduling round within a RR pool (0-based)
        # True if actual players are known (R1/pool), False if placeholder ("Winner of...")
        self.has_real_players = bool(known_players) and not (
            player1.startswith("Winner ") or player1.startswith("Slot ")
        )


def _build_day_constraint_set(config):
    """Build a set of round names that have day constraints, mapped to their required day.
    Returns dict: round_name -> day_name."""
    constraints = get_day_constraints(config)
    result = {}
    for constraint in constraints:
        day_name = constraint.get("day")
        for round_name in constraint.get("rounds", []):
            result[round_name] = day_name
    return result


def load_all_matches(config):
    """Load all schedulable matches from division JSON files."""
    divisions_dir = config["paths"]["divisions_dir"]

    with open(os.path.join(divisions_dir, "tournament_index.json"), encoding="utf-8") as f:
        index = json.load(f)

    elite_divisions = get_elite_divisions(config)
    priorities = get_priorities(config)
    round_priority_map = get_round_priority_map(config)
    day_constraint_map = _build_day_constraint_set(config)

    # Build resolved priority map: round_name -> numeric priority
    resolved_round_priority = {}
    for round_name, priority_key in round_priority_map.items():
        resolved_round_priority[round_name] = priorities.get(priority_key, priorities.get("round_1", 20))

    all_matches = []
    # Store match data by ID for back-tracing player names
    match_by_id = {}

    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue

        filepath = os.path.join(divisions_dir, entry["file"])
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        div_code = data["code"]
        div_name = data["name"]
        category = data["category"]
        fmt = data["format"]
        is_elite = div_code in elite_divisions
        duration = get_match_duration(config, category)
        overrun_buf = get_overrun_buffer(config, category)

        loader_args = (data, div_code, div_name, category, is_elite, duration,
                       resolved_round_priority, priorities, day_constraint_map, overrun_buf)

        if fmt == "elimination":
            matches = _load_elimination_matches(*loader_args)
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

        elif fmt == "round_robin":
            matches = _load_roundrobin_matches(*loader_args)
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

        elif fmt == "group_playoff":
            matches = _load_group_playoff_matches(*loader_args)
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

    # Resolve known_players for later rounds by tracing back through brackets
    _resolve_known_players(all_matches, match_by_id)

    return all_matches, match_by_id


def _load_elimination_matches(data, div_code, div_name, category, is_elite, duration,
                              resolved_round_priority, priorities, day_constraint_map,
                              overrun_buf=0):
    matches = []
    rounds = data.get("rounds", [])

    # Build a map of round_name -> round data for lookup
    round_map = {rnd["name"]: rnd for rnd in rounds}

    for rnd in rounds:
        round_name = rnd["name"]
        priority = resolved_round_priority.get(round_name, priorities.get("round_1", 20))
        day_constraint = day_constraint_map.get(round_name)

        for m in rnd["matches"]:
            match_id = make_match_id(div_code, round_name, m["match"])

            if is_bye_match(m):
                continue  # Skip byes

            p1 = m.get("player1", "")
            p2 = m.get("player2", "")
            known = extract_player_names(p1) + extract_player_names(p2)

            # Prerequisites: only the specific feeder matches (parsed from "Winner R1-M1")
            prereqs = []
            for player_str in (p1, p2):
                ref = parse_winner_ref(player_str)
                if ref:
                    ref_round, ref_match_num = ref
                    prereq_id = make_match_id(div_code, ref_round, ref_match_num)
                    # Only add if the feeder match is not a bye
                    if ref_round in round_map:
                        feeder = next(
                            (fm for fm in round_map[ref_round]["matches"]
                             if fm["match"] == ref_match_num), None
                        )
                        if feeder and not is_bye_match(feeder):
                            prereqs.append(prereq_id)

            match = Match(
                match_id=match_id,
                div_code=div_code, div_name=div_name, category=category,
                round_name=round_name, match_num=m["match"],
                player1=p1, player2=p2, known_players=known,
                duration_min=duration,
                priority=priority, day_constraint=day_constraint,
                prerequisites=prereqs, is_elite=is_elite,
                overrun_buffer=overrun_buf,
            )
            matches.append(match)

    return matches


def _compute_pool_rounds(matches):
    """Assign scheduling rounds to round-robin matches within a pool.
    Matches in the same round don't share players and can be played simultaneously.
    Uses greedy graph coloring on the conflict graph."""
    player_sets = []
    for m in matches:
        players = set(extract_player_names(m.player1) + extract_player_names(m.player2))
        player_sets.append(players)

    rounds = {}
    for i in range(len(matches)):
        round_num = 0
        while True:
            conflict = False
            for j, r in rounds.items():
                if r == round_num and player_sets[i] & player_sets[j]:
                    conflict = True
                    break
            if not conflict:
                rounds[i] = round_num
                break
            round_num += 1

    for i, m in enumerate(matches):
        m.pool_round = rounds.get(i, 0)


def _load_roundrobin_matches(data, div_code, div_name, category, is_elite, duration,
                             resolved_round_priority, priorities, day_constraint_map,
                             overrun_buf=0):
    matches = []
    for m in data.get("matches", []):
        match_id = make_match_id(div_code, "Pool", m["match"])
        p1 = m.get("player1", "")
        p2 = m.get("player2", "")
        known = extract_player_names(p1) + extract_player_names(p2)

        pool_priority = priorities.get("elite_pool", 5) if is_elite else priorities.get("pool", 10)
        match = Match(
            match_id=match_id,
            div_code=div_code, div_name=div_name, category=category,
            round_name="Pool", match_num=m["match"],
            player1=p1, player2=p2, known_players=known,
            duration_min=duration,
            priority=pool_priority, day_constraint=None,
            prerequisites=[], is_elite=is_elite,
            overrun_buffer=overrun_buf,
        )
        matches.append(match)

    # Compute scheduling rounds for parallelism
    _compute_pool_rounds(matches)
    return matches


def _load_group_playoff_matches(data, div_code, div_name, category, is_elite, duration,
                                resolved_round_priority, priorities, day_constraint_map,
                                overrun_buf=0):
    matches = []
    group_match_ids = []

    # Group stage matches
    for group in data.get("groups", []):
        group_name = group["name"]
        for m in group.get("matches", []):
            match_id = make_match_id(div_code, f"{group_name} Pool", m["match"])
            p1 = m.get("player1", "")
            p2 = m.get("player2", "")
            known = extract_player_names(p1) + extract_player_names(p2)

            match = Match(
                match_id=match_id,
                div_code=div_code, div_name=div_name, category=category,
                round_name=f"{group_name} Pool", match_num=m["match"],
                player1=p1, player2=p2, known_players=known,
                duration_min=duration,
                priority=priorities.get("pool", 10), day_constraint=None,
                prerequisites=[], is_elite=is_elite,
                overrun_buffer=overrun_buf,
            )
            matches.append(match)
            group_match_ids.append(match_id)

    # Playoff bracket
    playoff = data.get("playoff")
    if playoff and playoff.get("rounds"):
        playoff_round_map = {rnd["name"]: rnd for rnd in playoff["rounds"]}
        is_first_playoff_round = True

        for rnd in playoff["rounds"]:
            round_name = rnd["name"]
            priority = resolved_round_priority.get(round_name, priorities.get("group_playoff", 30))
            priority = max(priority, priorities.get("group_playoff", 30))
            day_constraint = day_constraint_map.get(round_name)

            for m in rnd["matches"]:
                match_id = make_match_id(div_code, f"Playoff {round_name}", m["match"])

                p1 = m.get("player1", "")
                p2 = m.get("player2", "")
                known = extract_player_names(p1) + extract_player_names(p2)

                prereqs = []
                if is_first_playoff_round:
                    # First playoff round depends on all group matches
                    prereqs = list(group_match_ids)
                else:
                    # Later playoff rounds: parse "Winner QF-M1" to find specific feeders
                    for player_str in (p1, p2):
                        ref = parse_winner_ref(player_str)
                        if ref:
                            ref_round, ref_match_num = ref
                            prereq_id = make_match_id(
                                div_code, f"Playoff {ref_round}", ref_match_num
                            )
                            prereqs.append(prereq_id)

                match = Match(
                    match_id=match_id,
                    div_code=div_code, div_name=div_name, category=category,
                    round_name=f"Playoff {round_name}", match_num=m["match"],
                    player1=p1, player2=p2, known_players=known,
                    duration_min=duration,
                    priority=priority, day_constraint=day_constraint,
                    prerequisites=prereqs, is_elite=is_elite,
                    overrun_buffer=overrun_buf,
                )
                matches.append(match)

            is_first_playoff_round = False

    return matches


def _resolve_known_players(all_matches, match_by_id):
    """For later-round matches with 'Winner ...' players, trace back to find
    all possible players (worst-case conflict set)."""
    # Build a map from match_id to its known_players
    # For matches that already have known players (R1/pool), skip
    # For later rounds, trace back recursively

    def get_all_possible_players(match_id, visited=None):
        if visited is None:
            visited = set()
        if match_id in visited:
            return []
        visited.add(match_id)

        m = match_by_id.get(match_id)
        if m is None:
            return []

        if m.known_players:
            return list(m.known_players)

        # Trace through prerequisites
        players = []
        for prereq_id in m.prerequisites:
            players.extend(get_all_possible_players(prereq_id, visited))
        return players

    for match in all_matches:
        if not match.known_players and match.prerequisites:
            match.known_players = list(set(get_all_possible_players(match.id)))


# ── Court schedule ───────────────────────────────────────────────

class CourtSchedule:
    def __init__(self, venue_model):
        self.venue_model = venue_model
        self.booked = {}  # (court, minute) -> match_id

    def is_available(self, court, minute):
        """Check if a court is available at a given time."""
        if not self._court_exists(court, minute):
            return False
        return (court, minute) not in self.booked

    def _court_exists(self, court, minute):
        """Check if a court is operational at this time."""
        for crt, start, end in self.venue_model["court_windows"]:
            if crt == court and start <= minute < end:
                return True
        return False

    def book(self, court, minute, match_id, duration_min, overrun_buffer=0):
        """Book a court for a match.

        Blocks slots for two purposes:
        1. match_duration + overrun_buffer AFTER the start — the match
           itself plus a gap so the next match isn't affected by overruns.
        2. overrun_buffer BEFORE the start — reserves a gap so no
           later-scheduled match can end too close before this one.

        This bidirectional blocking ensures the buffer works regardless
        of scheduling order (higher-priority matches are scheduled first
        but lower-priority matches fill in around them later).
        """
        slot_duration = self.venue_model["slot_duration"]

        # Block forward: match duration + buffer after
        total_forward = duration_min + overrun_buffer
        slots_forward = (total_forward + slot_duration - 1) // slot_duration
        for i in range(slots_forward):
            self.booked[(court, minute + i * slot_duration)] = match_id

        # Block backward: buffer before this match's start
        if overrun_buffer > 0:
            slots_before = (overrun_buffer + slot_duration - 1) // slot_duration
            for i in range(1, slots_before + 1):
                t = minute - i * slot_duration
                if t >= 0 and (court, t) not in self.booked:
                    self.booked[(court, t)] = f"_buffer_{match_id}"

    def can_book(self, court, minute, duration_min, overrun_buffer=0):
        """Check if a court can be booked for duration + overrun buffer."""
        slot_duration = self.venue_model["slot_duration"]
        total_forward = duration_min + overrun_buffer
        slots_forward = (total_forward + slot_duration - 1) // slot_duration
        for i in range(slots_forward):
            t = minute + i * slot_duration
            if not self.is_available(court, t):
                return False

        # Check backward buffer slots
        if overrun_buffer > 0:
            slots_before = (overrun_buffer + slot_duration - 1) // slot_duration
            for i in range(1, slots_before + 1):
                t = minute - i * slot_duration
                if t >= 0 and not self.is_available(court, t):
                    return False

        return True


class PlayerTracker:
    """Tracks player match history for rest-rule enforcement.

    Stores the full history of scheduled matches (start, end, division,
    category) so that rest between any two matches can be computed using
    context-dependent rest rules.

    Rest is enforced bidirectionally: a new match must have enough rest
    after any earlier match AND before any later match already scheduled.
    This allows independent matches to be placed in any order — a player
    can play XD A on Saturday even if their MD A match was already
    scheduled on Sunday, as long as rest constraints are satisfied in
    both directions.
    """

    def __init__(self, config):
        self.config = config
        # player_name -> list of (start_minute, end_minute, div_code, category)
        self.history = defaultdict(list)

    def can_play_at(self, players, start_minute, duration, new_div_code, new_category):
        """Check if all players can play a match at the given time.

        Verifies rest constraints in both directions:
        - Forward: enough rest after any earlier match (prior match end + rest <= start)
        - Backward: enough rest before any later match (start + duration + rest <= later match start)
        """
        if not players:
            return True
        new_end = start_minute + duration
        for p in players:
            for prev_start, prev_end, prev_div, prev_cat in self.history[p]:
                rest = compute_rest_between(
                    self.config, prev_div, prev_cat, new_div_code, new_category
                )
                if prev_end <= start_minute:
                    # Prior match ended before this one starts — check forward rest
                    if prev_end + rest > start_minute:
                        return False
                elif new_end <= prev_start:
                    # This match ends before the prior one starts — check backward rest
                    if new_end + rest > prev_start:
                        return False
                else:
                    # Overlapping — not allowed
                    return False
        return True

    def earliest_for_match(self, players, new_div_code, new_category):
        """Get the earliest time when all players can start, considering
        only matches that are scheduled before the candidate time.

        This provides a lower bound for slot searching. The full
        bidirectional check is done by can_play_at().
        """
        if not players:
            return 0
        earliest = 0
        for p in players:
            for _, prev_end, prev_div, prev_cat in self.history[p]:
                rest = compute_rest_between(
                    self.config, prev_div, prev_cat, new_div_code, new_category
                )
                earliest = max(earliest, prev_end + rest)
        return earliest

    def update(self, players, match_start, duration, div_code, category):
        """Record a scheduled match for player availability tracking."""
        end_min = match_start + duration
        for p in players:
            self.history[p].append((match_start, end_min, div_code, category))


# ── Court eligibility ────────────────────────────────────────────

def _day_name_for_minute(venue_model, minute):
    """Return the day name for a given minute offset."""
    for day in venue_model["days"]:
        if day["start_minute"] <= minute < day["start_minute"] + 24 * 60:
            return day["name"]
    return None


def get_eligible_courts(match, time_minute, config, venue_model):
    """Get ordered list of courts to try for a match at a given time."""
    category = match.category
    day_name = _day_name_for_minute(venue_model, time_minute)
    pref = get_court_preference(config, category, day_name=day_name)

    # Build ordered court list from preference chain
    ordered = []
    for key in ("required_courts", "preferred_courts", "fallback_courts", "last_resort_courts"):
        courts = pref.get(key)
        if courts:
            for c in courts:
                if c not in ordered:
                    ordered.append(c)

    # If required_courts is set, only use those (no fallback)
    if pref.get("required_courts"):
        ordered = list(pref["required_courts"])

    # Filter out courts not available at this time
    available = []
    for court in ordered:
        for crt, start, end in venue_model["court_windows"]:
            if crt == court and start <= time_minute < end:
                available.append(court)
                break

    return available


# ── Scheduling algorithm ─────────────────────────────────────────

def schedule_matches(matches, match_by_id, config, venue_model):
    """Main scheduling loop. Returns (scheduled_dict, unscheduled_list)."""
    court_sched = CourtSchedule(venue_model)
    player_tracker = PlayerTracker(config)
    scheduled = {}       # match_id -> (court, minute)
    scheduled_end = {}   # match_id -> end minute
    unscheduled = []

    all_slots = venue_model["all_slots"]
    slot_duration = venue_model["slot_duration"]
    day_start_minutes = venue_model["day_start_minutes"]

    # Minimum rest for prerequisite gaps (cross-division baseline)
    min_prereq_rest = get_cross_division_rest(config)

    # Sort by priority, then pool_round (groups non-conflicting RR matches),
    # then most-constrained-first (-player count, so doubles before singles),
    # then match_num and division for determinism.
    sorted_matches = sorted(matches, key=lambda m: (
        m.priority, m.pool_round, -len(m.known_players),
        m.match_num, m.division_code
    ))

    # Track matches that can't be scheduled because a prerequisite failed
    unschedulable = set()

    for match in sorted_matches:
        # If any non-bye prerequisite was unschedulable, this match is too
        prereq_failed = False
        for prereq_id in match.prerequisites:
            if prereq_id in unschedulable:
                prereq_failed = True
                break
        if prereq_failed:
            unschedulable.add(match.id)
            unscheduled.append(match)
            continue

        # Compute earliest start time from hard constraints
        # (player rest is checked bidirectionally per-slot via can_play_at)
        earliest = 0

        # Prerequisite constraint — feeder matches must finish + minimum rest
        for prereq_id in match.prerequisites:
            if prereq_id in scheduled_end:
                earliest = max(earliest, scheduled_end[prereq_id] + min_prereq_rest)

        # Day constraint (e.g. SF/Final must be on Sunday)
        if match.day_constraint:
            day_start = day_start_minutes.get(match.day_constraint, 0)
            earliest = max(earliest, day_start)

        # Snap to next slot boundary
        if earliest % slot_duration != 0:
            earliest = ((earliest // slot_duration) + 1) * slot_duration

        # Find available slot
        placed = False
        for slot in all_slots:
            if slot < earliest:
                continue

            courts = get_eligible_courts(match, slot, config, venue_model)
            for court in courts:
                if court_sched.can_book(court, slot, match.duration_min, match.overrun_buffer):
                    # Check player availability bidirectionally
                    if match.has_real_players and match.known_players:
                        if not player_tracker.can_play_at(
                            match.known_players, slot, match.duration_min,
                            match.division_code, match.category
                        ):
                            continue

                    # Book it — blocks duration + overrun_buffer on the court
                    court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)
                    if match.has_real_players:
                        player_tracker.update(
                            match.known_players, slot,
                            match.duration_min, match.division_code, match.category
                        )
                    scheduled[match.id] = (court, slot)
                    scheduled_end[match.id] = slot + match.duration_min
                    placed = True
                    break
            if placed:
                break

        if not placed:
            unschedulable.add(match.id)
            unscheduled.append(match)

    return scheduled, unscheduled, court_sched, player_tracker


# ── Validation ───────────────────────────────────────────────────

def validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker, config, venue_model):
    """Run validation checks and return warnings."""
    warnings = []
    day_start_minutes = venue_model["day_start_minutes"]

    # Check day constraints
    for match in matches:
        if match.id not in scheduled:
            continue
        court, minute = scheduled[match.id]
        if match.day_constraint:
            required_start = day_start_minutes.get(match.day_constraint, 0)
            # Check that match is on the required day
            on_correct_day = False
            for day in venue_model["days"]:
                if day["name"] == match.day_constraint:
                    if day["start_minute"] <= minute < day["start_minute"] + 24 * 60:
                        on_correct_day = True
                    break
            if not on_correct_day:
                day_name, time_str = config_minute_to_display(venue_model, minute)
                warnings.append(
                    f"{match.round_name} on wrong day: {match.id} at {day_name} {time_str} "
                    f"(should be {match.day_constraint})"
                )

    # Check round ordering
    for match in matches:
        if match.id not in scheduled:
            continue
        _, match_time = scheduled[match.id]
        for prereq_id in match.prerequisites:
            if prereq_id in scheduled:
                _, prereq_time = scheduled[prereq_id]
                if prereq_time >= match_time:
                    warnings.append(
                        f"Round order violation: {prereq_id} at {config_minute_to_display(venue_model, prereq_time)} "
                        f"but {match.id} at {config_minute_to_display(venue_model, match_time)}"
                    )

    # Check player double-booking (only for matches with confirmed real players)
    player_schedule = defaultdict(list)  # player -> list of (start, end, match_id)
    for match in matches:
        if match.id not in scheduled:
            continue
        if not match.has_real_players:
            continue  # Skip placeholder matches — players are only possibilities
        court, minute = scheduled[match.id]
        end = minute + match.duration_min
        for p in match.known_players:
            player_schedule[p].append((minute, end, match.id))

    for player, slots in player_schedule.items():
        slots.sort()
        for i in range(len(slots) - 1):
            _, end1, id1 = slots[i]
            start2, _, id2 = slots[i + 1]
            if start2 < end1:
                warnings.append(f"Double-booking: {player} in {id1} and {id2}")
            elif start2 < end1 + 30:  # minimum rest period
                warnings.append(
                    f"Insufficient rest for {player}: {id1} ends at {config_minute_to_display(venue_model, end1)}, "
                    f"{id2} starts at {config_minute_to_display(venue_model, start2)}"
                )

    # Check court preferences (required_courts) for all matches
    for match in matches:
        if match.id not in scheduled:
            continue
        court, minute = scheduled[match.id]
        day_name = _day_name_for_minute(venue_model, minute)
        pref = get_court_preference(config, match.category, day_name=day_name)
        required = pref.get("required_courts")
        if required and court not in required:
            warnings.append(f"{match.category} on wrong court: {match.id} on court {court}")

    return warnings


# ── Output generation ────────────────────────────────────────────

def write_schedules(matches, match_by_id, scheduled, unscheduled, warnings, config, venue_model):
    """Write session JSON files and index."""
    schedules_dir = config["paths"]["schedules_dir"]
    os.makedirs(schedules_dir, exist_ok=True)

    sessions = venue_model["sessions"]
    tournament_name = get_tournament_name(config)

    # Build scheduled match records
    records = []
    for match in matches:
        if match.id not in scheduled:
            continue
        court, minute = scheduled[match.id]
        day, time_str = config_minute_to_display(venue_model, minute)
        rec = {
            "time": time_str,
            "court": court,
            "division": match.division_code,
            "division_name": match.division_name,
            "round": match.round_name,
            "match_num": match.match_num,
            "player1": match.player1,
            "player2": match.player2,
            "duration_min": match.duration_min,
            "category": match.category,
        }
        if match.player1.startswith("Winner ") or match.player1.startswith("Slot "):
            rec["notes"] = "Players TBD based on earlier results"
        records.append((minute, rec))

    records.sort(key=lambda x: (x[0], x[1]["court"]))

    # Split into sessions
    session_data = []
    for sess in sessions:
        sess_matches = [
            rec for minute, rec in records
            if sess["start"] <= minute < sess["end"]
        ]
        session_json = {
            "session": sess["name"],
            "date": sess["date"],
            "start": sess["start_time"],
            "end": sess["end_time"],
            "matches": sess_matches,
        }

        outpath = os.path.join(schedules_dir, sess["file"])
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(session_json, f, indent=2, ensure_ascii=False)

        session_data.append({
            "file": sess["file"],
            "label": sess["name"],
            "time_range": f"{sess['start_time']}–{sess['end_time']}",
            "match_count": len(sess_matches),
        })

    # Index
    index = {
        "tournament": tournament_name,
        "generated": str(date.today()),
        "sessions": session_data,
        "total_matches": len(scheduled) + len(unscheduled),
        "total_scheduled": len(scheduled),
        "unscheduled": [m.id for m in unscheduled],
        "warnings": warnings,
    }

    index_path = os.path.join(schedules_dir, "schedule_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return session_data


# ── Main ─────────────────────────────────────────────────────────

def main(config=None):
    if config is None:
        parser = argparse.ArgumentParser(description="Generate match schedules")
        parser.add_argument("--tournament", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            help="Path to tournament directory (default: project root)")
        args = parser.parse_args()
        config = load_config(args.tournament)

    venue_model = build_venue_model(config)
    divisions_dir = config["paths"]["divisions_dir"]

    print(f"Loading divisions from: {divisions_dir}/")
    matches, match_by_id = load_all_matches(config)
    print(f"Loaded {len(matches)} schedulable matches (byes excluded)\n")

    print("Scheduling...")
    scheduled, unscheduled, court_sched, player_tracker = schedule_matches(
        matches, match_by_id, config, venue_model
    )

    print(f"  Scheduled: {len(scheduled)}")
    print(f"  Unscheduled: {len(unscheduled)}")
    if unscheduled:
        print("  Unscheduled matches:")
        for m in unscheduled:
            print(f"    {m.id}")

    print("\nValidating...")
    warnings = validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker, config, venue_model)
    if warnings:
        print(f"  {len(warnings)} warnings:")
        for w in warnings:
            print(f"    WARNING: {w}")
    else:
        print("  No warnings — all checks passed!")

    schedules_dir = config["paths"]["schedules_dir"]
    print(f"\nWriting schedules to: {schedules_dir}/")
    session_data = write_schedules(matches, match_by_id, scheduled, unscheduled, warnings, config, venue_model)

    print("\nSchedule Summary:")
    for sess in session_data:
        print(f"  {sess['label']:25s} {sess['match_count']:3d} matches  ({sess['time_range']})")
    total = sum(s["match_count"] for s in session_data)
    print(f"  {'TOTAL':25s} {total:3d} matches")

    # Show per-division breakdown
    print("\nPer-Division:")
    div_counts = defaultdict(int)
    for match in matches:
        if match.id in scheduled:
            div_counts[match.division_code] += 1
    for code in sorted(div_counts):
        print(f"  {code:12s}: {div_counts[code]} matches scheduled")

    print(f"\nDone. Files written to {schedules_dir}/")


if __name__ == "__main__":
    main()
