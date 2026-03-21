"""
Test which draw format combinations fit the kumpoo-2026 venue/schedule.

Generates mock draws with random seedings for each division,
then runs the scheduler to check if all matches can be scheduled.
"""
import json
import os
import sys
import random
import math
import itertools
from copy import deepcopy

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from config import load_config, build_venue_model
from generate_schedule import load_all_matches, schedule_matches, validate_schedule

TOURNAMENT_DIR = os.path.dirname(os.path.abspath(__file__))
DIVISIONS_DIR = os.path.join(TOURNAMENT_DIR, 'output', 'divisions')


# ── Draw generation helpers ──────────────────────────────────────

def next_power_of_2(n):
    return 1 << (n - 1).bit_length()


def round_name_for_size(draw_size, round_idx, total_rounds):
    """Map round index to name based on draw size."""
    rounds_from_final = total_rounds - 1 - round_idx
    if rounds_from_final == 0:
        return "Final"
    elif rounds_from_final == 1:
        return "Semi-Final"
    elif rounds_from_final == 2:
        return "Quarter-Final"
    else:
        return f"Round {round_idx + 1}"


def round_abbrev(name):
    if name == "Final":
        return "F"
    elif name == "Semi-Final":
        return "SF"
    elif name == "Quarter-Final":
        return "QF"
    elif name.startswith("Round "):
        return f"R{name.split()[1]}"
    return name


def _standard_seed_order(n):
    """Generate standard bracket seed order by position.

    Returns a list of length n where index i holds the seed number
    for bracket position i+1.  Ensures seed 1 and 2 are at opposite
    ends, 3/4 in opposite halves, etc.  Byes (highest seed numbers)
    end up spread evenly so no two byes share an R1 match.
    """
    if n == 1:
        return [1]
    half = _standard_seed_order(n // 2)
    result = []
    for seed in half:
        result.append(seed)
        result.append(n + 1 - seed)
    return result


def generate_elimination_draw(players, is_doubles):
    """Generate a full elimination bracket with proper bye placement.

    Players are randomly assigned to seed numbers, then placed into
    standard bracket positions.  Byes occupy the highest seed slots
    and are spread so that no Bye-vs-Bye match ever occurs.
    """
    n = len(players)
    draw_size = next_power_of_2(n)
    total_rounds = int(math.log2(draw_size))

    # Randomly assign players to seeds 1..n (random draw)
    shuffled = list(players)
    random.shuffle(shuffled)

    # Standard bracket: position -> seed number
    seed_order = _standard_seed_order(draw_size)

    # Build slots: bracket position -> player or None (bye)
    # Seeds 1..n are players, seeds n+1..draw_size are byes
    slots = [None] * draw_size
    for pos_idx, seed_num in enumerate(seed_order):
        if seed_num <= n:
            slots[pos_idx] = shuffled[seed_num - 1]

    # Build player entries with positions
    player_entries = []
    for i, p in enumerate(slots):
        if p is not None:
            entry = dict(p)
            entry["position"] = i + 1
            player_entries.append(entry)

    # Build rounds
    rounds = []
    current_slots = slots
    for r in range(total_rounds):
        rname = round_name_for_size(draw_size, r, total_rounds)
        matches = []
        next_slots = []
        for i in range(0, len(current_slots), 2):
            match_num = i // 2 + 1
            s1 = current_slots[i]
            s2 = current_slots[i + 1]

            if r == 0:
                p1_str = _player_display(s1, is_doubles) if s1 else "Bye"
                p2_str = _player_display(s2, is_doubles) if s2 else "Bye"
            else:
                prev_rname = round_name_for_size(draw_size, r - 1, total_rounds)
                prev_abbr = round_abbrev(prev_rname)
                p1_str = f"Winner {prev_abbr}-M{s1}"
                p2_str = f"Winner {prev_abbr}-M{s2}"

            match = {"match": match_num, "player1": p1_str, "player2": p2_str}

            if r == 0:
                if s1 is None:
                    match["notes"] = f"{p2_str} auto-advances"
                elif s2 is None:
                    match["notes"] = f"{p1_str} auto-advances"

            matches.append(match)
            next_slots.append(match_num)

        rounds.append({"name": rname, "matches": matches})
        current_slots = next_slots

    return {
        "format": "elimination",
        "drawSize": draw_size,
        "players": player_entries,
        "rounds": rounds,
    }


def generate_roundrobin_draw(players, is_doubles):
    """Generate a round-robin draw with all pairwise matches."""
    player_entries = []
    for i, p in enumerate(players):
        entry = dict(p)
        entry["position"] = i + 1
        player_entries.append(entry)

    matches = []
    match_num = 1
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            p1_str = _player_display(players[i], is_doubles)
            p2_str = _player_display(players[j], is_doubles)
            matches.append({"match": match_num, "player1": p1_str, "player2": p2_str})
            match_num += 1

    return {
        "format": "round_robin",
        "players": player_entries,
        "matches": matches,
    }


def generate_group_playoff_draw(players, group_sizes, is_doubles, playoff_entries=None):
    """Generate group+playoff draw.

    group_sizes: list like [4, 4] or [4, 4, 3]
    playoff_entries: total number of players advancing to playoff.
        Default (None) = 1 per group (group winners only).
        e.g. 4 with 2 groups means top 2 from each group.
    """
    random.shuffle(players)
    groups = []
    idx = 0
    for gi, gs in enumerate(group_sizes):
        group_players = players[idx:idx + gs]
        idx += gs
        group_name = f"Group {chr(65 + gi)}"

        g_entries = []
        for pi, p in enumerate(group_players):
            entry = dict(p)
            entry["position"] = pi + 1
            g_entries.append(entry)

        g_matches = []
        match_num = 1
        for i in range(gs):
            for j in range(i + 1, gs):
                p1_str = _player_display(group_players[i], is_doubles)
                p2_str = _player_display(group_players[j], is_doubles)
                g_matches.append({"match": match_num, "player1": p1_str, "player2": p2_str})
                match_num += 1

        groups.append({"name": group_name, "players": g_entries, "matches": g_matches})

    # Playoff bracket
    num_groups = len(group_sizes)
    if playoff_entries is None:
        playoff_entries = num_groups  # 1 per group
    playoff_size = next_power_of_2(playoff_entries)
    total_playoff_rounds = int(math.log2(playoff_size))

    playoff_rounds = []
    current_count = playoff_size
    for r in range(total_playoff_rounds):
        rname = round_name_for_size(playoff_size, r, total_playoff_rounds)
        matches = []
        next_count = current_count // 2
        for i in range(next_count):
            match_num = i + 1
            if r == 0:
                s1_idx = i * 2
                s2_idx = i * 2 + 1
                p1 = f"Slot {s1_idx + 1}" if s1_idx < playoff_entries else "Bye"
                p2 = f"Slot {s2_idx + 1}" if s2_idx < playoff_entries else "Bye"
            else:
                prev_rname = round_name_for_size(playoff_size, r - 1, total_playoff_rounds)
                prev_abbr = round_abbrev(prev_rname)
                p1 = f"Winner {prev_abbr}-M{i * 2 + 1}"
                p2 = f"Winner {prev_abbr}-M{i * 2 + 2}"
            match = {"match": match_num, "player1": p1, "player2": p2}
            if p1 == "Bye" or p2 == "Bye":
                winner = p2 if p1 == "Bye" else p1
                match["notes"] = f"{winner} auto-advances"
            matches.append(match)
        playoff_rounds.append({"name": rname, "matches": matches})
        current_count = next_count

    playoff = {
        "format": "elimination",
        "drawSize": playoff_size,
        "rounds": playoff_rounds,
    }

    return {
        "format": "group_playoff",
        "groups": groups,
        "playoff": playoff,
    }


def _player_display(player, is_doubles):
    if is_doubles:
        names = [p["name"] for p in player["players"]]
        return " / ".join(names)
    return player["name"]


# ── Division JSON writing ────────────────────────────────────────

def load_entries():
    """Load all current entries-only division JSONs."""
    entries = {}
    for fname in os.listdir(DIVISIONS_DIR):
        if fname == 'tournament_index.json' or not fname.endswith('.json'):
            continue
        with open(os.path.join(DIVISIONS_DIR, fname), encoding='utf-8') as f:
            data = json.load(f)
        entries[data['code']] = data
    return entries


def write_division_files(entries, format_assignments):
    """Write division JSONs and index based on format assignments.

    format_assignments: dict of div_code -> {
        'format': 'elimination'|'round_robin'|'group_playoff',
        'group_sizes': [4, 4] (only for group_playoff),
        'playoff_entries': 4 (optional, for group_playoff; default=num_groups)
    }
    """
    doubles_events = ["MD", "WD", "XD", "BD"]
    divisions_index = []

    for code, data in sorted(entries.items()):
        assignment = format_assignments.get(code)
        if not assignment:
            continue

        fmt = assignment['format']
        event_code = code.split()[0]
        is_doubles = event_code in doubles_events
        players = data['players']

        if fmt == 'elimination':
            draw_data = generate_elimination_draw(players, is_doubles)
        elif fmt == 'round_robin':
            draw_data = generate_roundrobin_draw(players, is_doubles)
        elif fmt == 'group_playoff':
            draw_data = generate_group_playoff_draw(
                players, assignment['group_sizes'], is_doubles,
                playoff_entries=assignment.get('playoff_entries')
            )
        else:
            continue

        # Build full division JSON
        div = {
            "tournament": data["tournament"],
            "name": data["name"],
            "code": code,
            "category": data["category"],
            "sheet": data["sheet"],
            "draw_type": "main_draw",
        }
        div.update(draw_data)
        div["clubs"] = []

        file_code = code.replace(' ', '_')
        filename = f"{file_code}-Main_Draw.json"

        with open(os.path.join(DIVISIONS_DIR, filename), 'w', encoding='utf-8') as f:
            json.dump(div, f, indent=2, ensure_ascii=False)

        index_entry = {
            "file": filename,
            "name": data["name"],
            "code": code,
            "category": data["category"],
            "draw_type": "main_draw",
            "format": fmt,
        }
        divisions_index.append(index_entry)

        # Write playoff file for group_playoff
        if fmt == 'group_playoff' and 'playoff' in draw_data:
            pf_filename = f"{file_code}-Playoff.json"
            pf_data = {
                "tournament": data["tournament"],
                "name": f"{data['name']} Playoff",
                "code": code,
                "category": data["category"],
                "sheet": data["sheet"],
                "draw_type": "playoff",
                "format": "elimination",
                "drawSize": draw_data["playoff"]["drawSize"],
                "players": [],
                "rounds": draw_data["playoff"]["rounds"],
                "clubs": [],
            }
            with open(os.path.join(DIVISIONS_DIR, pf_filename), 'w', encoding='utf-8') as f:
                json.dump(pf_data, f, indent=2, ensure_ascii=False)

            div["playoff_file"] = pf_filename
            # Re-write main file with playoff_file reference
            with open(os.path.join(DIVISIONS_DIR, filename), 'w', encoding='utf-8') as f:
                json.dump(div, f, indent=2, ensure_ascii=False)

            divisions_index.append({
                "file": pf_filename,
                "name": f"{data['name']} Playoff",
                "code": code,
                "category": data["category"],
                "draw_type": "playoff",
                "format": "elimination",
            })

    # Write tournament index
    index = {
        "tournament": "Kumpoo Tervasulan Eliitti 2026",
        "total_divisions": len(divisions_index),
        "clubs": [],
        "divisions": divisions_index,
    }
    with open(os.path.join(DIVISIONS_DIR, 'tournament_index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def count_matches(format_assignments, entries):
    """Count total schedulable matches for a format assignment."""
    total = 0
    for code, assignment in format_assignments.items():
        n = entries[code].get('player_count', len(entries[code].get('players', [])))
        fmt = assignment['format']
        if fmt == 'elimination':
            total += n - 1
        elif fmt == 'round_robin':
            total += n * (n - 1) // 2
        elif fmt == 'group_playoff':
            gs = assignment['group_sizes']
            for g in gs:
                total += g * (g - 1) // 2
            # Playoff matches
            num_groups = len(gs)
            ps = next_power_of_2(num_groups)
            total += ps - 1  # minus byes handled by scheduler
            # Actually byes are skipped, so: playoff matches = num_groups - 1
            # (single elimination of group winners)
            # Correction: scheduled playoff matches = num_groups - 1
            total -= (ps - 1)
            total += num_groups - 1
    return total


def run_scenario(name, format_assignments, entries, config, venue_model):
    """Generate draws, run scheduler, return results."""
    random.seed(42)  # Reproducible
    write_division_files(entries, format_assignments)

    matches, match_by_id = load_all_matches(config)
    scheduled, unscheduled, court_sched, player_tracker = schedule_matches(
        matches, match_by_id, config, venue_model
    )
    warnings = validate_schedule(matches, match_by_id, scheduled, court_sched, player_tracker, config, venue_model)

    total_matches = len(matches)
    n_scheduled = len(scheduled)
    n_unscheduled = len(unscheduled)

    print(f"\n{'=' * 60}")
    print(f"Scenario: {name}")
    print(f"{'=' * 60}")
    print(f"  Total matches: {total_matches}")
    print(f"  Scheduled:     {n_scheduled}")
    print(f"  Unscheduled:   {n_unscheduled}")

    if unscheduled:
        # Group by division
        unsched_by_div = {}
        for m in unscheduled:
            unsched_by_div.setdefault(m.division_code, []).append(m.id)
        print(f"  Unscheduled by division:")
        for div, ids in sorted(unsched_by_div.items()):
            print(f"    {div}: {len(ids)} matches")

    if warnings:
        print(f"  Warnings: {len(warnings)}")
        for w in warnings[:5]:
            print(f"    {w}")
        if len(warnings) > 5:
            print(f"    ... and {len(warnings) - 5} more")

    fit = n_unscheduled == 0 and len(warnings) == 0
    print(f"  FITS: {'YES' if fit else 'NO'}")

    return {
        'name': name,
        'total': total_matches,
        'scheduled': n_scheduled,
        'unscheduled': n_unscheduled,
        'unscheduled_matches': [m.id for m in unscheduled],
        'warnings': warnings,
        'fits': fit,
    }


# ── Group size variations for juniors ────────────────────────────

def group_size_options(n):
    """Generate reasonable group size splits for n players."""
    options = []
    # 2 groups
    if n >= 4:
        half = n // 2
        options.append(sorted([half, n - half], reverse=True))
    # 3 groups
    if n >= 6:
        base = n // 3
        rem = n % 3
        gs = [base] * 3
        for i in range(rem):
            gs[i] += 1
        options.append(sorted(gs, reverse=True))
    # 4 groups
    if n >= 8:
        base = n // 4
        rem = n % 4
        gs = [base] * 4
        for i in range(rem):
            gs[i] += 1
        options.append(sorted(gs, reverse=True))
    return options


# ── Main ─────────────────────────────────────────────────────────

def main():
    config = load_config(TOURNAMENT_DIR)
    venue_model = build_venue_model(config)
    entries = load_entries()

    # Print venue capacity
    slot_duration = venue_model["slot_duration"]
    total_court_slots = 0
    for court, start, end in venue_model["court_windows"]:
        total_court_slots += (end - start) // slot_duration
    print(f"Venue capacity: {total_court_slots} court-slots of {slot_duration} min")

    # ── Format assignments ────────────────────────────────────────
    assignments = {}

    # Junior divisions: 2 groups, top 2 from each -> 4-player playoff (SF + F)
    # BS U13 (8): groups [4, 4], playoff_entries=4
    # BS U15 (11): groups [6, 5], playoff_entries=4
    # BS U17 (12): groups [6, 6], playoff_entries=4
    assignments['BS U13'] = {'format': 'group_playoff', 'group_sizes': [4, 4], 'playoff_entries': 4}
    assignments['BS U15'] = {'format': 'group_playoff', 'group_sizes': [6, 5], 'playoff_entries': 4}
    assignments['BS U17'] = {'format': 'group_playoff', 'group_sizes': [6, 6], 'playoff_entries': 4}

    # New group+playoff: 2 groups, top 1 from each -> single Final
    # MD 35 (6): groups [3, 3], playoff_entries=2
    # MD A (9): groups [5, 4], playoff_entries=2
    # XD B (8): groups [4, 4], playoff_entries=2
    # XD C (10): groups [5, 5], playoff_entries=2
    assignments['MD 35'] = {'format': 'group_playoff', 'group_sizes': [3, 3], 'playoff_entries': 2}
    assignments['MD A']  = {'format': 'group_playoff', 'group_sizes': [5, 4], 'playoff_entries': 2}
    assignments['XD B']  = {'format': 'group_playoff', 'group_sizes': [4, 4], 'playoff_entries': 2}
    assignments['XD C']  = {'format': 'group_playoff', 'group_sizes': [5, 5], 'playoff_entries': 2}

    # Round-robin (<=5 entries)
    for code in ['MD 45', 'MS 35', 'WD C', 'WS C', 'XD 35', 'XD 55', 'XD A']:
        assignments[code] = {'format': 'round_robin'}

    # Elimination (remaining >5 entries)
    for code in ['MD B', 'MD C', 'MS A', 'MS B', 'MS C', 'XD B']:
        if code not in assignments:
            assignments[code] = {'format': 'elimination'}

    # Print plan
    print(f"\nFormat assignments:")
    for code in sorted(assignments.keys()):
        a = assignments[code]
        n = entries[code].get('player_count', len(entries[code].get('players', [])))
        if a['format'] == 'group_playoff':
            gs = a['group_sizes']
            pe = a.get('playoff_entries', len(gs))
            group_m = sum(g * (g - 1) // 2 for g in gs)
            playoff_size = next_power_of_2(pe)
            # scheduled playoff matches = pe - 1 (byes not scheduled)
            playoff_m = pe - 1
            print(f"  {code:12s} ({n:2d}) group_playoff  groups={gs}  playoff_entries={pe}  -> {group_m} group + {playoff_m} playoff = {group_m + playoff_m} matches")
        elif a['format'] == 'round_robin':
            m = n * (n - 1) // 2
            print(f"  {code:12s} ({n:2d}) round_robin    -> {m} matches")
        else:
            m = n - 1
            print(f"  {code:12s} ({n:2d}) elimination    -> {m} matches")

    result = run_scenario("2-group variation", assignments, entries, config, venue_model)


if __name__ == '__main__':
    main()
