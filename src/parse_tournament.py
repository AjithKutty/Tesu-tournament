"""
Parse the Kumpoo Tervasulan Eliitti 2025 tournament Excel file
and output structured JSON data — one file per division/sheet.

Usage:
    python src/parse_tournament.py

Reads:  Draws Kumpoo Tervasulan Eliitti 2025 vain kaaviot.XLSX
Writes: output/divisions/<SheetName>.json  (one per sheet)
        output/divisions/tournament_index.json  (summary index)
"""

import json
import re
import os
import openpyxl

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCEL_FILE = os.path.join(
    BASE_DIR,
    "Draws Kumpoo Tervasulan Eliitti 2025 vain kaaviot.XLSX",
)
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "divisions")

TOURNAMENT_NAME = "Kumpoo Tervasulan Eliitti 2025"

# ── Mapping helpers ──────────────────────────────────────────────

EVENT_NAMES = {
    "MS": "Men's Singles",
    "WS": "Women's Singles",
    "MD": "Men's Doubles",
    "WD": "Women's Doubles",
    "XD": "Mixed Doubles",
    "BS": "Boys' Singles",
    "BD": "Boys' Doubles",
}

LEVEL_CATEGORY = {
    "A": "Open A",
    "B": "Open B",
    "C": "Open C",
    "U11": "Junior",
    "U13": "Junior",
    "U15": "Junior",
    "U17": "Junior",
    "35": "Veterans",
    "45": "Veterans",
    "V": "Elite",
}

ROUND_NAMES = {
    "Round 1": "Round 1",
    "Round 2": "Round 2",
    "Quarterfinals": "Quarter-Final",
    "Semifinals": "Semi-Final",
    "Final": "Final",
}


def parse_sheet_name(name):
    """Parse sheet name like 'MS C-Main Draw' or 'BS U17-Playoff'."""
    m = re.match(r"^([A-Z]{2})\s+(.+?)-(Main Draw|Playoff)$", name)
    if not m:
        return None
    event_code = m.group(1)
    level = m.group(2)
    draw_type = m.group(3).lower().replace(" ", "_")
    category = LEVEL_CATEGORY.get(level, "Other")
    full_name = EVENT_NAMES.get(event_code, event_code)
    if level in ("35", "45"):
        full_name += f" {level}+"
    elif level == "V":
        full_name += " Elite"
    else:
        full_name += f" {level}"
    is_doubles = event_code in ("MD", "WD", "XD", "BD")
    return {
        "event_code": event_code,
        "level": level,
        "draw_type": draw_type,
        "category": category,
        "full_name": full_name,
        "code": f"{event_code} {level}",
        "is_doubles": is_doubles,
    }


def sheet_to_filename(sheet_name):
    """Convert sheet name to safe filename: 'MS C-Main Draw' -> 'MS_C-Main_Draw.json'."""
    return sheet_name.replace(" ", "_") + ".json"


def cell_val(cell):
    """Return stripped string value or None."""
    if cell.value is None:
        return None
    s = str(cell.value).strip()
    return s if s else None


def extract_seed(name):
    """Extract seeding from name like 'Player Name [1]' or '[3/4]'."""
    m = re.search(r"\[(\d+(?:/\d+)?)\]", name)
    if m:
        clean_name = re.sub(r"\s*\[\d+(?:/\d+)?\]\s*", "", name).strip()
        return clean_name, m.group(1)
    return name, None


def read_sheet_rows(ws):
    """Read all rows from worksheet, returning list of dicts keyed by column letter."""
    rows = []
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        row_data = {"_row": row[0].row}
        for c in row:
            v = cell_val(c)
            if v is not None:
                row_data[c.column_letter] = v
        rows.append(row_data)
    return rows


# ── Format detection ─────────────────────────────────────────────

def detect_format(rows):
    """Detect sheet format: 'elimination', 'round_robin', or 'group_playoff'."""
    for r in rows:
        a_val = r.get("A", "")
        if re.match(r"^[A-Z]{2}\s+.+- Group [A-Z]$", a_val):
            return "group_playoff"
    for r in rows:
        e_val = r.get("E", "")
        if e_val in ("Round 1", "Quarterfinals", "Semifinals", "Final"):
            return "elimination"
    for r in rows:
        if r.get("F") in ("1", "2") and r.get("B") == "St.":
            return "round_robin"
    for r in rows:
        if r.get("B") == "Standings":
            return "round_robin"
    return "elimination"


# ── Player extraction ────────────────────────────────────────────

def parse_doubles_names(name_str, club_str):
    """Parse doubles pair from newline-separated names/clubs."""
    names = [n.strip() for n in name_str.split("\n") if n.strip()]
    clubs = [c.strip() for c in (club_str or "").split("\n") if c.strip()]
    players = []
    for i, n in enumerate(names):
        clean, seed = extract_seed(n)
        players.append({
            "name": clean,
            "club": clubs[i] if i < len(clubs) else None,
            "seed": seed,
        })
    return players


def extract_elimination_players(rows, is_doubles):
    """Extract players/pairs from elimination-style draw. Returns list + draw_size."""
    players = []
    data_rows = [r for r in rows if r["_row"] >= 5]
    max_pos = 0

    if is_doubles:
        prev_row = None
        for r in data_rows:
            a_val = r.get("A")
            e_val = r.get("E")
            if a_val and a_val.isdigit():
                pos = int(a_val)
                max_pos = max(max_pos, pos)
                if e_val and e_val.lower() != "bye":
                    name1_raw = prev_row.get("E", "") if prev_row else ""
                    club1 = prev_row.get("C", "") if prev_row else ""
                    name2_raw = e_val
                    club2 = r.get("C", "")
                    status1 = prev_row.get("B") if prev_row else None
                    status2 = r.get("B")
                    status = status1 or status2

                    name1, seed1 = extract_seed(name1_raw) if name1_raw else ("", None)
                    name2, seed2 = extract_seed(name2_raw)
                    seed = seed1 or seed2

                    if name1:
                        pair = [
                            {"name": name1, "club": club1},
                            {"name": name2, "club": club2},
                        ]
                        players.append({
                            "position": pos,
                            "players": pair,
                            "seed": seed,
                            "status": status,
                        })
                prev_row = None
            else:
                prev_row = r if r.get("E") else None
    else:
        for r in data_rows:
            a_val = r.get("A")
            e_val = r.get("E")
            if a_val and a_val.isdigit():
                pos = int(a_val)
                max_pos = max(max_pos, pos)
                if e_val and e_val.lower() != "bye":
                    name, seed = extract_seed(e_val)
                    players.append({
                        "position": pos,
                        "name": name,
                        "club": r.get("C"),
                        "seed": seed,
                        "status": r.get("B"),
                    })

    return players, max_pos


def extract_roundrobin_players(rows, is_doubles):
    """Extract players from round-robin draw."""
    players = []
    for r in rows:
        if r.get("B") == "Standings":
            break
        a_val = r.get("A")
        e_val = r.get("E")
        if a_val and a_val.isdigit() and e_val:
            pos = int(a_val)
            if is_doubles and "\n" in e_val:
                pair = parse_doubles_names(e_val, r.get("C"))
                seed = None
                for p in pair:
                    if p["seed"]:
                        seed = p["seed"]
                        break
                players.append({
                    "position": pos,
                    "players": pair,
                    "seed": seed,
                    "status": r.get("B"),
                })
            else:
                name, seed = extract_seed(e_val)
                if name.lower() != "bye":
                    players.append({
                        "position": pos,
                        "name": name,
                        "club": r.get("C"),
                        "seed": seed,
                        "status": r.get("B"),
                    })
    return players


def extract_group_playoff(rows, is_doubles):
    """Extract groups from group+playoff format."""
    groups = []
    current_group = None

    for r in rows:
        a_val = r.get("A", "")
        if re.match(r"^[A-Z]{2}\s+.+- Group [A-Z]$", a_val):
            if current_group:
                groups.append(current_group)
            group_letter = a_val[-1]
            current_group = {"name": f"Group {group_letter}", "players": []}
            continue

        if current_group is None:
            continue

        if r.get("B") == "Standings":
            groups.append(current_group)
            current_group = None
            continue

        e_val = r.get("E")
        if a_val.isdigit() and e_val:
            pos = int(a_val)
            if is_doubles and "\n" in e_val:
                pair = parse_doubles_names(e_val, r.get("C"))
                seed = None
                for p in pair:
                    if p["seed"]:
                        seed = p["seed"]
                        break
                current_group["players"].append({
                    "position": pos,
                    "players": pair,
                    "seed": seed,
                    "status": r.get("B"),
                })
            else:
                name, seed = extract_seed(e_val)
                if name.lower() != "bye":
                    current_group["players"].append({
                        "position": pos,
                        "name": name,
                        "club": r.get("C"),
                        "seed": seed,
                        "status": r.get("B"),
                    })

    if current_group:
        groups.append(current_group)

    return groups


# ── Bracket / match generation ───────────────────────────────────

def get_round_headers(rows):
    """Extract ordered round names from header row (row with B='St.')."""
    for r in rows:
        if r.get("B") == "St.":
            rounds = []
            for col in sorted(r.keys()):
                if col in ("A", "B", "C", "D", "_row"):
                    continue
                val = r[col]
                if val in ROUND_NAMES:
                    rounds.append(ROUND_NAMES[val])
                elif val == "Winner":
                    continue
            return rounds
    return []


def player_label(player_entry, is_doubles):
    """Get display label for a player/pair entry."""
    if is_doubles:
        names = [p["name"] for p in player_entry.get("players", [])]
        return " / ".join(names)
    return player_entry.get("name", "")


def build_full_bracket(players, draw_size, round_names, is_doubles):
    """
    Build the full bracket structure for all rounds.

    Round 1: actual players from draw positions, paired (1v2, 3v4, ...).
    Later rounds: structural placeholders ('Winner R1-M1 vs Winner R1-M2').
    Bye positions (no player) result in auto-advance for the opponent.
    """
    # Build a position -> player map
    pos_map = {}
    for p in players:
        pos_map[p["position"]] = p

    # Round 1: pair adjacent draw positions
    r1_matches = []
    for i in range(1, draw_size + 1, 2):
        p1 = pos_map.get(i)
        p2 = pos_map.get(i + 1)

        p1_label = player_label(p1, is_doubles) if p1 else "Bye"
        p2_label = player_label(p2, is_doubles) if p2 else "Bye"

        match = {
            "match": len(r1_matches) + 1,
            "player1": p1_label,
            "player2": p2_label,
        }

        # Determine auto-advance
        if p1_label == "Bye" and p2_label != "Bye":
            match["notes"] = f"{p2_label} auto-advances"
        elif p2_label == "Bye" and p1_label != "Bye":
            match["notes"] = f"{p1_label} auto-advances"
        elif p1_label == "Bye" and p2_label == "Bye":
            match["notes"] = "Empty slot"

        r1_matches.append(match)

    if not round_names:
        return [{"name": "Round 1", "matches": r1_matches}] if r1_matches else []

    rounds = [{"name": round_names[0], "matches": r1_matches}]

    # Later rounds: structural matches
    prev_round_name = round_names[0]
    prev_match_count = len(r1_matches)
    abbrev_map = {
        "Round 1": "R1",
        "Round 2": "R2",
        "Quarter-Final": "QF",
        "Semi-Final": "SF",
        "Final": "F",
    }

    for rnd_idx in range(1, len(round_names)):
        rnd_name = round_names[rnd_idx]
        prev_abbrev = abbrev_map.get(prev_round_name, prev_round_name[:2])
        num_matches = prev_match_count // 2
        if num_matches < 1:
            break

        matches = []
        for m in range(num_matches):
            m1 = m * 2 + 1
            m2 = m * 2 + 2
            matches.append({
                "match": m + 1,
                "player1": f"Winner {prev_abbrev}-M{m1}",
                "player2": f"Winner {prev_abbrev}-M{m2}",
            })

        rounds.append({"name": rnd_name, "matches": matches})
        prev_round_name = rnd_name
        prev_match_count = num_matches

    return rounds


def build_playoff_bracket(rows, is_doubles):
    """Build bracket structure for a playoff sheet (positions may be empty — just slots)."""
    round_names = get_round_headers(rows)
    # Get draw positions
    data_rows = [r for r in rows if r["_row"] >= 5]
    positions = []
    for r in data_rows:
        a_val = r.get("A")
        if a_val and a_val.isdigit():
            positions.append(int(a_val))
    draw_size = max(positions) if positions else 0

    if draw_size == 0:
        return None

    # For playoffs, positions are typically empty (filled from group results)
    # Build structural bracket with slot labels
    if not round_names:
        return None

    # First round: pair adjacent slots
    first_round_matches = []
    for i in range(1, draw_size + 1, 2):
        first_round_matches.append({
            "match": len(first_round_matches) + 1,
            "player1": f"Slot {i}",
            "player2": f"Slot {i + 1}",
        })

    rounds = [{"name": round_names[0], "matches": first_round_matches}]

    # Later rounds
    abbrev_map = {
        "Round 1": "R1", "Round 2": "R2",
        "Quarter-Final": "QF", "Semi-Final": "SF", "Final": "F",
    }
    prev_name = round_names[0]
    prev_count = len(first_round_matches)

    for rnd_idx in range(1, len(round_names)):
        rnd_name = round_names[rnd_idx]
        prev_abbrev = abbrev_map.get(prev_name, prev_name[:2])
        num_matches = prev_count // 2
        if num_matches < 1:
            break
        matches = []
        for m in range(num_matches):
            matches.append({
                "match": m + 1,
                "player1": f"Winner {prev_abbrev}-M{m * 2 + 1}",
                "player2": f"Winner {prev_abbrev}-M{m * 2 + 2}",
            })
        rounds.append({"name": rnd_name, "matches": matches})
        prev_name = rnd_name
        prev_count = num_matches

    return {
        "format": "elimination",
        "drawSize": draw_size,
        "rounds": rounds,
    }


def generate_roundrobin_matches(players, is_doubles):
    """Generate all-vs-all match pairings for round-robin."""
    matches = []
    match_num = 1
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            p1 = players[i]
            p2 = players[j]
            name1 = player_label(p1, is_doubles)
            name2 = player_label(p2, is_doubles)
            matches.append({
                "match": match_num,
                "player1": name1,
                "player2": name2,
            })
            match_num += 1
    return matches


# ── Club collection helper ───────────────────────────────────────

def collect_clubs(players, is_doubles):
    """Collect unique club names from a player list."""
    clubs = set()
    for p in players:
        if is_doubles:
            for partner in p.get("players", []):
                if partner.get("club"):
                    clubs.add(partner["club"])
        else:
            if p.get("club"):
                clubs.add(p["club"])
    return clubs


# ── Main processing ──────────────────────────────────────────────

def process_workbook(filepath):
    wb = openpyxl.load_workbook(filepath, data_only=True)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # First pass: process all sheets and collect data
    sheet_data = {}
    all_clubs = set()

    for sheet_name in wb.sheetnames:
        info = parse_sheet_name(sheet_name)
        if not info:
            continue

        ws = wb[sheet_name]
        rows = read_sheet_rows(ws)
        fmt = detect_format(rows)

        sheet_data[sheet_name] = {
            "info": info,
            "rows": rows,
            "format": fmt,
        }

    # Second pass: build division JSON and link playoffs to main draws
    index_entries = []
    playoff_data = {}  # key: "EVENT LEVEL" -> playoff bracket dict

    # Process playoff sheets first
    for sheet_name, sd in sheet_data.items():
        info = sd["info"]
        if info["draw_type"] != "playoff":
            continue

        rows = sd["rows"]
        bracket = build_playoff_bracket(rows, info["is_doubles"])
        if bracket:
            playoff_data[info["code"]] = bracket

        # Write standalone playoff JSON
        filename = sheet_to_filename(sheet_name)
        division_json = {
            "tournament": TOURNAMENT_NAME,
            "name": f"{info['full_name']} Playoff",
            "code": info["code"],
            "category": info["category"],
            "sheet": sheet_name,
            "draw_type": "playoff",
            "format": "elimination",
            "linked_main_draw": sheet_to_filename(
                sheet_name.replace("-Playoff", "-Main Draw")
            ),
        }
        if bracket:
            division_json["drawSize"] = bracket["drawSize"]
            division_json["rounds"] = bracket["rounds"]
        else:
            division_json["drawSize"] = 0
            division_json["rounds"] = []

        outpath = os.path.join(OUTPUT_DIR, filename)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(division_json, f, indent=2, ensure_ascii=False)

        index_entries.append({
            "file": filename,
            "name": division_json["name"],
            "code": info["code"],
            "category": info["category"],
            "draw_type": "playoff",
            "format": "elimination",
        })

    # Process main draw sheets
    for sheet_name, sd in sheet_data.items():
        info = sd["info"]
        if info["draw_type"] != "main_draw":
            continue

        rows = sd["rows"]
        fmt = sd["format"]
        filename = sheet_to_filename(sheet_name)
        is_doubles = info["is_doubles"]

        division_json = {
            "tournament": TOURNAMENT_NAME,
            "name": info["full_name"],
            "code": info["code"],
            "category": info["category"],
            "sheet": sheet_name,
            "draw_type": "main_draw",
            "format": fmt,
        }

        div_clubs = set()

        if fmt == "elimination":
            players, draw_size = extract_elimination_players(rows, is_doubles)
            round_names = get_round_headers(rows)
            rounds = build_full_bracket(players, draw_size, round_names, is_doubles)

            division_json["drawSize"] = draw_size
            division_json["players"] = players
            division_json["rounds"] = rounds
            div_clubs = collect_clubs(players, is_doubles)

        elif fmt == "round_robin":
            players = extract_roundrobin_players(rows, is_doubles)
            matches = generate_roundrobin_matches(players, is_doubles)

            division_json["players"] = players
            division_json["matches"] = matches
            div_clubs = collect_clubs(players, is_doubles)

        elif fmt == "group_playoff":
            groups = extract_group_playoff(rows, is_doubles)
            for g in groups:
                g["matches"] = generate_roundrobin_matches(g["players"], is_doubles)
                div_clubs |= collect_clubs(g["players"], is_doubles)

            division_json["groups"] = groups

            # Link playoff bracket if exists
            if info["code"] in playoff_data:
                division_json["playoff"] = playoff_data[info["code"]]
                playoff_file = sheet_to_filename(
                    sheet_name.replace("-Main Draw", "-Playoff")
                )
                division_json["playoff_file"] = playoff_file

        division_json["clubs"] = sorted(div_clubs)
        all_clubs |= div_clubs

        outpath = os.path.join(OUTPUT_DIR, filename)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(division_json, f, indent=2, ensure_ascii=False)

        index_entries.append({
            "file": filename,
            "name": info["full_name"],
            "code": info["code"],
            "category": info["category"],
            "draw_type": "main_draw",
            "format": fmt,
        })

    # Write tournament index
    cat_order = ["Open A", "Open B", "Open C", "Junior", "Veterans", "Elite"]
    # Sort index by category order, then by code
    def sort_key(e):
        cat_idx = cat_order.index(e["category"]) if e["category"] in cat_order else 99
        return (cat_idx, e["code"], 0 if e["draw_type"] == "main_draw" else 1)

    index_entries.sort(key=sort_key)

    index_json = {
        "tournament": TOURNAMENT_NAME,
        "total_divisions": len(index_entries),
        "clubs": sorted(all_clubs),
        "divisions": index_entries,
    }

    index_path = os.path.join(OUTPUT_DIR, "tournament_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_json, f, indent=2, ensure_ascii=False)

    return index_json, len(index_entries)


def main():
    print(f"Reading: {EXCEL_FILE}")
    print(f"Output:  {OUTPUT_DIR}/\n")

    index, count = process_workbook(EXCEL_FILE)

    print(f"Generated {count} JSON files + tournament_index.json")
    print(f"Total clubs: {len(index['clubs'])}\n")

    # Summary by category
    from collections import defaultdict
    by_cat = defaultdict(list)
    for d in index["divisions"]:
        by_cat[d["category"]].append(d)

    for cat in ["Open A", "Open B", "Open C", "Junior", "Veterans", "Elite"]:
        divs = by_cat.get(cat, [])
        if divs:
            print(f"  {cat}: {len(divs)} files")
            for d in divs:
                tag = f"[{d['format']}]"
                draw_type = " (playoff)" if d["draw_type"] == "playoff" else ""
                print(f"    {d['file']:40s} {tag:20s}{draw_type}")

    print(f"\nAll files written to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
