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
import sys
from collections import defaultdict
from datetime import date

from config import (load_config, get_tournament_name, get_priorities,
                    get_round_priority_map, get_elite_divisions,
                    get_day_constraints, get_division_day_constraints,
                    get_match_duration, get_division_priorities,
                    get_overrun_buffer, compute_rest_between,
                    get_cross_division_rest, get_same_division_rest,
                    get_court_preference, get_round_completion,
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
        # True if ALL players are confirmed (no placeholders).
        # False if any side is a placeholder ("Winner of..." / "Slot N").
        self.has_real_players = bool(known_players) and not (
            player1.startswith("Winner ") or player1.startswith("Slot ") or
            player2.startswith("Winner ") or player2.startswith("Slot ")
        )
        # True if at least one side has a confirmed player name (for partial tracking).
        self.has_some_real_players = bool(known_players) and (
            not (player1.startswith("Winner ") or player1.startswith("Slot ")) or
            not (player2.startswith("Winner ") or player2.startswith("Slot "))
        )
        # Effective players for scheduling (filtered by probability threshold).
        # Set by _apply_probability_filter(); defaults to known_players.
        self.effective_players = list(known_players) if known_players else []


def _build_day_constraint_set(config):
    """Build day constraint maps from config.

    Returns (global_map, division_map):
      - global_map: round_name -> day_name (applies to all divisions)
      - division_map: div_code -> {round_name -> day_name} (per-division overrides)

    Per-division constraints override global constraints when both exist
    for the same round.

    Round names in division_day_constraints support the special names:
      - "Pool": matches round-robin pool rounds
      - "Group": matches all group-stage pool rounds (e.g., "Group A Pool")
    """
    constraints = get_day_constraints(config)
    global_map = {}
    for constraint in constraints:
        day_name = constraint.get("day")
        for round_name in constraint.get("rounds", []):
            global_map[round_name] = day_name

    div_constraints = get_division_day_constraints(config)
    division_map = {}  # div_code -> {round_name -> day_name}
    for div_code, constraint_list in div_constraints.items():
        div_map = {}
        for constraint in constraint_list:
            day_name = constraint.get("day")
            for round_name in constraint.get("rounds", []):
                div_map[round_name] = day_name
        division_map[div_code] = div_map

    return global_map, division_map


def _resolve_day_constraint(div_code, round_name, global_day_map, division_day_map):
    """Resolve the day constraint for a specific division and round.

    Checks per-division constraints first, then global.
    For group-stage rounds (e.g., "Group A Pool"), also checks the special
    "Group" key in division constraints.

    Returns day_name or None.
    """
    div_map = division_day_map.get(div_code, {})
    # Direct match on the round name in per-division constraints
    if round_name in div_map:
        return div_map[round_name]
    # For group pool rounds, check the "Group" shorthand
    if " Pool" in round_name and "Group" in div_map:
        return div_map["Group"]
    # Check global constraints
    if round_name in global_day_map:
        return global_day_map[round_name]
    # For group pool rounds, check "Group" in global too
    if " Pool" in round_name and "Group" in global_day_map:
        return global_day_map["Group"]
    return None


def load_all_matches(config):
    """Load all schedulable matches from division JSON files."""
    divisions_dir = config["paths"]["divisions_dir"]

    with open(os.path.join(divisions_dir, "tournament_index.json"), encoding="utf-8") as f:
        index = json.load(f)

    elite_divisions = get_elite_divisions(config)
    priorities = get_priorities(config)
    round_priority_map = get_round_priority_map(config)
    div_priorities = get_division_priorities(config)
    global_day_map, division_day_map = _build_day_constraint_set(config)

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
                       resolved_round_priority, priorities, global_day_map,
                       division_day_map, overrun_buf)

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

    # Apply per-division priority adjustments
    if div_priorities:
        for m in all_matches:
            offset = div_priorities.get(m.division_code, 0)
            if offset:
                m.priority += offset

    # Resolve known_players for later rounds by tracing back through brackets
    _resolve_known_players(all_matches, match_by_id)

    return all_matches, match_by_id


def _load_elimination_matches(data, div_code, div_name, category, is_elite, duration,
                              resolved_round_priority, priorities, global_day_map,
                              division_day_map, overrun_buf=0):
    matches = []
    rounds = data.get("rounds", [])

    # Build a map of round_name -> round data for lookup
    round_map = {rnd["name"]: rnd for rnd in rounds}

    for rnd in rounds:
        round_name = rnd["name"]
        priority = resolved_round_priority.get(round_name, priorities.get("round_1", 20))
        day_constraint = _resolve_day_constraint(
            div_code, round_name, global_day_map, division_day_map
        )

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
                             resolved_round_priority, priorities, global_day_map,
                             division_day_map, overrun_buf=0):
    matches = []
    day_constraint = _resolve_day_constraint(
        div_code, "Pool", global_day_map, division_day_map
    )
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
            priority=pool_priority, day_constraint=day_constraint,
            prerequisites=[], is_elite=is_elite,
            overrun_buffer=overrun_buf,
        )
        matches.append(match)

    # Compute scheduling rounds for parallelism
    _compute_pool_rounds(matches)
    return matches


def _load_group_playoff_matches(data, div_code, div_name, category, is_elite, duration,
                                resolved_round_priority, priorities, global_day_map,
                                division_day_map, overrun_buf=0):
    matches = []
    group_match_ids = []

    # Group stage matches — all groups share the same day constraint
    # The "Group" shorthand in config applies to all "X Pool" round names
    group_day_constraint = _resolve_day_constraint(
        div_code, "Group A Pool", global_day_map, division_day_map
    )

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
                priority=priorities.get("pool", 10), day_constraint=group_day_constraint,
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
            # Resolve day constraint for "Playoff Round 1", etc.
            playoff_round_label = f"Playoff {round_name}"
            day_constraint = _resolve_day_constraint(
                div_code, playoff_round_label, global_day_map, division_day_map
            )
            # Also check if the bare round name has a constraint (global SF/Final)
            if day_constraint is None:
                day_constraint = _resolve_day_constraint(
                    div_code, round_name, global_day_map, division_day_map
                )

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


# ── Probability-based player filtering ──────────────────────────

def _get_probability_config(config):
    """Get probability filter settings from scheduling config."""
    return config["scheduling"].get("probability_filter", {
        "default_threshold": 0.0,
        "use_seeding": False,
        "seeding_probabilities": {"default": 0.50},
        "divisions": {},
    })


def _get_round_depth(match, match_by_id, cache=None):
    """Compute round depth: number of prerequisite chain links to a real-player match."""
    if cache is None:
        cache = {}
    if match.id in cache:
        return cache[match.id]
    if match.has_real_players or not match.prerequisites:
        cache[match.id] = 0
        return 0
    max_depth = 0
    for prereq_id in match.prerequisites:
        prereq = match_by_id.get(prereq_id)
        if prereq:
            max_depth = max(max_depth, 1 + _get_round_depth(prereq, match_by_id, cache))
    cache[match.id] = max_depth
    return max_depth


def _get_win_probability(seed_a, seed_b, seeding_probs):
    """Get win probability for player A vs player B based on seeds."""
    default_prob = seeding_probs.get("default", 0.50)
    if seed_a is None and seed_b is None:
        return default_prob
    if seed_a is not None and seed_b is None:
        return seeding_probs.get(f"{seed_a}_vs_unseeded", default_prob)
    if seed_a is None and seed_b is not None:
        return 1.0 - seeding_probs.get(f"{seed_b}_vs_unseeded", default_prob)
    return seeding_probs.get("seed_vs_seed", default_prob)


def _build_seed_map(config):
    """Build player_name -> seed_label map from division JSON data."""
    seed_map = {}
    divisions_dir = config["paths"]["divisions_dir"]
    index_path = os.path.join(divisions_dir, "tournament_index.json")
    if not os.path.exists(index_path):
        return seed_map
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue
        filepath = os.path.join(divisions_dir, entry["file"])
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        for player in data.get("players", []):
            seed = player.get("seed")
            if seed:
                name = player.get("name")
                if name:
                    seed_map[name] = seed
                for sub in player.get("players", []):
                    if sub.get("name"):
                        seed_map[sub["name"]] = sub.get("seed") or seed
    return seed_map


def _compute_player_probabilities(all_matches, match_by_id, config):
    """Compute normalized probability for each player reaching each match.

    Returns dict: match_id -> {player_name: normalized_probability}
    """
    prob_config = _get_probability_config(config)
    use_seeding = prob_config.get("use_seeding", False)
    seeding_probs = prob_config.get("seeding_probabilities", {})

    seed_map = _build_seed_map(config) if use_seeding else {}

    # Raw probabilities: match_id -> {player: raw_probability}
    raw_probs = {}

    # Process matches in priority order (ensures feeders computed before dependents)
    sorted_matches = sorted(all_matches, key=lambda m: m.priority)

    for match in sorted_matches:
        if match.has_real_players:
            raw_probs[match.id] = {p: 1.0 for p in match.known_players}
            continue

        match_probs = {}
        for prereq_id in match.prerequisites:
            prereq = match_by_id.get(prereq_id)
            if prereq is None:
                continue
            prereq_player_probs = raw_probs.get(prereq_id, {})
            if not prereq_player_probs:
                continue

            if use_seeding:
                p1_names = set(extract_player_names(prereq.player1))
                p2_names = set(extract_player_names(prereq.player2))
                prereq_players = list(prereq_player_probs.keys())
                for player, prob in prereq_player_probs.items():
                    player_seed = seed_map.get(player)
                    if player in p1_names:
                        opponents = [p for p in prereq_players if p in p2_names]
                    else:
                        opponents = [p for p in prereq_players if p in p1_names]
                    if opponents:
                        opp_seed = seed_map.get(opponents[0])
                        win_prob = _get_win_probability(player_seed, opp_seed, seeding_probs)
                    else:
                        win_prob = seeding_probs.get("default", 0.50)
                    match_probs[player] = prob * win_prob
            else:
                for player, prob in prereq_player_probs.items():
                    match_probs[player] = prob * 0.5

        raw_probs[match.id] = match_probs

    # Normalize per match by round depth
    depth_cache = {}
    normalized = {}
    for match in all_matches:
        if match.has_real_players:
            normalized[match.id] = {p: 1.0 for p in match.known_players}
            continue

        depth = _get_round_depth(match, match_by_id, depth_cache)
        base_prob = 0.5 ** depth if depth > 0 else 1.0

        match_raw = raw_probs.get(match.id, {})
        norm_probs = {}
        for player, prob in match_raw.items():
            norm_probs[player] = min(prob / base_prob, 1.0) if base_prob > 0 else 1.0
        normalized[match.id] = norm_probs

    return normalized


def _apply_probability_filter(all_matches, probabilities, config):
    """Filter each match's known_players by probability threshold.
    Sets match.effective_players."""
    prob_config = _get_probability_config(config)
    default_threshold = prob_config.get("default_threshold", 0.0)
    div_configs = prob_config.get("divisions", {})

    for match in all_matches:
        threshold = default_threshold
        div_override = div_configs.get(match.division_code, {})
        if isinstance(div_override, dict):
            threshold = div_override.get("threshold", default_threshold)

        if threshold <= 0.0:
            match.effective_players = list(match.known_players)
        else:
            match_probs = probabilities.get(match.id, {})
            match.effective_players = [
                p for p in match.known_players
                if match_probs.get(p, 0.0) >= threshold
            ]


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
                    self.config, prev_div, prev_cat, new_div_code, new_category,
                    player_name=p,
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
                    self.config, prev_div, prev_cat, new_div_code, new_category,
                    player_name=p,
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

def _get_same_day_key(match):
    """Return the grouping key for same-day enforcement.

    All matches sharing a key must be scheduled on the same day.
    For group+playoff divisions, all group pools share one key (so all
    group-stage matches land on the same day regardless of group letter).
    """
    div_code = match.division_code
    round_name = match.round_name
    # Group pool rounds like "Group A Pool", "Group B Pool" → shared key
    if " Pool" in round_name and round_name != "Pool":
        return (div_code, "Group Pool")
    return (div_code, round_name)


def _day_bounds_for_minute(venue_model, minute):
    """Return (day_start, day_end) for the day containing the given minute."""
    for day in venue_model["days"]:
        if day["start_minute"] <= minute < day["start_minute"] + 24 * 60:
            return day["start_minute"], day["end_minute"]
    return None, None


# Elimination round ordering for round-completion constraint
_ROUND_ORDER = [
    "Round 1", "Round 2", "Round 3", "Round 4",
    "Quarter-Final", "Semi-Final", "Final",
]

# Playoff round ordering
_PLAYOFF_ROUND_ORDER = [
    "Playoff Quarter-Final", "Playoff Semi-Final", "Playoff Final",
]


def _get_previous_round(div_code, round_name, div_round_matches):
    """Get the previous round name for a match, within the same division.

    Returns None if this is the first round or a pool round.
    """
    # Skip pool/group rounds — round completion doesn't apply
    if "Pool" in round_name:
        return None

    # Determine the round sequence for this division
    if round_name.startswith("Playoff "):
        order = _PLAYOFF_ROUND_ORDER
    else:
        order = _ROUND_ORDER

    if round_name not in order:
        return None

    idx = order.index(round_name)
    # Walk backwards to find the previous round that actually has matches
    for i in range(idx - 1, -1, -1):
        prev = order[i]
        if (div_code, prev) in div_round_matches:
            return prev
    return None


def schedule_matches(matches, match_by_id, config, venue_model):
    """Main scheduling loop. Returns (scheduled_dict, unscheduled_list)."""
    # Compute probabilities and filter effective players
    probabilities = _compute_player_probabilities(matches, match_by_id, config)
    _apply_probability_filter(matches, probabilities, config)

    court_sched = CourtSchedule(venue_model)
    player_tracker = PlayerTracker(config)
    scheduled = {}       # match_id -> (court, minute)
    scheduled_end = {}   # match_id -> end minute
    unscheduled = []

    # Pre-block court buffer slots (breaks/maintenance)
    for court, minute in venue_model.get("court_buffer_blocks", []):
        if (court, minute) not in court_sched.booked:
            court_sched.booked[(court, minute)] = "_buffer_break"

    # Round-completion constraint: build (div_code, round_name) -> [match_ids]
    rc_enabled, rc_exceptions = get_round_completion(config)
    div_round_matches = defaultdict(list)  # (div_code, round_name) -> [match_id]
    if rc_enabled:
        for m in matches:
            div_round_matches[(m.division_code, m.round_name)].append(m.id)

    all_slots = venue_model["all_slots"]
    slot_duration = venue_model["slot_duration"]
    day_start_minutes = venue_model["day_start_minutes"]

    # Build day_end_minutes for same-day enforcement
    day_end_minutes = {}
    for day in venue_model["days"]:
        day_end_minutes[day["name"]] = day["end_minute"]

    # Minimum rest for prerequisite gaps (cross-division baseline)
    min_prereq_rest = get_cross_division_rest(config)

    # Same-day enforcement: once the first match of a (div, round) group
    # is placed on a day, all remaining matches in that group are constrained
    # to the same day.
    # Key: _get_same_day_key(match) -> day_name
    round_day_assignments = {}

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
        latest = None  # upper bound on slot (exclusive), set by same-day rule

        # Prerequisite constraint — feeder matches must finish + minimum rest
        for prereq_id in match.prerequisites:
            if prereq_id in scheduled_end:
                earliest = max(earliest, scheduled_end[prereq_id] + min_prereq_rest)

        # Round-completion constraint: all matches of the previous round in
        # this division must finish before this match can start
        if rc_enabled and match.division_code not in rc_exceptions:
            prev_round = _get_previous_round(
                match.division_code, match.round_name, div_round_matches
            )
            if prev_round:
                prev_match_ids = div_round_matches[(match.division_code, prev_round)]
                # Check if any previous-round match failed to schedule
                prev_failed = any(mid in unschedulable for mid in prev_match_ids)
                if prev_failed:
                    unschedulable.add(match.id)
                    unscheduled.append(match)
                    continue
                # All previous-round matches should be scheduled by now
                # (they have lower priority). Use latest end time as earliest start.
                if prev_match_ids:
                    latest_prev_end = max(
                        scheduled_end.get(mid, 0) for mid in prev_match_ids
                    )
                    earliest = max(earliest, latest_prev_end)

        # Day constraint from config (e.g. SF/Final must be on Sunday)
        effective_day = match.day_constraint

        # Same-day enforcement: if another match in this round+division
        # was already placed on a day, this match must go on that same day
        same_day_key = _get_same_day_key(match)
        if same_day_key in round_day_assignments:
            assigned_day = round_day_assignments[same_day_key]
            day_start = day_start_minutes.get(assigned_day, 0)
            day_end = day_end_minutes.get(assigned_day, day_start + 24 * 60)
            earliest = max(earliest, day_start)
            latest = day_end
            effective_day = assigned_day
        elif effective_day:
            day_start = day_start_minutes.get(effective_day, 0)
            day_end = day_end_minutes.get(effective_day, day_start + 24 * 60)
            earliest = max(earliest, day_start)
            latest = day_end

        # Snap to next slot boundary
        if earliest % slot_duration != 0:
            earliest = ((earliest // slot_duration) + 1) * slot_duration

        # Find available slot
        placed = False
        for slot in all_slots:
            if slot < earliest:
                continue
            # If same-day or day constraint limits the day, stop searching beyond it
            if latest is not None and slot >= latest:
                break

            courts = get_eligible_courts(match, slot, config, venue_model)
            for court in courts:
                if court_sched.can_book(court, slot, match.duration_min, match.overrun_buffer):
                    # Check player availability bidirectionally using effective_players
                    # (filtered by probability threshold for placeholder matches)
                    if match.effective_players:
                        if not player_tracker.can_play_at(
                            match.effective_players, slot, match.duration_min,
                            match.division_code, match.category
                        ):
                            continue

                    # Book it — blocks duration + overrun_buffer on the court
                    court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)
                    # Update tracker for confirmed players. For matches where
                    # one side is a bye winner (confirmed) and the other is a
                    # placeholder ("Winner R1-M5"), track the confirmed players
                    # so they aren't double-booked across divisions.
                    if match.has_some_real_players:
                        # Extract only the confirmed player names (from the
                        # non-placeholder side)
                        confirmed = set()
                        for p_str in (match.player1, match.player2):
                            if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                                confirmed.update(extract_player_names(p_str))
                        if confirmed:
                            player_tracker.update(
                                list(confirmed), slot,
                                match.duration_min, match.division_code, match.category
                            )
                    scheduled[match.id] = (court, slot)
                    scheduled_end[match.id] = slot + match.duration_min

                    # Record same-day assignment for this round+division
                    if same_day_key not in round_day_assignments:
                        placed_day = _day_name_for_minute(venue_model, slot)
                        round_day_assignments[same_day_key] = placed_day

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
    """Run validation checks and return (errors, warnings).

    Errors are hard failures (e.g., same-day violations). Warnings are
    advisory (e.g., insufficient rest for placeholder matches).
    """
    errors = []
    warnings = []
    day_start_minutes = venue_model["day_start_minutes"]

    # Check same-day rule: all matches in the same round+division must be on the same day
    round_day_map = {}  # _get_same_day_key -> {day_name: [match_ids]}
    for match in matches:
        if match.id not in scheduled:
            continue
        _, minute = scheduled[match.id]
        day_name = _day_name_for_minute(venue_model, minute)
        key = _get_same_day_key(match)
        if key not in round_day_map:
            round_day_map[key] = defaultdict(list)
        round_day_map[key][day_name].append(match.id)

    for key, day_matches in round_day_map.items():
        if len(day_matches) > 1:
            div_code, round_label = key
            day_list = ", ".join(
                f"{d} ({len(ids)} matches)" for d, ids in day_matches.items()
            )
            errors.append(
                f"Same-day violation: {div_code} {round_label} split across days: {day_list}"
            )

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
                errors.append(
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

    return errors, warnings


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
    errors, warnings = validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker, config, venue_model)
    if errors:
        print(f"  {len(errors)} ERRORS:")
        for e in errors:
            print(f"    ERROR: {e}")
    if warnings:
        print(f"  {len(warnings)} warnings:")
        for w in warnings:
            print(f"    WARNING: {w}")
    if not errors and not warnings:
        print("  No errors or warnings — all checks passed!")

    if errors:
        print(f"\nAborting: {len(errors)} scheduling error(s) detected.")
        sys.exit(1)

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
