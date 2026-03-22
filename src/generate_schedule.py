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

from config import (load_config, get_tournament_name, resolve_priority,
                    get_day_constraints, get_division_day_constraints,
                    get_match_duration, get_time_deadlines, get_earliest_start,
                    get_match_density, get_overrun_buffer, compute_rest_between,
                    get_cross_division_rest, get_same_division_rest,
                    get_court_preference, get_round_completion,
                    get_potential_conflict_avoidance, get_round_time_limit,
                    get_pool_round_same_day, get_slot_duration, build_venue_model,
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

    global_day_map, division_day_map = _build_day_constraint_set(config)

    all_matches = []
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
        duration = get_match_duration(config, category, div_code)
        overrun_buf = get_overrun_buffer(config, category)

        loader_args = (config, data, div_code, div_name, category, duration,
                       global_day_map, division_day_map, overrun_buf)

        if fmt == "elimination":
            matches = _load_elimination_matches(*loader_args)
        elif fmt == "round_robin":
            matches = _load_roundrobin_matches(*loader_args)
        elif fmt == "group_playoff":
            matches = _load_group_playoff_matches(*loader_args)
        else:
            continue

        all_matches.extend(matches)
        for m in matches:
            match_by_id[m.id] = m

    # Infer effective day for matches without explicit day constraints.
    # If a later round in the same division has a day constraint, earlier
    # rounds will likely end up on the same day (due to round-completion).
    # Use this inferred day to resolve day-specific priorities.
    _infer_day_and_resolve_priorities(all_matches, config)

    # Resolve known_players for later rounds by tracing back through brackets
    _resolve_known_players(all_matches, match_by_id)

    return all_matches, match_by_id


def _infer_day_and_resolve_priorities(all_matches, config):
    """Infer effective day for matches and re-resolve priorities with day_overrides.

    For elimination rounds, if SF/Final has a day constraint, earlier rounds
    (QF, R2) in the same division are inferred to be on the same day when
    they have no explicit constraint. Their priorities are then re-resolved
    using the day-specific overrides.
    """
    # Build div_code -> {round_name -> day_constraint} from existing matches
    div_round_days = defaultdict(dict)
    for m in all_matches:
        if m.day_constraint:
            div_round_days[m.division_code][m.round_name] = m.day_constraint

    # Round order for inference (later rounds inform earlier)
    round_order = ["Round 1", "Round 2", "Quarter-Final", "Semi-Final", "Final"]
    playoff_order = ["Playoff Quarter-Final", "Playoff Semi-Final", "Playoff Final"]

    for m in all_matches:
        if m.day_constraint:
            continue  # already has explicit day

        div_days = div_round_days.get(m.division_code, {})
        if not div_days:
            continue

        # Check if a later round in this division has a day constraint
        bare = m.round_name.replace("Playoff ", "") if m.round_name.startswith("Playoff ") else m.round_name
        order = playoff_order if m.round_name.startswith("Playoff ") else round_order

        if bare not in order:
            continue

        idx = order.index(bare if not m.round_name.startswith("Playoff ") else m.round_name)
        inferred_day = None
        for later_idx in range(idx + 1, len(order)):
            later_round = order[later_idx]
            if later_round in div_days:
                inferred_day = div_days[later_round]
                break

        if inferred_day:
            # Re-resolve priority with the inferred day
            new_priority = resolve_priority(
                config, m.round_name, m.category, m.division_code,
                day_name=inferred_day,
            )
            if new_priority != m.priority:
                m.priority = new_priority


def _load_elimination_matches(config, data, div_code, div_name, category, duration,
                              global_day_map, division_day_map, overrun_buf=0):
    matches = []
    rounds = data.get("rounds", [])

    # Build a map of round_name -> round data for lookup
    round_map = {rnd["name"]: rnd for rnd in rounds}

    for rnd in rounds:
        round_name = rnd["name"]
        day_constraint = _resolve_day_constraint(
            div_code, round_name, global_day_map, division_day_map
        )
        priority = resolve_priority(config, round_name, category, div_code,
                                    day_name=day_constraint)

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
                prerequisites=prereqs, is_elite=False,
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


def _load_roundrobin_matches(config, data, div_code, div_name, category, duration,
                             global_day_map, division_day_map, overrun_buf=0):
    matches = []
    day_constraint = _resolve_day_constraint(
        div_code, "Pool", global_day_map, division_day_map
    )
    pool_priority = resolve_priority(config, "Pool", category, div_code,
                                     day_name=day_constraint)
    has_pool_rounds = False
    for m in data.get("matches", []):
        match_id = make_match_id(div_code, "Pool", m["match"])
        p1 = m.get("player1", "")
        p2 = m.get("player2", "")
        known = extract_player_names(p1) + extract_player_names(p2)

        match = Match(
            match_id=match_id,
            div_code=div_code, div_name=div_name, category=category,
            round_name="Pool", match_num=m["match"],
            player1=p1, player2=p2, known_players=known,
            duration_min=duration,
            priority=pool_priority, day_constraint=day_constraint,
            prerequisites=[], is_elite=False,
            overrun_buffer=overrun_buf,
        )
        if "pool_round" in m:
            match.pool_round = m["pool_round"] - 1  # JSON is 1-based, internal is 0-based
            has_pool_rounds = True
        matches.append(match)

    # Compute scheduling rounds only if not provided in the data
    if not has_pool_rounds:
        _compute_pool_rounds(matches)
    return matches


def _load_group_playoff_matches(config, data, div_code, div_name, category, duration,
                                global_day_map, division_day_map, overrun_buf=0):
    matches = []
    group_match_ids = []

    # Group stage matches — all groups share the same day constraint
    group_day_constraint = _resolve_day_constraint(
        div_code, "Group A Pool", global_day_map, division_day_map
    )
    pool_priority = resolve_priority(config, "Pool", category, div_code,
                                     day_name=group_day_constraint)

    has_pool_rounds = False
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
                priority=pool_priority, day_constraint=group_day_constraint,
                prerequisites=[], is_elite=False,
                overrun_buffer=overrun_buf,
            )
            if "pool_round" in m:
                match.pool_round = m["pool_round"] - 1  # JSON is 1-based, internal is 0-based
                has_pool_rounds = True
            matches.append(match)
            group_match_ids.append(match_id)

    # Playoff bracket
    playoff = data.get("playoff")
    if playoff and playoff.get("rounds"):
        is_first_playoff_round = True

        for rnd in playoff["rounds"]:
            round_name = rnd["name"]
            playoff_round_label = f"Playoff {round_name}"

            day_constraint = _resolve_day_constraint(
                div_code, playoff_round_label, global_day_map, division_day_map
            )
            if day_constraint is None:
                day_constraint = _resolve_day_constraint(
                    div_code, round_name, global_day_map, division_day_map
                )

            priority = resolve_priority(config, playoff_round_label, category,
                                        div_code, day_name=day_constraint)
            bare_priority = resolve_priority(config, round_name, category,
                                            div_code, day_name=day_constraint)
            priority = min(priority, bare_priority)

            for m in rnd["matches"]:
                match_id = make_match_id(div_code, f"Playoff {round_name}", m["match"])

                p1 = m.get("player1", "")
                p2 = m.get("player2", "")
                known = extract_player_names(p1) + extract_player_names(p2)

                prereqs = []
                if is_first_playoff_round:
                    prereqs = list(group_match_ids)
                else:
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
                    prerequisites=prereqs, is_elite=False,
                    overrun_buffer=overrun_buf,
                )
                matches.append(match)

            is_first_playoff_round = False

    return matches


def _resolve_known_players(all_matches, match_by_id):
    """For later-round matches with 'Winner ...' or 'Slot ...' players, trace
    back through prerequisites to find all possible players (worst-case
    conflict set). Handles mixed matches where one side is confirmed and
    the other is a placeholder."""

    def _has_placeholder(match):
        return (match.player1.startswith("Winner ") or match.player1.startswith("Slot ") or
                match.player2.startswith("Winner ") or match.player2.startswith("Slot "))

    def get_all_possible_players(match_id, visited=None):
        if visited is None:
            visited = set()
        if match_id in visited:
            return []
        visited.add(match_id)

        m = match_by_id.get(match_id)
        if m is None:
            return []

        # If this match has no placeholders, return its known players
        if not _has_placeholder(m):
            return list(m.known_players)

        # Has placeholders — collect confirmed players from this match
        # plus trace through prerequisites for placeholder sides
        players = list(m.known_players)  # confirmed players from this match
        for prereq_id in m.prerequisites:
            prereq_players = get_all_possible_players(prereq_id, visited)
            players.extend(prereq_players)
        return players

    for match in all_matches:
        if _has_placeholder(match) and match.prerequisites:
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

    def can_book_override_buffer(self, court, minute, duration_min, overrun_buffer=0):
        """Check if a court can be booked if court buffer breaks are ignored.

        Returns (can_book, overridden_buffers) where overridden_buffers is a
        list of (court, minute) buffer slots that would need to be cleared.
        """
        slot_duration = self.venue_model["slot_duration"]
        total_forward = duration_min + overrun_buffer
        slots_forward = (total_forward + slot_duration - 1) // slot_duration
        overridden = []

        for i in range(slots_forward):
            t = minute + i * slot_duration
            if not self._court_exists(court, t):
                return False, []
            if (court, t) in self.booked:
                if self.booked[(court, t)] == "_buffer_break":
                    overridden.append((court, t))
                else:
                    return False, []

        if overrun_buffer > 0:
            slots_before = (overrun_buffer + slot_duration - 1) // slot_duration
            for i in range(1, slots_before + 1):
                t = minute - i * slot_duration
                if t >= 0 and (court, t) in self.booked:
                    if self.booked[(court, t)] == "_buffer_break":
                        overridden.append((court, t))
                    else:
                        return False, []

        return bool(overridden), overridden  # only True if there were buffers to override


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
        # Potential player history: tracks all possible players for configured
        # rounds, used for overlap-only checks (no rest requirement)
        # player_name -> list of (start_minute, end_minute, match_id)
        self.potential_history = defaultdict(list)
        self.density_cfg = get_match_density(config)

    def can_play_at(self, players, start_minute, duration, new_div_code, new_category):
        """Check if all players can play a match at the given time.

        Verifies rest constraints in both directions and match density limits.
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

            # Match density check: max X matches within Y minutes
            if not self._check_density(p, start_minute, new_end):
                return False
        return True

    def can_play_at_relaxed(self, players, start_minute, duration, new_div_code, new_category):
        """Relaxed check: only enforce same-division rest and no-overlap.

        Cross-division rest is NOT enforced — only time overlap is prevented.
        Used as a fallback when normal scheduling fails.
        """
        if not players:
            return True
        new_end = start_minute + duration
        for p in players:
            for prev_start, prev_end, prev_div, prev_cat in self.history[p]:
                same_div = (prev_div == new_div_code)
                if same_div:
                    # Same division: enforce full rest
                    rest = compute_rest_between(
                        self.config, prev_div, prev_cat, new_div_code, new_category,
                        player_name=p,
                    )
                else:
                    # Cross division: only prevent overlap (rest = 0)
                    rest = 0

                if prev_end <= start_minute:
                    if rest > 0 and prev_end + rest > start_minute:
                        return False
                elif new_end <= prev_start:
                    if rest > 0 and new_end + rest > prev_start:
                        return False
                else:
                    # Overlapping — never allowed
                    return False

            if not self._check_density(p, start_minute, new_end):
                return False
        return True

    def _check_density(self, player, new_start, new_end):
        """Check match density limit for a player.

        Returns True if adding a match at [new_start, new_end) doesn't
        violate the max-matches-per-window constraint.
        """
        max_matches = self.density_cfg["max_matches"]
        if max_matches <= 0:
            return True  # disabled

        time_window = self.density_cfg["time_window"]

        # Per-player exception
        player_exc = self.density_cfg["player_exceptions"].get(player)
        if player_exc:
            max_matches = player_exc.get("max_matches", max_matches)
            time_window = player_exc.get("time_window", time_window)
            if max_matches <= 0:
                return True

        # Count matches (including this new one) that overlap with a sliding
        # window. The tightest window is one that includes the new match.
        # Check: in the window [new_start - time_window, new_end + time_window],
        # how many matches fall within any time_window-sized sub-window?
        # Simplified: count matches whose start is within [new_start - time_window, new_end]
        # (any match starting within time_window before this match ends could
        # be in the same window).
        count = 1  # the new match itself
        for prev_start, prev_end, _, _ in self.history[player]:
            # Check if this match and the new match could be in the same window
            if abs(prev_start - new_start) < time_window:
                count += 1
        return count <= max_matches

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

    def update_potential(self, players, match_start, duration, match_id,
                         category=None, div_code=None):
        """Record potential players for overlap and rest tracking."""
        end_min = match_start + duration
        for p in players:
            self.potential_history[p].append(
                (match_start, end_min, match_id, category, div_code)
            )

    def check_potential_overlap(self, players, start_minute, duration,
                                category=None, div_code=None, scope="all"):
        """Check potential player conflicts with rest enforcement.

        Enforces compute_rest_between() for all pairs (same logic as
        can_play_at for confirmed players), ensuring cross_division_rest
        is respected for potential players too.

        scope="all": check across ALL categories (from default config).
        scope="same_category": only check within same category (from
          category-specific config). Cross-category is ignored entirely.

        Returns (ok, conflict_detail) where ok=True means no conflict.
        """
        new_end = start_minute + duration
        for p in players:
            for prev_start, prev_end, prev_match_id, prev_cat, prev_div in self.potential_history[p]:
                diff_cat = (category and prev_cat and category != prev_cat)

                if scope == "same_category" and diff_cat:
                    continue  # Category-specific: ignore cross-category

                # Enforce rest for all pairs (cross_division_rest as minimum)
                rest = compute_rest_between(
                    self.config,
                    prev_div or "", prev_cat or "",
                    div_code or "", category or "",
                    player_name=p,
                )
                if prev_end <= start_minute:
                    if prev_end + rest > start_minute:
                        return False, (
                            f"{p} needs {rest}min rest after {prev_match_id} "
                            f"(ends +{prev_end - start_minute + rest}min short)"
                        )
                elif new_end <= prev_start:
                    if new_end + rest > prev_start:
                        return False, (
                            f"{p} too close before {prev_match_id}"
                        )
                else:
                    return False, f"{p} potential overlap with {prev_match_id}"
        return True, ""

    def check_potential_overlap_relaxed(self, players, start_minute, duration,
                                        category=None, div_code=None):
        """Fallback: same-category rest + cross-category overlap prevention.

        Relaxes cross-category rest to overlap-only, but still prevents
        actual time overlaps across all categories. Same-category pairs
        still get full rest enforcement via compute_rest_between().
        """
        new_end = start_minute + duration
        for p in players:
            for prev_start, prev_end, prev_match_id, prev_cat, prev_div in self.potential_history[p]:
                same_cat = (category and prev_cat and category == prev_cat)

                if same_cat:
                    # Same category: enforce rest
                    rest = compute_rest_between(
                        self.config,
                        prev_div or "", prev_cat or "",
                        div_code or "", category or "",
                        player_name=p,
                    )
                else:
                    # Cross-category: overlap prevention only
                    rest = 0

                if prev_end <= start_minute:
                    if rest > 0 and prev_end + rest > start_minute:
                        return False, (
                            f"{p} needs {rest}min rest after {prev_match_id}"
                        )
                elif new_end <= prev_start:
                    if rest > 0 and new_end + rest > prev_start:
                        return False, (
                            f"{p} too close before {prev_match_id}"
                        )
                else:
                    return False, f"{p} potential overlap with {prev_match_id}"
        return True, ""


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
    pref = get_court_preference(config, category, day_name=day_name,
                                round_name=match.round_name)

    # Per-round court preference override (e.g., Finals on courts 5-8).
    # Only applies when category doesn't have required_courts (which is a
    # hard constraint, e.g., Junior on Saturday must use courts 9-12).
    bare_round = match.round_name.replace("Playoff ", "") if match.round_name.startswith("Playoff ") else match.round_name
    round_prefs = config["court_preferences"].get("round_court_preferences", {})
    if bare_round in round_prefs and not pref.get("required_courts"):
        pref = dict(pref)  # copy to avoid mutating cached config
        rp = round_prefs[bare_round]
        for key in ("preferred_courts", "fallback_courts", "last_resort_courts"):
            if key in rp:
                pref[key] = rp[key]

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

def _get_same_day_key(match, config=None):
    """Return the grouping key for same-day enforcement.

    All matches sharing a key must be scheduled on the same day.

    When pool_round_same_day is enabled for this match's category,
    each pool round (R1, R2, R3) gets a separate same-day key.
    Otherwise, all pool matches share one key (legacy behavior).

    For group+playoff divisions, all group pools share one key per round.
    """
    div_code = match.division_code
    round_name = match.round_name

    if "Pool" in round_name:
        use_pool_round = False
        if config is not None:
            use_pool_round = get_pool_round_same_day(
                config, match.category, match.division_code
            )

        if use_pool_round:
            pr_label = f"R{match.pool_round + 1}"
            if " Pool" in round_name and round_name != "Pool":
                return (div_code, "Group Pool", pr_label)
            return (div_code, "Pool", pr_label)
        else:
            if " Pool" in round_name and round_name != "Pool":
                return (div_code, "Group Pool")
            return (div_code, round_name)

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


def _fmt_minute(venue_model, minute):
    """Format a minute offset as 'Day HH:MM' for trace logging."""
    day, time = config_minute_to_display(venue_model, minute)
    return f"{day} {time}"


def _player_conflict_detail(player_tracker, match, slot):
    """Get a human-readable description of which player(s) cause a conflict."""
    duration = match.duration_min
    new_end = slot + duration
    conflicts = []
    for p in match.effective_players:
        for prev_start, prev_end, prev_div, prev_cat in player_tracker.history[p]:
            rest = compute_rest_between(
                player_tracker.config, prev_div, prev_cat,
                match.division_code, match.category, player_name=p,
            )
            if prev_end <= slot:
                if prev_end + rest > slot:
                    conflicts.append(
                        f"{p} needs {rest}min rest after {prev_div} "
                        f"(ends {_fmt_minute(player_tracker.config.get('_venue_model', {}), prev_end) if False else prev_end})"
                    )
                    break
            elif new_end <= prev_start:
                if new_end + rest > prev_start:
                    conflicts.append(f"{p} has {prev_div} starting too soon after")
                    break
            else:
                conflicts.append(f"{p} overlaps with {prev_div}")
                break
        # Also check density
        if not player_tracker._check_density(p, slot, new_end):
            density = player_tracker.density_cfg
            p_exc = density["player_exceptions"].get(p)
            p_max = p_exc.get("max_matches", density["max_matches"]) if p_exc else density["max_matches"]
            p_window = p_exc.get("time_window", density["time_window"]) if p_exc else density["time_window"]
            conflicts.append(
                f"{p} exceeds {p_max} matches in {p_window}min"
            )
    return "; ".join(conflicts) if conflicts else "unknown"


def _should_check_potential_conflicts(match, pca_config):
    """Check if this match's round is configured for potential conflict avoidance.

    Returns (should_check, scope) where scope is:
      "all" — from default config, check across all categories
      "same_category" — from category-specific config, check within category only
      None — not configured
    """
    if not pca_config:
        return False, None
    category = match.category
    round_name = match.round_name
    bare_round = round_name.replace("Playoff ", "") if round_name.startswith("Playoff ") else round_name

    # Check category-specific config first
    if category in pca_config:
        if bare_round in pca_config[category]:
            return True, "same_category"

    # Fall back to default (applies across all categories)
    default_rounds = pca_config.get("_default", set())
    if bare_round in default_rounds:
        return True, "all"

    return False, None


def _parse_deadline(deadline_str, venue_model):
    """Parse 'Day HH:MM' to a minute offset. Returns None if invalid."""
    parts = deadline_str.split(" ", 1)
    if len(parts) != 2:
        return None
    day_name, time_str = parts
    day_start = venue_model["day_start_minutes"].get(day_name)
    if day_start is None:
        return None
    # Find the day's start_time to compute offset
    for day in venue_model["days"]:
        if day["name"] == day_name:
            start_h, start_m = map(int, day["start_time"].split(":"))
            dl_h, dl_m = map(int, time_str.split(":"))
            offset = (dl_h - start_h) * 60 + (dl_m - start_m)
            return day_start + offset
    return None


def _build_time_deadline_map(config, venue_model):
    """Build (div_code, round_name) -> deadline_minute map from config.

    Global deadlines (no divisions list) apply to all divisions.
    """
    deadlines = get_time_deadlines(config)
    result = {}  # (div_code, round_name) -> deadline minute
    for dl in deadlines:
        minute = _parse_deadline(dl.get("deadline", ""), venue_model)
        if minute is None:
            continue
        rounds = dl.get("rounds", [])
        divisions = dl.get("divisions")  # None means all divisions
        for rnd in rounds:
            if divisions:
                for div in divisions:
                    result[(div, rnd)] = minute
            else:
                # Sentinel: store with None div_code for "all divisions"
                result[(None, rnd)] = minute
    return result


def _build_earliest_start_map(config, venue_model):
    """Build (div_code, round_name) -> earliest_minute map from config.

    Matches in specified rounds won't be scheduled before this time.
    """
    entries = get_earliest_start(config)
    result = {}
    for entry in entries:
        minute = _parse_deadline(entry.get("time", ""), venue_model)
        if minute is None:
            continue
        rounds = entry.get("rounds", [])
        divisions = entry.get("divisions")
        for rnd in rounds:
            if divisions:
                for div in divisions:
                    result[(div, rnd)] = minute
            else:
                result[(None, rnd)] = minute
    return result


def _schedule_sf_pair(pair, earliest_base, latest_base, day_constraint,
                      all_slots, slot_duration, config, venue_model,
                      court_sched, player_tracker, pca_config,
                      scheduled, scheduled_end, sf_already_placed,
                      unschedulable, unscheduled, sched_trace,
                      round_day_assignments, same_day_key,
                      day_start_minutes, day_end_minutes,
                      min_prereq_rest, deadline_map, earliest_start_map,
                      rc_enabled, rc_exceptions, div_round_matches):
    """Schedule both SF matches of a division at the same time slot.

    Finds a slot where two courts are available and both matches' player
    constraints are satisfied.
    """
    m1, m2 = pair

    # Compute earliest for each match from prerequisites
    earliest = earliest_base
    for m in pair:
        for prereq_id in m.prerequisites:
            if prereq_id in scheduled_end:
                earliest = max(earliest, scheduled_end[prereq_id] + min_prereq_rest)

    # Round-completion constraint
    if rc_enabled and m1.division_code not in (rc_exceptions or set()):
        prev_round = _get_previous_round(
            m1.division_code, m1.round_name, div_round_matches
        )
        if prev_round:
            prev_ids = div_round_matches[(m1.division_code, prev_round)]
            if any(mid in unschedulable for mid in prev_ids):
                for m in pair:
                    unschedulable.add(m.id)
                    unscheduled.append(m)
                    sched_trace.append({
                        "match_id": m.id, "status": "UNSCHEDULED",
                        "reason": f"previous round incomplete (SF pair)",
                    })
                return True  # handled
            if prev_ids:
                latest_prev = max(scheduled_end.get(mid, 0) for mid in prev_ids)
                earliest = max(earliest, latest_prev)

    # Day constraint
    latest = latest_base
    effective_day = day_constraint or m1.day_constraint
    sdkey = _get_same_day_key(m1, config)
    if sdkey in round_day_assignments:
        assigned_day = round_day_assignments[sdkey]
        ds = day_start_minutes.get(assigned_day, 0)
        de = day_end_minutes.get(assigned_day, ds + 24 * 60)
        earliest = max(earliest, ds)
        latest = de
    elif effective_day:
        ds = day_start_minutes.get(effective_day, 0)
        de = day_end_minutes.get(effective_day, ds + 24 * 60)
        earliest = max(earliest, ds)
        latest = de

    # Time deadline
    for m in pair:
        dl = deadline_map.get((m.division_code, m.round_name))
        if dl is None:
            dl = deadline_map.get((None, m.round_name))
        if dl is not None:
            dl_latest = dl - m.duration_min
            latest = min(latest, dl_latest) if latest else dl_latest

    # Earliest start time
    for m in pair:
        es = earliest_start_map.get((m.division_code, m.round_name))
        if es is None:
            es = earliest_start_map.get((None, m.round_name))
        if es is not None:
            earliest = max(earliest, es)

    # Ensure the Final can fit after the SF: tighten latest
    # SF end + same-division rest + Final duration must be before day end
    # So SF must start before: day_end - SF_duration - rest - Final_duration
    from config import get_same_division_rest
    sd_rest = get_same_division_rest(config, m1.division_code)
    final_duration = m1.duration_min  # assume same duration as SF
    if latest is not None:
        sf_latest = latest - m1.duration_min - sd_rest - final_duration
        latest = min(latest, sf_latest)

    # Snap earliest
    if earliest % slot_duration != 0:
        earliest = ((earliest // slot_duration) + 1) * slot_duration

    # Search for a slot with 2 available courts
    placed = False
    for slot in all_slots:
        if slot < earliest:
            continue
        if latest is not None and slot >= latest:
            break

        courts = get_eligible_courts(m1, slot, config, venue_model)
        available_courts = []
        for court in courts:
            if court_sched.can_book(court, slot, m1.duration_min, m1.overrun_buffer):
                available_courts.append(court)

        if len(available_courts) < 2:
            # Try with buffer override
            for court in courts:
                if court in available_courts:
                    continue
                can_ovr, _ = court_sched.can_book_override_buffer(
                    court, slot, m1.duration_min, m1.overrun_buffer
                )
                if can_ovr:
                    available_courts.append(court)
                if len(available_courts) >= 2:
                    break

        if len(available_courts) < 2:
            continue

        # Try all 2-court combinations for the pair
        from itertools import combinations
        for c1, c2 in combinations(available_courts, 2):
            # Check player constraints for both matches
            ok1 = True
            if m1.effective_players:
                if not player_tracker.can_play_at(
                    m1.effective_players, slot, m1.duration_min,
                    m1.division_code, m1.category
                ):
                    ok1 = False
                if ok1 and player_tracker.potential_history:
                    _, sf_scope = _should_check_potential_conflicts(m1, pca_config)
                    if sf_scope:
                        ok_p, _ = player_tracker.check_potential_overlap(
                            m1.effective_players, slot, m1.duration_min,
                            category=m1.category, div_code=m1.division_code,
                            scope=sf_scope,
                        )
                        if not ok_p:
                            ok1 = False
            if not ok1:
                continue

            ok2 = True
            if m2.effective_players:
                if not player_tracker.can_play_at(
                    m2.effective_players, slot, m2.duration_min,
                    m2.division_code, m2.category
                ):
                    ok2 = False
                if ok2 and player_tracker.potential_history:
                    _, sf_scope2 = _should_check_potential_conflicts(m2, pca_config)
                    if sf_scope2:
                        ok_p, _ = player_tracker.check_potential_overlap(
                            m2.effective_players, slot, m2.duration_min,
                            category=m2.category, div_code=m2.division_code,
                            scope=sf_scope2,
                        )
                    if not ok_p:
                        ok2 = False
            if not ok2:
                continue

            # Book both matches
            for m, court in [(m1, c1), (m2, c2)]:
                # Override buffer if needed
                if not court_sched.can_book(court, slot, m.duration_min, m.overrun_buffer):
                    _, overridden = court_sched.can_book_override_buffer(
                        court, slot, m.duration_min, m.overrun_buffer
                    )
                    for bc, bm in overridden:
                        del court_sched.booked[(bc, bm)]

                court_sched.book(court, slot, m.id, m.duration_min, m.overrun_buffer)

                if m.has_some_real_players:
                    confirmed = set()
                    for p_str in (m.player1, m.player2):
                        if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                            confirmed.update(extract_player_names(p_str))
                    if confirmed:
                        player_tracker.update(
                            list(confirmed), slot,
                            m.duration_min, m.division_code, m.category
                        )

                check_potential, pca_scope = _should_check_potential_conflicts(m, pca_config)
                if check_potential and m.effective_players:
                    player_tracker.update_potential(
                        m.effective_players, slot, m.duration_min, m.id,
                        category=m.category, div_code=m.division_code,
                    )

                scheduled[m.id] = (court, slot)
                scheduled_end[m.id] = slot + m.duration_min
                sf_already_placed.add(m.id)

                sched_trace.append({
                    "match_id": m.id,
                    "status": "SCHEDULED",
                    "priority": m.priority,
                    "placed": _fmt_minute(venue_model, slot),
                    "court": court,
                    "player1": m.player1,
                    "player2": m.player2,
                    "players": m.effective_players,
                    "note": "SF pair scheduling",
                })

            # Record same-day
            if sdkey not in round_day_assignments:
                round_day_assignments[sdkey] = _day_name_for_minute(venue_model, slot)

            placed = True
            break
        if placed:
            break

    # Fallback: retry with relaxed cross-division rest
    if not placed:
        for slot in all_slots:
            if slot < earliest:
                continue
            if latest is not None and slot >= latest:
                break

            courts = get_eligible_courts(m1, slot, config, venue_model)
            available_courts = []
            for court in courts:
                if court_sched.can_book(court, slot, m1.duration_min, m1.overrun_buffer):
                    available_courts.append(court)
            if len(available_courts) < 2:
                for court in courts:
                    if court in available_courts:
                        continue
                    can_ovr, _ = court_sched.can_book_override_buffer(
                        court, slot, m1.duration_min, m1.overrun_buffer
                    )
                    if can_ovr:
                        available_courts.append(court)
                    if len(available_courts) >= 2:
                        break
            if len(available_courts) < 2:
                continue

            from itertools import combinations as combs2
            for c1, c2 in combs2(available_courts, 2):
                ok1 = not m1.effective_players or player_tracker.can_play_at_relaxed(
                    m1.effective_players, slot, m1.duration_min,
                    m1.division_code, m1.category
                )
                if not ok1:
                    continue
                ok2 = not m2.effective_players or player_tracker.can_play_at_relaxed(
                    m2.effective_players, slot, m2.duration_min,
                    m2.division_code, m2.category
                )
                if not ok2:
                    continue

                # Book both
                for m, court in [(m1, c1), (m2, c2)]:
                    if not court_sched.can_book(court, slot, m.duration_min, m.overrun_buffer):
                        _, ovr = court_sched.can_book_override_buffer(
                            court, slot, m.duration_min, m.overrun_buffer
                        )
                        for bc, bm in ovr:
                            del court_sched.booked[(bc, bm)]
                    court_sched.book(court, slot, m.id, m.duration_min, m.overrun_buffer)
                    if m.has_some_real_players:
                        confirmed = set()
                        for p_str in (m.player1, m.player2):
                            if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                                confirmed.update(extract_player_names(p_str))
                        if confirmed:
                            player_tracker.update(
                                list(confirmed), slot,
                                m.duration_min, m.division_code, m.category
                            )
                    check_potential, pca_scope = _should_check_potential_conflicts(m, pca_config)
                    if check_potential and m.effective_players:
                        player_tracker.update_potential(
                            m.effective_players, slot, m.duration_min, m.id,
                            category=m.category, div_code=m.division_code,
                        )
                    scheduled[m.id] = (court, slot)
                    scheduled_end[m.id] = slot + m.duration_min
                    sf_already_placed.add(m.id)
                    sched_trace.append({
                        "match_id": m.id, "status": "SCHEDULED",
                        "priority": m.priority,
                        "placed": _fmt_minute(venue_model, slot), "court": court,
                        "player1": m.player1, "player2": m.player2,
                        "players": m.effective_players,
                        "warning": "SF pair: cross-division rest relaxed",
                    })
                if sdkey not in round_day_assignments:
                    round_day_assignments[sdkey] = _day_name_for_minute(venue_model, slot)
                placed = True
                break
            if placed:
                break

    if not placed:
        for m in pair:
            unschedulable.add(m.id)
            unscheduled.append(m)
            sched_trace.append({
                "match_id": m.id,
                "status": "UNSCHEDULED",
                "priority": m.priority,
                "reason": "SF pair: no slot with 2 available courts meeting all constraints",
                "constraints": [
                    f"earliest={_fmt_minute(venue_model, earliest)}",
                    f"latest={_fmt_minute(venue_model, latest)}" if latest else None,
                ],
                "player1": m.player1,
                "player2": m.player2,
                "players": m.effective_players,
            })

    return True  # handled (whether placed or not)


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

    # Time deadlines: (div_code, round_name) -> deadline minute
    deadline_map = _build_time_deadline_map(config, venue_model)

    # Earliest start times: (div_code, round_name) -> earliest minute
    earliest_start_map = _build_earliest_start_map(config, venue_model)

    # Match density limits
    density_cfg = get_match_density(config)

    # Potential conflict avoidance config
    pca_config = get_potential_conflict_avoidance(config)

    # Pool time limit: track earliest start per pool group
    # Key: (div_code, pool_key) -> earliest_start_minute
    round_first_start = {}  # populated when first pool match of a group is placed

    # Scheduling trace log — records why each match was placed or rejected
    sched_trace = []

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

    # Pool round completion: register per-pool-round entries when pool_round_same_day
    # is enabled, so R1 must finish before R2 starts, etc.
    pool_round_completion = set()  # set of div_codes with pool round completion
    for m in matches:
        if "Pool" not in m.round_name:
            continue
        if get_pool_round_same_day(config, m.category, m.division_code):
            pool_round_completion.add(m.division_code)
            pool_round_key = f"{m.round_name}:R{m.pool_round + 1}"
            div_round_matches[(m.division_code, pool_round_key)].append(m.id)

    all_slots = venue_model["all_slots"]
    slot_duration = venue_model["slot_duration"]
    day_start_minutes = venue_model["day_start_minutes"]

    # Build day_end_minutes for same-day enforcement
    day_end_minutes = {}
    for day in venue_model["days"]:
        day_end_minutes[day["name"]] = day["end_minute"]

    # Semi-final same-time enforcement: both SF matches of a division
    # are scheduled together as a pair (when enabled in config).
    sf_same_time_enabled = config["scheduling"].get("semi_final_same_time", False)
    # Build SF pairs: (div_code, round_name) -> [match, match]
    sf_pairs = {}
    sf_already_placed = set()  # match IDs already placed as part of a pair
    if sf_same_time_enabled:
        for m in matches:
            bare = m.round_name.replace("Playoff ", "") if m.round_name.startswith("Playoff ") else m.round_name
            if bare == "Semi-Final":
                key = (m.division_code, m.round_name)
                if key not in sf_pairs:
                    sf_pairs[key] = []
                sf_pairs[key].append(m)

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
            sched_trace.append({
                "match_id": match.id, "status": "UNSCHEDULED",
                "reason": f"prerequisite failed: {prereq_id}",
            })
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
                    failed_ids = [mid for mid in prev_match_ids if mid in unschedulable]
                    unschedulable.add(match.id)
                    unscheduled.append(match)
                    sched_trace.append({
                        "match_id": match.id, "status": "UNSCHEDULED",
                        "reason": f"previous round incomplete: {prev_round} has unscheduled {failed_ids}",
                    })
                    continue
                # All previous-round matches should be scheduled by now
                # (they have lower priority). Use latest end time as earliest start.
                if prev_match_ids:
                    latest_prev_end = max(
                        scheduled_end.get(mid, 0) for mid in prev_match_ids
                    )
                    earliest = max(earliest, latest_prev_end)

        # Pool round completion: previous pool round must finish before this one starts
        if "Pool" in match.round_name and match.division_code in pool_round_completion:
            if match.pool_round > 0:
                prev_pr_key = f"{match.round_name}:R{match.pool_round}"  # previous round (1-based)
                prev_pr_ids = div_round_matches.get((match.division_code, prev_pr_key), [])
                if prev_pr_ids:
                    prev_pr_failed = any(mid in unschedulable for mid in prev_pr_ids)
                    if prev_pr_failed:
                        failed_ids = [mid for mid in prev_pr_ids if mid in unschedulable]
                        unschedulable.add(match.id)
                        unscheduled.append(match)
                        sched_trace.append({
                            "match_id": match.id, "status": "UNSCHEDULED",
                            "reason": f"previous pool round incomplete: R{match.pool_round} has unscheduled {failed_ids}",
                        })
                        continue
                    latest_prev_pr = max(
                        scheduled_end.get(mid, 0) for mid in prev_pr_ids
                    )
                    earliest = max(earliest, latest_prev_pr)

        # Day constraint from config (e.g. SF/Final must be on Sunday)
        effective_day = match.day_constraint

        # Same-day enforcement: if another match in this round+division
        # was already placed on a day, this match must go on that same day
        same_day_key = _get_same_day_key(match, config)
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

        # Time deadline: match must finish by this minute
        deadline = deadline_map.get((match.division_code, match.round_name))
        if deadline is None:
            deadline = deadline_map.get((None, match.round_name))  # global
        if deadline is not None:
            # Match must start early enough to finish by deadline
            dl_latest = deadline - match.duration_min
            if latest is None:
                latest = dl_latest
            else:
                latest = min(latest, dl_latest)

        # Earliest start time: match must not start before this minute
        es = earliest_start_map.get((match.division_code, match.round_name))
        if es is None:
            es = earliest_start_map.get((None, match.round_name))  # global
        if es is not None:
            earliest = max(earliest, es)

        # Round time limit: match must finish within time_limit of the round's first match
        # Soft limits can be relaxed in fallback; hard limits are never relaxed
        # Use per-group key for pool rounds (not merged across groups)
        round_time_limited = False
        round_time_hard = False
        latest_without_rtl = latest  # save the latest before round limit
        rtl_key = (match.division_code, match.round_name)
        rtl_result = get_round_time_limit(config, match.round_name, match.category, match.division_code)
        if rtl_result is not None:
            rtl, rtl_is_hard = rtl_result
            if rtl_key in round_first_start:
                rtl_deadline = round_first_start[rtl_key] + rtl
                rtl_latest = rtl_deadline - match.duration_min
                if latest is None:
                    latest = rtl_latest
                else:
                    latest = min(latest, rtl_latest)
                round_time_limited = True
                round_time_hard = rtl_is_hard

        # Snap to next slot boundary
        if earliest % slot_duration != 0:
            earliest = ((earliest // slot_duration) + 1) * slot_duration

        # Semi-final pair scheduling: skip if already placed as part of a pair
        bare_round = match.round_name.replace("Playoff ", "") if match.round_name.startswith("Playoff ") else match.round_name
        if match.id in sf_already_placed:
            continue

        # If this is a SF match in a pair, schedule both together
        if sf_same_time_enabled and bare_round == "Semi-Final":
            sf_key = (match.division_code, match.round_name)
            pair = sf_pairs.get(sf_key, [])
            if len(pair) == 2:
                placed = _schedule_sf_pair(
                    pair, earliest, latest, match.day_constraint,
                    all_slots, slot_duration, config, venue_model,
                    court_sched, player_tracker, pca_config,
                    scheduled, scheduled_end, sf_already_placed,
                    unschedulable, unscheduled, sched_trace,
                    round_day_assignments, same_day_key,
                    day_start_minutes, day_end_minutes,
                    min_prereq_rest, deadline_map, earliest_start_map,
                    rc_enabled, rc_exceptions, div_round_matches,
                )
                continue  # pair handler deals with both matches

        # Collect trace info for this match
        trace_constraints = []
        if earliest > 0:
            trace_constraints.append(f"earliest={_fmt_minute(venue_model, earliest)}")
        if latest is not None:
            trace_constraints.append(f"latest={_fmt_minute(venue_model, latest)}")
        if match.day_constraint:
            trace_constraints.append(f"day={match.day_constraint}")

        # Find available slot
        placed = False
        # Trace: collect per-slot rejection info (all slots, not just last N)
        # court_busy_by_slot: minute -> list of busy courts
        # player_conflict_by_slot: minute -> (court, detail)
        trace_court_busy = {}     # minute -> [court, ...]
        trace_player_conflict = {}  # minute -> detail string
        trace_end_reason = None
        slots_tried = 0
        for slot in all_slots:
            if slot < earliest:
                continue
            # If same-day or day constraint limits the day, stop searching beyond it
            if latest is not None and slot >= latest:
                trace_end_reason = f"past latest bound {_fmt_minute(venue_model, latest)}"
                break

            courts = get_eligible_courts(match, slot, config, venue_model)
            slots_tried += 1
            slot_all_busy = True
            # For matches with round court preferences (e.g., Finals on 5-8),
            # try buffer override on preferred courts before accepting fallback
            has_round_pref = bare_round in config["court_preferences"].get("round_court_preferences", {})
            court_overrides = {}  # court -> overridden buffer slots
            for court in courts:
                if not court_sched.can_book(court, slot, match.duration_min, match.overrun_buffer):
                    # Only try inline buffer override for courts with round preferences
                    if has_round_pref:
                        can_ovr, ovr_slots = court_sched.can_book_override_buffer(
                            court, slot, match.duration_min, match.overrun_buffer
                        )
                        if can_ovr:
                            court_overrides[court] = ovr_slots
                    if court not in court_overrides:
                        if slot not in trace_court_busy:
                            trace_court_busy[slot] = []
                        trace_court_busy[slot].append(court)
                    continue

                slot_all_busy = False
                # Check player availability bidirectionally using effective_players
                # (filtered by probability threshold for placeholder matches)
                if match.effective_players:
                    if not player_tracker.can_play_at(
                        match.effective_players, slot, match.duration_min,
                        match.division_code, match.category
                    ):
                        trace_player_conflict[slot] = _player_conflict_detail(
                            player_tracker, match, slot
                        )
                        continue

                # Check potential player overlaps — always check against
                # potential_history (populated by configured rounds), so that
                # e.g. a Pool match won't overlap with a R2 match's potential players
                check_potential, pca_scope = _should_check_potential_conflicts(match, pca_config)
                if match.effective_players and player_tracker.potential_history:
                    ok, detail = player_tracker.check_potential_overlap(
                        match.effective_players, slot, match.duration_min,
                        category=match.category, div_code=match.division_code,
                        scope=pca_scope or "all",
                    )
                    if not ok:
                        trace_player_conflict[slot] = f"potential overlap: {detail}"
                        continue

                # Book it — blocks duration + overrun_buffer on the court
                court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)
                # Update tracker for confirmed players. For matches where
                # one side is a bye winner (confirmed) and the other is a
                # placeholder ("Winner R1-M5"), track the confirmed players
                # so they aren't double-booked across divisions.
                if match.has_some_real_players:
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

                # Update potential player history for configured rounds
                if check_potential and match.effective_players:
                    player_tracker.update_potential(
                        match.effective_players, slot,
                        match.duration_min, match.id,
                        category=match.category, div_code=match.division_code,
                    )

                # Record pool first start time
                rtl_key = (match.division_code, match.round_name)
                if rtl_key not in round_first_start:
                    round_first_start[rtl_key] = slot

                # Record same-day assignment for this round+division
                if same_day_key not in round_day_assignments:
                    placed_day = _day_name_for_minute(venue_model, slot)
                    round_day_assignments[same_day_key] = placed_day

                placed = True
                break

            # If no court was directly available but some preferred courts
            # could work with buffer override, try those before moving to next slot
            if not placed and court_overrides:
                for court, ovr_slots in court_overrides.items():
                    if match.effective_players:
                        if not player_tracker.can_play_at(
                            match.effective_players, slot, match.duration_min,
                            match.division_code, match.category
                        ):
                            break  # player blocked — no point trying other courts
                    if match.effective_players and player_tracker.potential_history:
                        ok, _ = player_tracker.check_potential_overlap(
                            match.effective_players, slot, match.duration_min,
                            category=match.category, div_code=match.division_code,
                        )
                        if not ok:
                            break

                    # Override buffers and book
                    for bc, bm in ovr_slots:
                        del court_sched.booked[(bc, bm)]
                    court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)

                    if match.has_some_real_players:
                        confirmed = set()
                        for p_str in (match.player1, match.player2):
                            if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                                confirmed.update(extract_player_names(p_str))
                        if confirmed:
                            player_tracker.update(
                                list(confirmed), slot,
                                match.duration_min, match.division_code, match.category
                            )
                    if check_potential and match.effective_players:
                        player_tracker.update_potential(
                            match.effective_players, slot, match.duration_min, match.id,
                            category=match.category,
                        )
                    scheduled[match.id] = (court, slot)
                    scheduled_end[match.id] = slot + match.duration_min
                    if "Pool" in match.round_name:
                        ptl_key = (match.division_code, match.round_name)
                        if ptl_key not in round_first_start:
                            round_first_start[ptl_key] = slot
                    if same_day_key not in round_day_assignments:
                        round_day_assignments[same_day_key] = _day_name_for_minute(venue_model, slot)
                    buffer_override_detail = [
                        _fmt_minute(venue_model, bm) + f" court {bc}"
                        for bc, bm in ovr_slots
                    ]
                    placed = True
                    break

            if placed:
                break

        # Fallback: retry with court buffer override if normal placement failed
        buffer_override_detail = None
        trace_buffer_busy = {}        # minute -> [court, ...]
        trace_buffer_player = {}      # minute -> detail string
        trace_buffer_end_reason = None
        if not placed:
            for slot in all_slots:
                if slot < earliest:
                    continue
                if latest is not None and slot >= latest:
                    trace_buffer_end_reason = f"past latest bound {_fmt_minute(venue_model, latest)}"
                    break

                courts = get_eligible_courts(match, slot, config, venue_model)
                for court in courts:
                    can_override, overridden = court_sched.can_book_override_buffer(
                        court, slot, match.duration_min, match.overrun_buffer
                    )
                    if not can_override:
                        if slot not in trace_buffer_busy:
                            trace_buffer_busy[slot] = []
                        trace_buffer_busy[slot].append(court)
                        continue

                    if match.effective_players:
                        if not player_tracker.can_play_at(
                            match.effective_players, slot, match.duration_min,
                            match.division_code, match.category
                        ):
                            trace_buffer_player[slot] = _player_conflict_detail(
                                player_tracker, match, slot
                            )
                            continue

                    # Check potential overlaps in buffer override pass too
                    if match.effective_players and player_tracker.potential_history:
                        ok, detail = player_tracker.check_potential_overlap(
                            match.effective_players, slot, match.duration_min,
                            category=match.category, div_code=match.division_code,
                        )
                        if not ok:
                            trace_buffer_player[slot] = f"potential overlap: {detail}"
                            continue

                    # Clear the buffer blocks and book
                    for bc, bm in overridden:
                        del court_sched.booked[(bc, bm)]
                    court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)

                    if match.has_some_real_players:
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

                    if check_potential and match.effective_players:
                        player_tracker.update_potential(
                            match.effective_players, slot,
                            match.duration_min, match.id,
                            category=match.category,
                        )

                    if "Pool" in match.round_name:
                        ptl_key = (match.division_code, match.round_name)
                        if ptl_key not in round_first_start:
                            round_first_start[ptl_key] = slot

                    if same_day_key not in round_day_assignments:
                        placed_day = _day_name_for_minute(venue_model, slot)
                        round_day_assignments[same_day_key] = placed_day

                    buffer_override_detail = [
                        _fmt_minute(venue_model, bm) + f" court {bc}"
                        for bc, bm in overridden
                    ]
                    placed = True
                    break
                if placed:
                    break

        # Fallback: if soft time limit was the blocker, retry without it
        # Hard limits are never relaxed — match stays unscheduled or uses later fallbacks
        round_limit_overridden = False
        if not placed and round_time_limited and not round_time_hard:
            # Retry the full scheduling (normal + buffer override) with relaxed latest
            relaxed_latest = latest_without_rtl
            for attempt_buffer in (False, True):
                for slot in all_slots:
                    if slot < earliest:
                        continue
                    if relaxed_latest is not None and slot >= relaxed_latest:
                        break

                    courts = get_eligible_courts(match, slot, config, venue_model)
                    for court in courts:
                        if attempt_buffer:
                            can_book, overridden = court_sched.can_book_override_buffer(
                                court, slot, match.duration_min, match.overrun_buffer
                            )
                            if not can_book:
                                continue
                        else:
                            if not court_sched.can_book(court, slot, match.duration_min, match.overrun_buffer):
                                continue
                            overridden = []

                        if match.effective_players:
                            if not player_tracker.can_play_at(
                                match.effective_players, slot, match.duration_min,
                                match.division_code, match.category
                            ):
                                continue
                        if match.effective_players and player_tracker.potential_history:
                            ok, _ = player_tracker.check_potential_overlap_relaxed(
                                match.effective_players, slot, match.duration_min,
                                category=match.category, div_code=match.division_code,
                            )
                            if not ok:
                                continue

                        # Clear buffers if needed
                        for bc, bm in overridden:
                            del court_sched.booked[(bc, bm)]
                        court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)

                        if match.has_some_real_players:
                            confirmed = set()
                            for p_str in (match.player1, match.player2):
                                if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                                    confirmed.update(extract_player_names(p_str))
                            if confirmed:
                                player_tracker.update(
                                    list(confirmed), slot,
                                    match.duration_min, match.division_code, match.category
                                )
                        check_potential, pca_scope = _should_check_potential_conflicts(match, pca_config)
                        if check_potential and match.effective_players:
                            player_tracker.update_potential(
                                match.effective_players, slot, match.duration_min, match.id,
                                category=match.category,
                            )
                        scheduled[match.id] = (court, slot)
                        scheduled_end[match.id] = slot + match.duration_min

                        rfs_key = (match.division_code, match.round_name)
                        if rfs_key not in round_first_start:
                            round_first_start[rfs_key] = slot

                        if same_day_key not in round_day_assignments:
                            round_day_assignments[same_day_key] = _day_name_for_minute(venue_model, slot)

                        round_limit_overridden = True
                        if overridden:
                            buffer_override_detail = [
                                _fmt_minute(venue_model, bm) + f" court {bc}"
                                for bc, bm in overridden
                            ]
                        placed = True
                        break
                    if placed:
                        break
                if placed:
                    break

        # Fallback: relax cross-division rest (only enforce same-division rest + no overlap)
        # For hard time limits, keep the limit enforced (use latest, not latest_without_rtl)
        cross_div_rest_relaxed = False
        cross_div_latest = latest if round_time_hard else latest_without_rtl
        if not placed:
            for attempt_buffer in (False, True):
                for slot in all_slots:
                    if slot < earliest:
                        continue
                    if cross_div_latest is not None and slot >= cross_div_latest:
                        break

                    courts = get_eligible_courts(match, slot, config, venue_model)
                    for court in courts:
                        if attempt_buffer:
                            can_bk, overridden = court_sched.can_book_override_buffer(
                                court, slot, match.duration_min, match.overrun_buffer
                            )
                            if not can_bk:
                                continue
                        else:
                            if not court_sched.can_book(court, slot, match.duration_min, match.overrun_buffer):
                                continue
                            overridden = []

                        if match.effective_players:
                            if not player_tracker.can_play_at_relaxed(
                                match.effective_players, slot, match.duration_min,
                                match.division_code, match.category
                            ):
                                continue
                        # Last resort: skip potential overlap check entirely.
                        # Confirmed rest is already relaxed; potential conflicts
                        # will be reported by the verifier.

                        # Book it
                        for bc, bm in overridden:
                            del court_sched.booked[(bc, bm)]
                        court_sched.book(court, slot, match.id, match.duration_min, match.overrun_buffer)

                        if match.has_some_real_players:
                            confirmed = set()
                            for p_str in (match.player1, match.player2):
                                if not p_str.startswith("Winner ") and not p_str.startswith("Slot "):
                                    confirmed.update(extract_player_names(p_str))
                            if confirmed:
                                player_tracker.update(
                                    list(confirmed), slot,
                                    match.duration_min, match.division_code, match.category
                                )
                        check_potential, pca_scope = _should_check_potential_conflicts(match, pca_config)
                        if check_potential and match.effective_players:
                            player_tracker.update_potential(
                                match.effective_players, slot, match.duration_min, match.id,
                                category=match.category, div_code=match.division_code,
                            )
                        scheduled[match.id] = (court, slot)
                        scheduled_end[match.id] = slot + match.duration_min
                        rtl_key = (match.division_code, match.round_name)
                        if rtl_key not in round_first_start:
                            round_first_start[rtl_key] = slot
                        if same_day_key not in round_day_assignments:
                            round_day_assignments[same_day_key] = _day_name_for_minute(venue_model, slot)

                        cross_div_rest_relaxed = True
                        if overridden:
                            buffer_override_detail = [
                                _fmt_minute(venue_model, bm) + f" court {bc}"
                                for bc, bm in overridden
                            ]
                        placed = True
                        break
                    if placed:
                        break
                if placed:
                    break

        if not placed:
            unschedulable.add(match.id)
            unscheduled.append(match)

            # Build aggregated rejection trace
            rejections = []

            # Normal pass: aggregate court-busy by time slot
            for minute in sorted(trace_court_busy):
                busy_courts = trace_court_busy[minute]
                eligible = get_eligible_courts(match, minute, config, venue_model)
                entry = {
                    "slot": _fmt_minute(venue_model, minute),
                    "busy_courts": busy_courts,
                }
                if minute in trace_player_conflict:
                    entry["player_conflict"] = trace_player_conflict[minute]
                    entry["free_courts"] = [c for c in eligible if c not in busy_courts]
                elif len(busy_courts) >= len(eligible):
                    entry["reason"] = "all courts busy"
                else:
                    entry["free_courts"] = [c for c in eligible if c not in busy_courts]
                    entry["reason"] = "free courts had player conflicts"
                    if minute in trace_player_conflict:
                        entry["player_conflict"] = trace_player_conflict[minute]
                rejections.append(entry)

            # Slots with only player conflicts (court was free but player blocked)
            for minute in sorted(trace_player_conflict):
                if minute not in trace_court_busy:
                    rejections.append({
                        "slot": _fmt_minute(venue_model, minute),
                        "reason": "player conflict",
                        "player_conflict": trace_player_conflict[minute],
                    })

            if trace_end_reason:
                rejections.append({"reason": trace_end_reason})

            # Buffer override pass
            buffer_rejections = []
            for minute in sorted(trace_buffer_busy):
                eligible = get_eligible_courts(match, minute, config, venue_model)
                busy_courts = trace_buffer_busy[minute]
                entry = {
                    "slot": _fmt_minute(venue_model, minute),
                    "busy_courts": busy_courts,
                }
                if minute in trace_buffer_player:
                    entry["player_conflict"] = trace_buffer_player[minute]
                    entry["free_courts"] = [c for c in eligible if c not in busy_courts]
                elif len(busy_courts) >= len(eligible):
                    entry["reason"] = "all courts busy (even with buffer override)"
                else:
                    entry["free_courts"] = [c for c in eligible if c not in busy_courts]
                    if minute in trace_buffer_player:
                        entry["player_conflict"] = trace_buffer_player[minute]
                buffer_rejections.append(entry)

            for minute in sorted(trace_buffer_player):
                if minute not in trace_buffer_busy:
                    buffer_rejections.append({
                        "slot": _fmt_minute(venue_model, minute),
                        "reason": "player conflict (buffer override pass)",
                        "player_conflict": trace_buffer_player[minute],
                    })

            if trace_buffer_end_reason:
                buffer_rejections.append({"reason": trace_buffer_end_reason})

            sched_trace.append({
                "match_id": match.id,
                "status": "UNSCHEDULED",
                "priority": match.priority,
                "constraints": trace_constraints,
                "player1": match.player1,
                "player2": match.player2,
                "players": match.effective_players,
                "slots_tried": slots_tried,
                "rejections": rejections,
                "buffer_override_rejections": buffer_rejections if buffer_rejections else None,
            })
        else:
            court, minute = scheduled[match.id]
            trace_entry = {
                "match_id": match.id,
                "status": "SCHEDULED",
                "priority": match.priority,
                "placed": _fmt_minute(venue_model, minute),
                "court": court,
                "player1": match.player1,
                "player2": match.player2,
                "players": match.effective_players,
            }
            if "Pool" in match.round_name:
                trace_entry["pool_round"] = match.pool_round + 1  # display as 1-based
            warnings_list = []
            if buffer_override_detail:
                warnings_list.append("court buffer overridden")
                trace_entry["buffer_slots_overridden"] = buffer_override_detail
            if round_limit_overridden:
                warnings_list.append("round time limit exceeded")
            if cross_div_rest_relaxed:
                warnings_list.append("cross-division rest relaxed")
            if warnings_list:
                trace_entry["warning"] = "; ".join(warnings_list)
            sched_trace.append(trace_entry)

    # Write scheduling trace log
    trace_path = os.path.join(config["paths"]["schedules_dir"], "scheduling_trace.json")
    os.makedirs(config["paths"]["schedules_dir"], exist_ok=True)
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(sched_trace, f, indent=2, ensure_ascii=False)

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
        key = _get_same_day_key(match, config)
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
        if "Pool" in match.round_name:
            rec["pool_round"] = match.pool_round + 1  # display as 1-based
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

    # Per-division schedule files
    div_dir = os.path.join(schedules_dir, "divisions")
    os.makedirs(div_dir, exist_ok=True)
    div_records = defaultdict(list)
    for minute, rec in records:
        day, _ = config_minute_to_display(venue_model, minute)
        div_rec = dict(rec)
        div_rec["day"] = day
        div_records[rec["division"]].append(div_rec)

    for div_code, div_matches in sorted(div_records.items()):
        div_json = {
            "division": div_code,
            "division_name": div_matches[0]["division_name"] if div_matches else div_code,
            "category": div_matches[0]["category"] if div_matches else "",
            "match_count": len(div_matches),
            "matches": div_matches,
        }
        filename = div_code.replace(" ", "_") + ".json"
        with open(os.path.join(div_dir, filename), "w", encoding="utf-8") as f:
            json.dump(div_json, f, indent=2, ensure_ascii=False)

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
