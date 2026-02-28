"""
Generate match schedules from division JSON files.

Usage:
    python generate_schedule.py

Reads:  divisions/tournament_index.json + divisions/*.json
Writes: schedules/Saturday_Morning.json, Saturday_Afternoon.json,
        Saturday_Evening.json, Sunday_Morning.json, Sunday_Afternoon.json,
        schedules/schedule_index.json
"""

import json
import os
import re
from collections import defaultdict
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIVISIONS_DIR = os.path.join(BASE_DIR, "output", "divisions")
SCHEDULES_DIR = os.path.join(BASE_DIR, "output", "schedules")

TOURNAMENT_NAME = "Kumpoo Tervasulan Eliitti 2025"

# ── Time model ───────────────────────────────────────────────────
# Minutes from Saturday 9:00
# Saturday: 0 (9:00) to 780 (22:00)
# Sunday:   1440 (9:00) to 1980 (18:00)

SAT_START = 0       # Saturday 9:00
SAT_END = 780       # Saturday 22:00
SUN_START = 1440    # Sunday 9:00
SUN_COURTS_14_END = 1860   # Sunday 16:00 (courts 1-4)
SUN_COURTS_58_END = 1980   # Sunday 18:00 (courts 5-8)

SLOT_DURATION = 30  # minutes per slot

# Session boundaries (in minutes)
SESSIONS = [
    {"name": "Saturday Morning",   "file": "Saturday_Morning.json",   "date": "Saturday", "start": 0,    "end": 240,  "start_time": "09:00", "end_time": "13:00"},
    {"name": "Saturday Afternoon", "file": "Saturday_Afternoon.json", "date": "Saturday", "start": 240,  "end": 540,  "start_time": "13:00", "end_time": "18:00"},
    {"name": "Saturday Evening",   "file": "Saturday_Evening.json",   "date": "Saturday", "start": 540,  "end": 780,  "start_time": "18:00", "end_time": "22:00"},
    {"name": "Sunday Morning",     "file": "Sunday_Morning.json",     "date": "Sunday",   "start": 1440, "end": 1680, "start_time": "09:00", "end_time": "13:00"},
    {"name": "Sunday Afternoon",   "file": "Sunday_Afternoon.json",   "date": "Sunday",   "start": 1680, "end": 1980, "start_time": "13:00", "end_time": "18:00"},
]

# Priority levels
PRIORITY_ELITE_POOL = 5   # Elite round-robins first (long rest = cascading risk)
PRIORITY_POOL = 10
PRIORITY_R1 = 20
PRIORITY_GROUP_PLAYOFF = 30
PRIORITY_R2 = 40
PRIORITY_QF = 50
PRIORITY_SF = 60
PRIORITY_FINAL = 70

ROUND_PRIORITY = {
    "Round 1": PRIORITY_R1,
    "Round 2": PRIORITY_R2,
    "Quarter-Final": PRIORITY_QF,
    "Semi-Final": PRIORITY_SF,
    "Final": PRIORITY_FINAL,
}

ELITE_DIVISIONS = {"MS V", "WS V", "XD V"}
OPEN_A_DIVISIONS = {"MS A", "MD A", "WD A", "XD A"}
JUNIOR_CATEGORIES = {"Junior"}


# ── Helper functions ─────────────────────────────────────────────

def minute_to_display(m):
    """Convert minute offset to (day, 'HH:MM')."""
    if m >= SUN_START:
        h, mm = divmod(m - SUN_START, 60)
        return "Sunday", f"{h + 9:02d}:{mm:02d}"
    else:
        h, mm = divmod(m, 60)
        return "Saturday", f"{h + 9:02d}:{mm:02d}"


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
                 rest_min, priority, is_sf_or_final, prerequisites, is_elite):
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
        self.rest_min = rest_min
        self.priority = priority
        self.is_sf_or_final = is_sf_or_final
        self.prerequisites = prerequisites
        self.is_elite = is_elite
        self.pool_round = 0  # scheduling round within a RR pool (0-based)
        # True if actual players are known (R1/pool), False if placeholder ("Winner of...")
        self.has_real_players = bool(known_players) and not (
            player1.startswith("Winner ") or player1.startswith("Slot ")
        )
        # Effective players for scheduling (filtered by probability threshold)
        # Set by _apply_probability_filter(); defaults to known_players
        self.effective_players = list(known_players) if known_players else []


def load_all_matches():
    """Load all schedulable matches from division JSON files."""
    with open(os.path.join(DIVISIONS_DIR, "tournament_index.json"), encoding="utf-8") as f:
        index = json.load(f)

    all_matches = []
    # Store match data by ID for back-tracing player names
    match_by_id = {}

    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue

        filepath = os.path.join(DIVISIONS_DIR, entry["file"])
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        div_code = data["code"]
        div_name = data["name"]
        category = data["category"]
        fmt = data["format"]
        is_elite = div_code in ELITE_DIVISIONS
        duration = 45 if is_elite else 30
        rest = 60 if is_elite else 30

        if fmt == "elimination":
            matches = _load_elimination_matches(
                data, div_code, div_name, category, is_elite, duration, rest
            )
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

        elif fmt == "round_robin":
            matches = _load_roundrobin_matches(
                data, div_code, div_name, category, is_elite, duration, rest
            )
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

        elif fmt == "group_playoff":
            matches = _load_group_playoff_matches(
                data, div_code, div_name, category, is_elite, duration, rest
            )
            all_matches.extend(matches)
            for m in matches:
                match_by_id[m.id] = m

    # Resolve known_players for later rounds by tracing back through brackets
    _resolve_known_players(all_matches, match_by_id)

    return all_matches, match_by_id


def _load_elimination_matches(data, div_code, div_name, category, is_elite, duration, rest):
    matches = []
    rounds = data.get("rounds", [])

    # Build a map of round_name -> round data for lookup
    round_map = {rnd["name"]: rnd for rnd in rounds}

    for rnd in rounds:
        round_name = rnd["name"]
        priority = ROUND_PRIORITY.get(round_name, PRIORITY_R1)
        is_sf_final = round_name in ("Semi-Final", "Final")

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
                duration_min=duration, rest_min=rest,
                priority=priority, is_sf_or_final=is_sf_final,
                prerequisites=prereqs, is_elite=is_elite,
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


def _load_roundrobin_matches(data, div_code, div_name, category, is_elite, duration, rest):
    matches = []
    for m in data.get("matches", []):
        match_id = make_match_id(div_code, "Pool", m["match"])
        p1 = m.get("player1", "")
        p2 = m.get("player2", "")
        known = extract_player_names(p1) + extract_player_names(p2)

        pool_priority = PRIORITY_ELITE_POOL if is_elite else PRIORITY_POOL
        match = Match(
            match_id=match_id,
            div_code=div_code, div_name=div_name, category=category,
            round_name="Pool", match_num=m["match"],
            player1=p1, player2=p2, known_players=known,
            duration_min=duration, rest_min=rest,
            priority=pool_priority, is_sf_or_final=False,
            prerequisites=[], is_elite=is_elite,
        )
        matches.append(match)

    # Compute scheduling rounds for parallelism
    _compute_pool_rounds(matches)
    return matches


def _load_group_playoff_matches(data, div_code, div_name, category, is_elite, duration, rest):
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
                duration_min=duration, rest_min=rest,
                priority=PRIORITY_POOL, is_sf_or_final=False,
                prerequisites=[], is_elite=is_elite,
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
            priority = ROUND_PRIORITY.get(round_name, PRIORITY_GROUP_PLAYOFF)
            priority = max(priority, PRIORITY_GROUP_PLAYOFF)
            is_sf_final = round_name in ("Semi-Final", "Final")

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
                    duration_min=duration, rest_min=rest,
                    priority=priority, is_sf_or_final=is_sf_final,
                    prerequisites=prereqs, is_elite=is_elite,
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


# ── Schedule configuration ──────────────────────────────────────

DEFAULT_SCHEDULE_CONFIG = {
    "default_threshold": 0.0,
    "use_seeding": False,
    "seeding_probabilities": {
        "1_vs_unseeded": 0.75,
        "2_vs_unseeded": 0.70,
        "3/4_vs_unseeded": 0.65,
        "seed_vs_seed": 0.55,
        "default": 0.50,
    },
    "divisions": {},
}


def _load_schedule_config(config_path):
    """Load schedule configuration from JSON file, merged with defaults."""
    config = dict(DEFAULT_SCHEDULE_CONFIG)
    if config_path:
        with open(config_path, encoding="utf-8") as f:
            user_config = json.load(f)
        config["default_threshold"] = user_config.get("default_threshold", config["default_threshold"])
        config["use_seeding"] = user_config.get("use_seeding", config["use_seeding"])
        if "seeding_probabilities" in user_config:
            config["seeding_probabilities"].update(user_config["seeding_probabilities"])
        config["divisions"] = user_config.get("divisions", {})
    return config


# ── Probability-based player filtering ──────────────────────────

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


def _get_seed_label(player_name, seed_map):
    """Look up seed label for a player. Returns e.g. '1', '2', '3/4', or None."""
    return seed_map.get(player_name)


def _get_win_probability(seed_a, seed_b, seeding_probs):
    """Get win probability for player A vs player B based on seeds.
    Returns probability of A winning."""
    default_prob = seeding_probs.get("default", 0.50)

    if seed_a is None and seed_b is None:
        return default_prob

    if seed_a is not None and seed_b is None:
        key = f"{seed_a}_vs_unseeded"
        return seeding_probs.get(key, default_prob)

    if seed_a is None and seed_b is not None:
        key = f"{seed_b}_vs_unseeded"
        return 1.0 - seeding_probs.get(key, default_prob)

    # Both seeded
    return seeding_probs.get("seed_vs_seed", default_prob)


def _build_seed_map(all_matches, match_by_id):
    """Build player_name -> seed_label map from division JSON data."""
    seed_map = {}
    # Read seed info from division files
    index_path = os.path.join(DIVISIONS_DIR, "tournament_index.json")
    if not os.path.exists(index_path):
        return seed_map
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)
    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue
        filepath = os.path.join(DIVISIONS_DIR, entry["file"])
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        for player in data.get("players", []):
            seed = player.get("seed")
            if seed:
                name = player.get("name")
                if name:
                    seed_map[name] = seed
                # Doubles: players may be in a "players" sub-list
                for sub in player.get("players", []):
                    if sub.get("seed"):
                        seed_map[sub["name"]] = sub["seed"]
                    elif seed:
                        seed_map[sub["name"]] = seed
    return seed_map


def _compute_player_probabilities(all_matches, match_by_id, config):
    """Compute normalized probability for each player reaching each match.
    Returns dict: match_id -> {player_name: normalized_probability}"""
    use_seeding = config.get("use_seeding", False)
    seeding_probs = config.get("seeding_probabilities", {})

    seed_map = _build_seed_map(all_matches, match_by_id) if use_seeding else {}

    # Raw probabilities: match_id -> {player: raw_probability}
    raw_probs = {}

    # Process matches in priority order (ensures feeders computed before dependents)
    sorted_matches = sorted(all_matches, key=lambda m: m.priority)

    for match in sorted_matches:
        if match.has_real_players:
            # Real-player match: all players at 100%
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
                # For each player in the prerequisite, compute their win probability
                # against the other players in that match
                prereq_players = list(prereq_player_probs.keys())
                # Split into the two sides (player1 players vs player2 players)
                p1_names = set(extract_player_names(prereq.player1))
                p2_names = set(extract_player_names(prereq.player2))
                for player, prob in prereq_player_probs.items():
                    player_seed = _get_seed_label(player, seed_map)
                    # Find opponent seed (representative from other side)
                    if player in p1_names:
                        opponents = [p for p in prereq_players if p in p2_names]
                    else:
                        opponents = [p for p in prereq_players if p in p1_names]
                    if opponents:
                        opp_seed = _get_seed_label(opponents[0], seed_map)
                        win_prob = _get_win_probability(player_seed, opp_seed, seeding_probs)
                    else:
                        win_prob = seeding_probs.get("default", 0.50)
                    match_probs[player] = prob * win_prob
            else:
                # Default 50/50: each player gets half their current probability
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
    default_threshold = config.get("default_threshold", 0.0)
    div_configs = config.get("divisions", {})

    for match in all_matches:
        threshold = default_threshold
        div_override = div_configs.get(match.division_code, {})
        if isinstance(div_override, dict):
            threshold = div_override.get("threshold", default_threshold)

        if threshold <= 0.0:
            # No filtering: include all known players
            match.effective_players = list(match.known_players)
        else:
            match_probs = probabilities.get(match.id, {})
            match.effective_players = [
                p for p in match.known_players
                if match_probs.get(p, 0.0) >= threshold
            ]


# ── Court schedule ───────────────────────────────────────────────

class CourtSchedule:
    def __init__(self):
        self.booked = {}  # (court, minute) -> match_id

    def is_available(self, court, minute):
        """Check if a court is available at a given time."""
        if not self._court_exists(court, minute):
            return False
        return (court, minute) not in self.booked

    def _court_exists(self, court, minute):
        """Check if a court is operational at this time."""
        if minute < SUN_START:
            # Saturday
            return 1 <= court <= 12 and 0 <= minute < SAT_END
        else:
            # Sunday
            if 1 <= court <= 4:
                return SUN_START <= minute < SUN_COURTS_14_END
            elif 5 <= court <= 8:
                return SUN_START <= minute < SUN_COURTS_58_END
            else:
                return False  # courts 9-12 not available Sunday

    def book(self, court, minute, match_id, duration_min):
        """Book a court for a match. 45-min matches block 2 slots."""
        slots_needed = (duration_min + SLOT_DURATION - 1) // SLOT_DURATION
        for i in range(slots_needed):
            self.booked[(court, minute + i * SLOT_DURATION)] = match_id

    def can_book(self, court, minute, duration_min):
        """Check if a court can be booked for the full duration."""
        slots_needed = (duration_min + SLOT_DURATION - 1) // SLOT_DURATION
        for i in range(slots_needed):
            t = minute + i * SLOT_DURATION
            if not self.is_available(court, t):
                return False
        return True


class PlayerTracker:
    def __init__(self):
        self.available_from = defaultdict(int)  # player_name -> earliest minute

    def earliest_for(self, players):
        """Get the earliest time when all players are available."""
        if not players:
            return 0
        return max(self.available_from[p] for p in players)

    def update(self, players, match_start, duration, rest):
        """Update player availability after a match."""
        next_available = match_start + duration + rest
        for p in players:
            self.available_from[p] = max(self.available_from[p], next_available)


# ── Court eligibility ────────────────────────────────────────────

def get_eligible_courts(match, time_minute):
    """Get ordered list of courts to try for a match at a given time."""
    is_sunday = time_minute >= SUN_START
    div_code = match.division_code
    category = match.category

    if div_code in ELITE_DIVISIONS:
        return [5, 6, 7, 8]

    if div_code in OPEN_A_DIVISIONS:
        if is_sunday:
            return [5, 6, 7, 8, 1, 2, 3, 4]
        else:
            return [5, 6, 7, 8, 1, 2, 3, 4, 9, 10, 11, 12]

    if category in JUNIOR_CATEGORIES:
        if is_sunday:
            return [1, 2, 3, 4, 5, 6, 7, 8]
        else:
            return [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8]

    # Open B, C, Veterans
    if is_sunday:
        return [1, 2, 3, 4, 5, 6, 7, 8]
    else:
        return [1, 2, 3, 4, 9, 10, 11, 12, 5, 6, 7, 8]


# ── All available time slots in order ────────────────────────────

def generate_all_slots():
    """Generate all 30-min time slots in chronological order."""
    slots = []
    # Saturday: 0 to 750 (9:00 to 21:30)
    t = 0
    while t < SAT_END:
        slots.append(t)
        t += SLOT_DURATION
    # Sunday: 1440 to max end
    t = SUN_START
    while t < SUN_COURTS_58_END:
        slots.append(t)
        t += SLOT_DURATION
    return slots


ALL_SLOTS = generate_all_slots()


# ── Scheduling algorithm ─────────────────────────────────────────

def schedule_matches(matches, match_by_id, config=None):
    """Main scheduling loop. Returns (scheduled_dict, unscheduled_list)."""
    if config is None:
        config = dict(DEFAULT_SCHEDULE_CONFIG)

    # Compute probabilities and filter effective players
    probabilities = _compute_player_probabilities(matches, match_by_id, config)
    _apply_probability_filter(matches, probabilities, config)

    court_sched = CourtSchedule()
    player_tracker = PlayerTracker()
    scheduled = {}       # match_id -> (court, minute)
    scheduled_end = {}   # match_id -> end minute
    unscheduled = []

    # Sort by priority, then pool_round (groups non-conflicting RR matches),
    # then most-constrained-first (-player count, so doubles before singles),
    # then match_num and division for determinism.
    sorted_matches = sorted(matches, key=lambda m: (
        m.priority, m.pool_round, -len(m.known_players),
        m.match_num, m.division_code
    ))

    for match in sorted_matches:
        # Compute earliest start time
        earliest = 0

        # Player availability — for all matches with effective players
        if match.effective_players:
            earliest = max(earliest, player_tracker.earliest_for(match.effective_players))

        # Prerequisite constraint — feeder matches must finish + rest
        for prereq_id in match.prerequisites:
            if prereq_id in scheduled_end:
                earliest = max(earliest, scheduled_end[prereq_id] + match.rest_min)
            elif prereq_id not in scheduled:
                # Prerequisite wasn't scheduled (maybe it was a bye that got skipped)
                pass

        # Sunday rule for SF/Final
        if match.is_sf_or_final:
            earliest = max(earliest, SUN_START)

        # Snap to next 30-min slot boundary
        if earliest % SLOT_DURATION != 0:
            earliest = ((earliest // SLOT_DURATION) + 1) * SLOT_DURATION

        # Find available slot
        placed = False
        for slot in ALL_SLOTS:
            if slot < earliest:
                continue

            courts = get_eligible_courts(match, slot)
            for court in courts:
                if court_sched.can_book(court, slot, match.duration_min):
                    # Check player availability for all matches with effective players
                    if match.effective_players:
                        all_available = all(
                            player_tracker.available_from[p] <= slot
                            for p in match.effective_players
                        )
                        if not all_available:
                            continue

                    # Book it
                    court_sched.book(court, slot, match.id, match.duration_min)
                    # Only update tracker for real-player matches (confirmed players).
                    # Placeholder matches check effective_players for rest but don't
                    # add tracker entries — avoids over-constraining cross-division
                    # schedules when all possible players would be blocked.
                    if match.has_real_players and match.known_players:
                        player_tracker.update(
                            match.known_players, slot,
                            match.duration_min, match.rest_min
                        )
                    scheduled[match.id] = (court, slot)
                    scheduled_end[match.id] = slot + match.duration_min
                    placed = True
                    break
            if placed:
                break

        if not placed:
            unscheduled.append(match)

    return scheduled, unscheduled, court_sched, player_tracker


# ── Validation ───────────────────────────────────────────────────

def validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker):
    """Run validation checks and return warnings."""
    warnings = []

    # Check SF/Final on Sunday
    for match in matches:
        if match.id not in scheduled:
            continue
        court, minute = scheduled[match.id]
        if match.is_sf_or_final and minute < SUN_START:
            warnings.append(f"SF/Final on Saturday: {match.id} at {minute_to_display(minute)}")

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
                        f"Round order violation: {prereq_id} at {minute_to_display(prereq_time)} "
                        f"but {match.id} at {minute_to_display(match_time)}"
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
                    f"Insufficient rest for {player}: {id1} ends at {minute_to_display(end1)}, "
                    f"{id2} starts at {minute_to_display(start2)}"
                )

    # Check Elite courts
    for match in matches:
        if match.id not in scheduled:
            continue
        if match.is_elite:
            court, _ = scheduled[match.id]
            if court not in (5, 6, 7, 8):
                warnings.append(f"Elite on wrong court: {match.id} on court {court}")

    return warnings


# ── Output generation ────────────────────────────────────────────

def write_schedules(matches, match_by_id, scheduled, unscheduled, warnings):
    """Write session JSON files and index."""
    os.makedirs(SCHEDULES_DIR, exist_ok=True)

    # Build scheduled match records
    records = []
    for match in matches:
        if match.id not in scheduled:
            continue
        court, minute = scheduled[match.id]
        day, time_str = minute_to_display(minute)
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
    for sess in SESSIONS:
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

        outpath = os.path.join(SCHEDULES_DIR, sess["file"])
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
        "tournament": TOURNAMENT_NAME,
        "generated": str(date.today()),
        "sessions": session_data,
        "total_matches": len(matches) + sum(1 for _ in []),  # all loaded (excl byes)
        "total_scheduled": len(scheduled),
        "unscheduled": [m.id for m in unscheduled],
        "warnings": warnings,
    }
    # Fix total count
    index["total_matches"] = len(scheduled) + len(unscheduled)

    index_path = os.path.join(SCHEDULES_DIR, "schedule_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return session_data


# ── Main ─────────────────────────────────────────────────────────

def main(config_path=None):
    config = _load_schedule_config(config_path)
    if config_path:
        print(f"Schedule config: {config_path}")
        print(f"  default_threshold: {config['default_threshold']}")
        print(f"  use_seeding: {config['use_seeding']}")
        div_overrides = config.get("divisions", {})
        if div_overrides:
            print(f"  division overrides: {list(div_overrides.keys())}")
        print()

    print(f"Loading divisions from: {DIVISIONS_DIR}/")
    matches, match_by_id = load_all_matches()
    print(f"Loaded {len(matches)} schedulable matches (byes excluded)\n")

    print("Scheduling...")
    scheduled, unscheduled, court_sched, player_tracker = schedule_matches(matches, match_by_id, config)

    print(f"  Scheduled: {len(scheduled)}")
    print(f"  Unscheduled: {len(unscheduled)}")
    if unscheduled:
        print("  Unscheduled matches:")
        for m in unscheduled:
            print(f"    {m.id}")

    print("\nValidating...")
    warnings = validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker)
    if warnings:
        print(f"  {len(warnings)} warnings:")
        for w in warnings:
            print(f"    WARNING: {w}")
    else:
        print("  No warnings — all checks passed!")

    print(f"\nWriting schedules to: {SCHEDULES_DIR}/")
    session_data = write_schedules(matches, match_by_id, scheduled, unscheduled, warnings)

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

    print(f"\nDone. Files written to {SCHEDULES_DIR}/")


if __name__ == "__main__":
    main()
