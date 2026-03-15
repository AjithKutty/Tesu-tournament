"""Import service — wraps existing parse_tournament and parse_web modules."""

from __future__ import annotations

import json
import os
import sys

SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

BASE_DIR = os.path.dirname(SRC_DIR)
DIVISIONS_DIR = os.path.join(BASE_DIR, "output", "divisions")


def import_excel(filepath: str) -> dict:
    """Import from Excel file using parse_tournament.main()."""
    from parse_tournament import main as parse_excel_main
    parse_excel_main(filepath=filepath)
    return _read_import_summary()


def import_web(url: str, full_results: bool = False) -> dict:
    """Import from web URL using parse_web.main()."""
    from parse_web import main as parse_web_main
    parse_web_main(url=url, full_results=full_results)
    return _read_import_summary()


def _read_import_summary() -> dict:
    """Read the generated division files and return a summary."""
    index_path = os.path.join(DIVISIONS_DIR, "tournament_index.json")
    if not os.path.isfile(index_path):
        raise FileNotFoundError("Tournament index not found after import")

    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    # Collect division summaries and count players
    divisions = []
    all_players = set()
    match_count = 0

    for entry in index.get("divisions", []):
        div_path = os.path.join(DIVISIONS_DIR, entry["file"])
        if not os.path.isfile(div_path):
            continue

        with open(div_path, encoding="utf-8") as f:
            data = json.load(f)

        divisions.append({
            "code": data.get("code", ""),
            "name": data.get("name", ""),
            "category": data.get("category", ""),
        })

        # Count players
        for player in data.get("players", []):
            name = player.get("name", "")
            if name:
                all_players.add(name)
            for sub in player.get("players", []):
                if sub.get("name"):
                    all_players.add(sub["name"])

        # Count matches
        for rnd in data.get("rounds", []):
            match_count += len(rnd.get("matches", []))
        match_count += len(data.get("matches", []))
        for group in data.get("groups", []):
            match_count += len(group.get("matches", []))
        playoff = data.get("playoff")
        if playoff:
            for rnd in playoff.get("rounds", []):
                match_count += len(rnd.get("matches", []))

    return {
        "tournament_name": index.get("tournament_name", ""),
        "division_count": len(divisions),
        "match_count": match_count,
        "player_count": len(all_players),
        "divisions": divisions,
    }
