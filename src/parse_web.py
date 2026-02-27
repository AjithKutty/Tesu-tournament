"""
Scrape tournament draw data from tournamentsoftware.com and output
structured JSON data — one file per division, identical format to
parse_tournament.py's Excel-based output.

Usage:
    python src/parse_web.py "https://badmintonfinland.tournamentsoftware.com/sport/draws.aspx?id=48aae77a-..."

    # With match results:
    python src/parse_web.py --full-results "https://..."

Writes: output/divisions/<DivisionCode>.json  (one per division)
        output/divisions/tournament_index.json
"""

import json
import re
import os
import sys
import time
import argparse
import math

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "divisions")

REQUEST_DELAY = 0.5  # seconds between requests

# ── Mapping helpers (mirrored from parse_tournament.py) ─────────

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


def extract_seed(name):
    """Extract seeding from name like 'Player Name [1]' or '[3/4]'."""
    m = re.search(r"\[(\d+(?:/\d+)?)\]", name)
    if m:
        clean_name = re.sub(r"\s*\[\d+(?:/\d+)?\]\s*", "", name).strip()
        return clean_name, m.group(1)
    return name, None


def clean_player_name(raw):
    """Strip country codes like [FIN] and extract seed. Returns (name, seed)."""
    # Remove country codes: [FIN], [SWE], [GER], etc.
    text = re.sub(r"\s*\[[A-Z]{2,3}\]\s*", " ", raw).strip()
    return extract_seed(text)


def player_label(player_entry, is_doubles):
    """Get display label for a player/pair entry."""
    if is_doubles:
        names = [p["name"] for p in player_entry.get("players", [])]
        return " / ".join(names)
    return player_entry.get("name", "")


# ── Round name helpers ──────────────────────────────────────────

def round_names_for_size(draw_size):
    """Derive round name sequence from draw size."""
    num_rounds = int(math.log2(draw_size)) if draw_size > 0 else 0
    names = []
    for i in range(num_rounds):
        remaining = num_rounds - i
        if remaining == 1:
            names.append("Final")
        elif remaining == 2:
            names.append("Semi-Final")
        elif remaining == 3:
            names.append("Quarter-Final")
        else:
            names.append(f"Round {i + 1}")
    return names


ABBREV_MAP = {
    "Round 1": "R1",
    "Round 2": "R2",
    "Quarter-Final": "QF",
    "Semi-Final": "SF",
    "Final": "F",
}


# ── Web scraping functions ──────────────────────────────────────

def _get(session, url):
    """GET with delay and cookie-wall retry."""
    time.sleep(REQUEST_DELAY)
    resp = session.get(url)
    # If redirected to cookie wall, re-bypass
    if "/cookiewall/" in resp.url:
        base_url = re.match(r"(https?://[^/]+)", url).group(1)
        return_url = url.replace(base_url, "")
        session.post(
            f"{base_url}/cookiewall/Save",
            data={
                "ReturnUrl": return_url,
                "SettingsOpen": "false",
                "CookiePurposes": ["1", "2", "4", "16"],
            },
        )
        time.sleep(REQUEST_DELAY)
        resp = session.get(url)
    return resp


def bypass_cookiewall(session, base_url, target_path):
    """Accept all cookies on the tournamentsoftware.com cookie wall."""
    url = base_url + target_path
    resp = session.get(url, allow_redirects=True)
    if "/cookiewall/" in resp.url:
        session.post(
            f"{base_url}/cookiewall/Save",
            data={
                "ReturnUrl": target_path,
                "SettingsOpen": "false",
                "CookiePurposes": ["1", "2", "4", "16"],
            },
            allow_redirects=True,
        )


def parse_url(url):
    """Extract base_url and tournament_id from a tournamentsoftware.com URL."""
    m = re.match(r"(https?://[^/]+)", url)
    if not m:
        raise ValueError(f"Invalid URL: {url}")
    base_url = m.group(1)

    m2 = re.search(r"[?&]id=([0-9a-fA-F-]+)", url)
    if not m2:
        raise ValueError(f"No tournament ID found in URL: {url}")
    tournament_id = m2.group(1)

    return base_url, tournament_id


def extract_tournament_name(session, base_url, tournament_id):
    """Fetch tournament name from the draws page heading."""
    resp = _get(session, f"{base_url}/sport/draws.aspx?id={tournament_id}")
    soup = BeautifulSoup(resp.text, "lxml")
    # Tournament name is typically in the second <h2>
    headings = soup.find_all("h2")
    for h in headings:
        text = h.get_text(strip=True)
        # Skip the full page title that includes "Badminton Finland - ..."
        if text and "Badminton Finland" not in text:
            return text
    # Fallback: parse from title tag
    title = soup.find("title")
    if title:
        parts = title.get_text().split("-")
        if len(parts) >= 2:
            return parts[1].strip().split("-")[0].strip()
    return "Unknown Tournament"


def fetch_draw_list(session, base_url, tournament_id):
    """Scrape draws.aspx and return list of {draw_num, name}."""
    resp = _get(session, f"{base_url}/sport/draws.aspx?id={tournament_id}")
    soup = BeautifulSoup(resp.text, "lxml")

    draws = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"draw=(\d+)", href)
        if m and "draw.aspx" in href:
            draw_num = int(m.group(1))
            name = a.get_text(strip=True)
            if name:
                draws.append({"draw_num": draw_num, "name": name})

    return draws


def group_draws_by_division(draw_list):
    """
    Group flat draw list into logical divisions.

    Returns dict keyed by division base name:
      "BS U17": {"type": "group_playoff", "groups": [...], "playoff": {...}}
      "MS A":   {"type": "standalone", "draw": {...}}
    """
    # First pass: identify group draws
    group_bases = {}  # base_name -> list of group draws
    non_group = []

    for draw in draw_list:
        m = re.match(r"^(.+?)\s*-\s*Group\s+([A-Z])$", draw["name"])
        if m:
            base_name = m.group(1).strip()
            letter = m.group(2)
            if base_name not in group_bases:
                group_bases[base_name] = []
            group_bases[base_name].append({**draw, "letter": letter})
        else:
            non_group.append(draw)

    divisions = {}

    # Create group_playoff entries
    for base_name, groups in group_bases.items():
        groups.sort(key=lambda g: g["letter"])
        divisions[base_name] = {
            "type": "group_playoff",
            "groups": groups,
            "playoff": None,
        }

    # Assign playoff draws and standalone draws
    for draw in non_group:
        name = draw["name"]
        if name in divisions and divisions[name]["type"] == "group_playoff":
            # This is the playoff draw for a group_playoff division
            divisions[name]["playoff"] = draw
        else:
            divisions[name] = {"type": "standalone", "draw": draw}

    return divisions


def fetch_draw_meta(session, base_url, tournament_id, draw_num):
    """Fetch format info and draw size from draw.aspx."""
    resp = _get(
        session,
        f"{base_url}/sport/draw.aspx?id={tournament_id}&draw={draw_num}",
    )
    soup = BeautifulSoup(resp.text, "lxml")

    format_text = ""
    draw_size = 0

    # Look for tags with format and size info
    for span in soup.find_all("span", class_="tag"):
        text = span.get_text(strip=True)
        # "Cup-kaavio" = elimination, "Lohko" = pool/round-robin (Finnish)
        if any(kw in text.lower() for kw in ("kaavio", "cup", "pool", "lohko")):
            format_text = text
        size_m = re.match(r"Size\s+(\d+)", text)
        if size_m:
            draw_size = int(size_m.group(1))

    # Also get player list from autosuggest
    players = []
    for li in soup.find_all("li", attrs={"data-asg-title": True}):
        players.append(li["data-asg-title"])

    return {
        "format_text": format_text,
        "draw_size": draw_size,
        "players": players,
    }


def fetch_draw_matches(session, base_url, tournament_id, draw_num, is_doubles):
    """
    Scrape drawmatches.aspx and return list of parsed match dicts.

    Each match dict:
      player1: list of name strings (1 for singles, 2 for doubles)
      player2: list of name strings
      seed1: str or None
      seed2: str or None
      time: scheduled time string or None
      court: court string or None
      result: result string or None
      duration: duration string or None
    """
    resp = _get(
        session,
        f"{base_url}/sport/drawmatches.aspx?id={tournament_id}&draw={draw_num}",
    )
    soup = BeautifulSoup(resp.text, "lxml")

    table = soup.find("table", class_="matches")
    if not table:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    matches = []
    # State machine: accumulate rows per match
    # A new match starts at a row that has a .plannedtime cell
    current_rows = []

    for row in rows[1:]:  # skip header row
        cells = row.find_all("td")
        if not cells:
            continue

        # Check if this row starts a new match (has plannedtime cell)
        has_time = any(
            "plannedtime" in " ".join(td.get("class", []))
            for td in cells
        )

        if has_time:
            # Process previous match
            if current_rows:
                match = _parse_match_rows(current_rows, is_doubles)
                if match:
                    matches.append(match)
            current_rows = [cells]
        else:
            current_rows.append(cells)

    # Process last match
    if current_rows:
        match = _parse_match_rows(current_rows, is_doubles)
        if match:
            matches.append(match)

    return matches


def _parse_match_rows(rows_of_cells, is_doubles):
    """
    Parse a group of table rows belonging to one match.

    Row 0 (main row): has plannedtime, player names, result, duration, court
    Subsequent rows: detail rows with individual player names
    """
    if not rows_of_cells:
        return None

    main_cells = rows_of_cells[0]

    # Extract planned time (use space separator to avoid "la 5.4.20259.00")
    match_time = None
    for td in main_cells:
        if "plannedtime" in " ".join(td.get("class", [])):
            match_time = td.get_text(" ", strip=True)
            break

    # Extract all text from main row cells (use space separator for multi-element cells)
    cell_texts = [td.get_text(" ", strip=True) for td in main_cells]

    # Find the separator "-" between player1 side and player2 side
    sep_idx = None
    for i, text in enumerate(cell_texts):
        if text == "-":
            sep_idx = i
            break

    if sep_idx is None:
        return None

    # Player names are in the detail rows (more reliable)
    # Main row has concatenated text that's harder to parse
    # Detail rows: each has 2 cells — [name, country] or [country, name]
    detail_rows = rows_of_cells[1:]

    player1_names = []
    player2_names = []
    seed1 = None
    seed2 = None

    if is_doubles:
        # Doubles: 4 detail rows (2 per side)
        # First 2 rows: player1 side, last 2 rows: player2 side
        p1_rows = detail_rows[:2]
        p2_rows = detail_rows[2:4]

        for row_cells in p1_rows:
            texts = [td.get_text(strip=True) for td in row_cells]
            name = _extract_name_from_detail_row(texts)
            if name:
                clean, seed = clean_player_name(name)
                if seed:
                    seed1 = seed
                player1_names.append(clean)

        for row_cells in p2_rows:
            texts = [td.get_text(strip=True) for td in row_cells]
            name = _extract_name_from_detail_row(texts)
            if name:
                clean, seed = clean_player_name(name)
                if seed:
                    seed2 = seed
                player2_names.append(clean)
    else:
        # Singles: 2 detail rows (1 per side)
        if len(detail_rows) >= 1:
            texts = [td.get_text(strip=True) for td in detail_rows[0]]
            name = _extract_name_from_detail_row(texts)
            if name:
                clean, seed = clean_player_name(name)
                seed1 = seed
                player1_names = [clean]

        if len(detail_rows) >= 2:
            texts = [td.get_text(strip=True) for td in detail_rows[1]]
            name = _extract_name_from_detail_row(texts)
            if name:
                clean, seed = clean_player_name(name)
                seed2 = seed
                player2_names = [clean]

    # If detail rows didn't give us names, fall back to main row parsing
    if not player1_names or not player2_names:
        p1_names, p2_names, s1, s2 = _parse_players_from_main_row(
            cell_texts, sep_idx, is_doubles
        )
        if not player1_names:
            player1_names = p1_names
            seed1 = s1
        if not player2_names:
            player2_names = p2_names
            seed2 = s2

    if not player1_names and not player2_names:
        return None

    # Extract result, duration, court from main row
    # These are typically after the player2 cells
    result = None
    duration = None
    court = None

    # Result is usually right after player2 country code
    # Duration contains 'm' or 'h'
    # Court contains venue name
    for i, text in enumerate(cell_texts):
        if i <= sep_idx:
            continue
        if not text:
            continue
        # Score pattern: digits with dashes
        if re.match(r"^\d+-\d+", text):
            result = text
        # Walkover
        elif text.lower() in ("luovutusvoitto", "walkover", "w.o."):
            result = "Walkover"
        # Duration: contains 'm' for minutes
        elif re.search(r"\d+m$", text) or re.search(r"\d+h\s*\d+m$", text):
            duration = text
        # Court: contains "Nallisport" or similar venue name, or just a dash-separated string
        elif "-" in text and not re.match(r"^\[", text) and len(text) > 5:
            court = text

    return {
        "player1": player1_names,
        "player2": player2_names,
        "seed1": seed1,
        "seed2": seed2,
        "time": match_time,
        "court": court,
        "result": result,
        "duration": duration,
    }


def _extract_name_from_detail_row(texts):
    """Extract player name from a detail row's cell texts.

    Detail rows come in two forms:
      [name, country_code]  — player1 side
      [country_code, name]  — player2 side
    """
    if not texts:
        return None
    # Filter out empty and country-code-only texts
    non_empty = [t for t in texts if t]
    if not non_empty:
        return None

    for t in non_empty:
        # Skip pure country codes like [FIN]
        if re.match(r"^\[[A-Z]{2,3}\]$", t):
            continue
        # This should be the name (possibly with seed and/or country code)
        return t
    return None


def _parse_players_from_main_row(cell_texts, sep_idx, is_doubles):
    """Fallback: extract player names from the main match row."""
    # Cells before sep_idx (after empty and time cells) are player1 side
    # Cells after sep_idx are player2 side + result + duration + court
    p1_texts = []
    p2_texts = []

    for i, text in enumerate(cell_texts[:sep_idx]):
        if not text:
            continue
        # Skip time-like values
        if re.match(r"^[a-z]{2}\s+\d+\.\d+\.\d+", text):
            continue
        # Skip country codes
        if re.match(r"^\[[A-Z]{2,3}\]$", text):
            continue
        p1_texts.append(text)

    for i, text in enumerate(cell_texts[sep_idx + 1:]):
        if not text:
            continue
        if re.match(r"^\[[A-Z]{2,3}\]$", text):
            continue
        # Stop at score/result
        if re.match(r"^\d+-\d+", text):
            break
        if text.lower() in ("luovutusvoitto", "walkover", "w.o."):
            break
        p2_texts.append(text)

    p1_names = []
    p2_names = []
    seed1 = None
    seed2 = None

    for t in p1_texts:
        name, seed = clean_player_name(t)
        if name:
            p1_names.append(name)
            if seed:
                seed1 = seed

    for t in p2_texts:
        name, seed = clean_player_name(t)
        if name:
            p2_names.append(name)
            if seed:
                seed2 = seed

    return p1_names, p2_names, seed1, seed2


def fetch_clubs(session, base_url, tournament_id):
    """Scrape clubs.aspx for club name list."""
    resp = _get(session, f"{base_url}/sport/clubs.aspx?id={tournament_id}")
    soup = BeautifulSoup(resp.text, "lxml")

    clubs = []
    table = soup.find("table")
    if table:
        for row in table.find_all("tr")[1:]:  # skip header
            cells = row.find_all("td")
            if cells:
                name = cells[0].get_text(strip=True)
                if name:
                    clubs.append(name)

    return sorted(clubs)


# ── Division name parsing ───────────────────────────────────────

def parse_draw_name(name):
    """Parse web draw name like 'MS A', 'BS U17', 'XD 35' into metadata dict."""
    m = re.match(r"^([A-Z]{2})\s+(.+)$", name)
    if not m:
        return None

    event_code = m.group(1)
    level = m.group(2).strip()

    if event_code not in EVENT_NAMES:
        return None
    if level not in LEVEL_CATEGORY:
        return None

    category = LEVEL_CATEGORY[level]
    full_name = EVENT_NAMES[event_code]

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
        "category": category,
        "full_name": full_name,
        "code": f"{event_code} {level}",
        "is_doubles": is_doubles,
    }


def division_to_filename(code, draw_type="main_draw"):
    """Generate filename matching Excel parser convention."""
    code_safe = code.replace(" ", "_")
    suffix = "Main_Draw" if draw_type == "main_draw" else "Playoff"
    return f"{code_safe}-{suffix}.json"


# ── Format-specific builders ────────────────────────────────────

def _group_matches_into_rounds(matches, is_doubles):
    """
    Group chronological matches into rounds by detecting player recurrence.

    When a match contains a player who already appeared in the current round,
    a new round boundary is detected.
    """
    if not matches:
        return []

    rounds_of_matches = [[]]
    seen_in_round = set()

    for match in matches:
        # Collect all player names in this match
        match_players = set()
        for side in ("player1", "player2"):
            for name in match.get(side, []):
                match_players.add(name)

        # If any player in this match already appeared in the current round,
        # we've crossed a round boundary
        if match_players & seen_in_round:
            rounds_of_matches.append([])
            seen_in_round = set()

        rounds_of_matches[-1].append(match)
        seen_in_round.update(match_players)

    return rounds_of_matches


def build_elimination_division(matches, draw_size, is_doubles, full_results):
    """
    Build players list and rounds structure from scraped elimination matches.

    Returns (players, rounds, draw_size).
    """
    if draw_size == 0:
        # Infer from match count: total matches = draw_size - 1
        draw_size = len(matches) + 1
        # Round up to next power of 2
        draw_size = 2 ** math.ceil(math.log2(max(draw_size, 2)))

    rnd_names = round_names_for_size(draw_size)
    if not rnd_names:
        return [], [], draw_size

    # Group matches into rounds by detecting player recurrence
    rounds_of_matches = _group_matches_into_rounds(matches, is_doubles)

    # Expected match counts per round (for structural placeholder generation)
    round_match_counts = []
    size = draw_size
    for _ in rnd_names:
        round_match_counts.append(size // 2)
        size //= 2

    # Extract players from Round 1 matches
    players = []
    r1_matches = rounds_of_matches[0] if rounds_of_matches else []
    pos = 1
    seen_names = set()

    for match in r1_matches:
        for side, seed_key in [("player1", "seed1"), ("player2", "seed2")]:
            names = match.get(side, [])
            seed = match.get(seed_key)

            if names and names[0].lower() != "bye":
                if is_doubles and len(names) >= 2:
                    pair_key = tuple(names)
                    if pair_key not in seen_names:
                        seen_names.add(pair_key)
                        players.append({
                            "position": pos,
                            "players": [
                                {"name": n, "club": None} for n in names
                            ],
                            "seed": seed,
                            "status": None,
                        })
                elif not is_doubles and names:
                    name = names[0]
                    if name not in seen_names:
                        seen_names.add(name)
                        players.append({
                            "position": pos,
                            "name": name,
                            "club": None,
                            "seed": seed,
                            "status": None,
                        })
            pos += 1

    # Build rounds array
    rounds = []
    for rnd_idx, rnd_name in enumerate(rnd_names):
        if rnd_idx < len(rounds_of_matches) and rounds_of_matches[rnd_idx]:
            # This round has actual match data
            scraped = rounds_of_matches[rnd_idx]
            round_matches = []
            for m_idx, match in enumerate(scraped):
                p1_label = _match_side_label(match["player1"], is_doubles)
                p2_label = _match_side_label(match["player2"], is_doubles)

                entry = {
                    "match": m_idx + 1,
                    "player1": p1_label,
                    "player2": p2_label,
                }

                # Auto-advance notes
                if p1_label == "Bye" and p2_label != "Bye":
                    entry["notes"] = f"{p2_label} auto-advances"
                elif p2_label == "Bye" and p1_label != "Bye":
                    entry["notes"] = f"{p1_label} auto-advances"

                # Optional full results
                if full_results:
                    if match.get("result"):
                        entry["result"] = match["result"]
                    if match.get("duration"):
                        entry["duration"] = match["duration"]
                    if match.get("time"):
                        entry["scheduled_time"] = match["time"]
                    if match.get("court"):
                        entry["court"] = match["court"]

                round_matches.append(entry)

            rounds.append({"name": rnd_name, "matches": round_matches})
        else:
            # Generate structural placeholders for unplayed rounds
            if rnd_idx == 0:
                # Round 1 with no data — generate from draw_size
                r1_slot_matches = []
                for m in range(draw_size // 2):
                    r1_slot_matches.append({
                        "match": m + 1,
                        "player1": f"Slot {m * 2 + 1}",
                        "player2": f"Slot {m * 2 + 2}",
                    })
                rounds.append({"name": rnd_name, "matches": r1_slot_matches})
            else:
                prev_name = rnd_names[rnd_idx - 1]
                prev_abbrev = ABBREV_MAP.get(prev_name, prev_name[:2])
                prev_count = len(rounds[-1]["matches"]) if rounds else round_match_counts[rnd_idx - 1]
                num_matches = prev_count // 2
                struct_matches = []
                for m in range(num_matches):
                    struct_matches.append({
                        "match": m + 1,
                        "player1": f"Winner {prev_abbrev}-M{m * 2 + 1}",
                        "player2": f"Winner {prev_abbrev}-M{m * 2 + 2}",
                    })
                rounds.append({"name": rnd_name, "matches": struct_matches})

    return players, rounds, draw_size


def _match_side_label(names, is_doubles):
    """Create display label from a list of player names."""
    if not names:
        return "Bye"
    if is_doubles:
        return " / ".join(names) if names else "Bye"
    return names[0] if names else "Bye"


def build_roundrobin_division(matches, is_doubles, full_results):
    """
    Build players list and matches list from scraped round-robin matches.

    Returns (players, rr_matches).
    """
    # Collect unique players in order of first appearance
    seen = []
    seen_set = set()

    for match in matches:
        for side, seed_key in [("player1", "seed1"), ("player2", "seed2")]:
            names = match.get(side, [])
            seed = match.get(seed_key)
            if not names:
                continue

            key = tuple(names) if is_doubles else names[0]
            if key not in seen_set:
                seen_set.add(key)
                seen.append((names, seed))

    # Build player entries
    players = []
    for pos, (names, seed) in enumerate(seen, start=1):
        if is_doubles and len(names) >= 2:
            players.append({
                "position": pos,
                "players": [{"name": n, "club": None} for n in names],
                "seed": seed,
                "status": None,
            })
        elif not is_doubles and names:
            players.append({
                "position": pos,
                "name": names[0],
                "club": None,
                "seed": seed,
                "status": None,
            })

    # Generate all-vs-all match list (mirrors generate_roundrobin_matches)
    rr_matches = []
    match_num = 1
    for i in range(len(players)):
        for j in range(i + 1, len(players)):
            p1_label = player_label(players[i], is_doubles)
            p2_label = player_label(players[j], is_doubles)
            entry = {
                "match": match_num,
                "player1": p1_label,
                "player2": p2_label,
            }

            # Try to find corresponding scraped match for full_results
            if full_results:
                scraped = _find_scraped_match(
                    matches, players[i], players[j], is_doubles
                )
                if scraped:
                    if scraped.get("result"):
                        entry["result"] = scraped["result"]
                    if scraped.get("duration"):
                        entry["duration"] = scraped["duration"]
                    if scraped.get("time"):
                        entry["scheduled_time"] = scraped["time"]
                    if scraped.get("court"):
                        entry["court"] = scraped["court"]

            rr_matches.append(entry)
            match_num += 1

    return players, rr_matches


def _find_scraped_match(scraped_matches, player_i, player_j, is_doubles):
    """Find the scraped match corresponding to two players."""
    if is_doubles:
        names_i = set(p["name"] for p in player_i.get("players", []))
        names_j = set(p["name"] for p in player_j.get("players", []))
    else:
        names_i = {player_i.get("name", "")}
        names_j = {player_j.get("name", "")}

    for m in scraped_matches:
        p1_set = set(m.get("player1", []))
        p2_set = set(m.get("player2", []))
        if (names_i == p1_set and names_j == p2_set) or \
           (names_i == p2_set and names_j == p1_set):
            return m
    return None


def build_playoff_bracket(draw_size, rnd_names=None):
    """Build structural playoff bracket with Slot N placeholders."""
    if draw_size == 0:
        return None

    if rnd_names is None:
        rnd_names = round_names_for_size(draw_size)

    if not rnd_names:
        return None

    # First round: pair adjacent slots
    first_round_matches = []
    for i in range(1, draw_size + 1, 2):
        first_round_matches.append({
            "match": len(first_round_matches) + 1,
            "player1": f"Slot {i}",
            "player2": f"Slot {i + 1}",
        })

    rounds = [{"name": rnd_names[0], "matches": first_round_matches}]

    # Later rounds: structural placeholders
    prev_name = rnd_names[0]
    prev_count = len(first_round_matches)

    for rnd_idx in range(1, len(rnd_names)):
        rnd_name = rnd_names[rnd_idx]
        prev_abbrev = ABBREV_MAP.get(prev_name, prev_name[:2])
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


# ── Main orchestration ──────────────────────────────────────────

def process_tournament(url, full_results=False):
    """
    Scrape a tournament from tournamentsoftware.com and write division JSON files.

    Returns (index_json, file_count).
    """
    base_url, tournament_id = parse_url(url)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    # Bypass cookie wall
    target_path = f"/sport/draws.aspx?id={tournament_id}"
    print("Bypassing cookie wall...")
    bypass_cookiewall(session, base_url, target_path)

    # Get tournament name
    tournament_name = extract_tournament_name(session, base_url, tournament_id)
    print(f"Tournament: {tournament_name}")

    # Fetch draw list
    print("Fetching draw list...")
    draw_list = fetch_draw_list(session, base_url, tournament_id)
    print(f"Found {len(draw_list)} draws")

    # Group into divisions
    divisions = group_draws_by_division(draw_list)
    print(f"Grouped into {len(divisions)} divisions")

    # Fetch clubs
    print("Fetching club list...")
    club_names = fetch_clubs(session, base_url, tournament_id)
    print(f"Found {len(club_names)} clubs")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    index_entries = []
    all_clubs = set(club_names)
    files_written = 0

    # Process each division
    for div_name, div_info in sorted(divisions.items()):
        info = parse_draw_name(div_name)
        if not info:
            print(f"  Skipping unrecognized draw: {div_name}")
            continue

        print(f"  Processing: {div_name} ({div_info['type']})")

        if div_info["type"] == "group_playoff":
            files_written += _process_group_playoff(
                session, base_url, tournament_id, tournament_name,
                info, div_info, full_results, index_entries,
            )
        else:
            files_written += _process_standalone(
                session, base_url, tournament_id, tournament_name,
                info, div_info["draw"], full_results, index_entries,
            )

    # Write tournament index
    cat_order = ["Open A", "Open B", "Open C", "Junior", "Veterans", "Elite"]

    def sort_key(e):
        cat_idx = cat_order.index(e["category"]) if e["category"] in cat_order else 99
        return (cat_idx, e["code"], 0 if e["draw_type"] == "main_draw" else 1)

    index_entries.sort(key=sort_key)

    index_json = {
        "tournament": tournament_name,
        "total_divisions": len(index_entries),
        "clubs": sorted(all_clubs),
        "divisions": index_entries,
    }

    index_path = os.path.join(OUTPUT_DIR, "tournament_index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_json, f, indent=2, ensure_ascii=False)

    files_written += 1  # count the index file
    return index_json, len(index_entries)


def _process_standalone(
    session, base_url, tournament_id, tournament_name,
    info, draw, full_results, index_entries,
):
    """Process a standalone elimination or round-robin division."""
    draw_num = draw["draw_num"]

    # Fetch metadata and matches
    meta = fetch_draw_meta(session, base_url, tournament_id, draw_num)
    matches = fetch_draw_matches(
        session, base_url, tournament_id, draw_num, info["is_doubles"]
    )

    # Detect format from draw.aspx metadata
    # "Cup-kaavio" / "Cup" = elimination, "Lohko" / "Pool" = round-robin
    format_text = meta.get("format_text", "").lower()
    draw_size = meta.get("draw_size", 0)

    if "cup" in format_text or "kaavio" in format_text:
        fmt = "elimination"
    elif "lohko" in format_text or "pool" in format_text:
        fmt = "round_robin"
    else:
        # Fallback heuristic
        fmt = "elimination"

    filename = division_to_filename(info["code"], "main_draw")

    division_json = {
        "tournament": tournament_name,
        "name": info["full_name"],
        "code": info["code"],
        "category": info["category"],
        "source": f"{base_url}/sport/drawmatches.aspx?id={tournament_id}&draw={draw_num}",
        "draw_type": "main_draw",
        "format": fmt,
    }

    if fmt == "elimination":
        players, rounds, ds = build_elimination_division(
            matches, draw_size, info["is_doubles"], full_results
        )
        division_json["drawSize"] = ds
        division_json["players"] = players
        division_json["rounds"] = rounds
    else:
        players, rr_matches = build_roundrobin_division(
            matches, info["is_doubles"], full_results
        )
        division_json["players"] = players
        division_json["matches"] = rr_matches

    division_json["clubs"] = []

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

    return 1


def _process_group_playoff(
    session, base_url, tournament_id, tournament_name,
    info, div_info, full_results, index_entries,
):
    """Process a group+playoff division."""
    files_written = 0

    # Build groups
    groups = []
    for group_draw in div_info["groups"]:
        draw_num = group_draw["draw_num"]
        letter = group_draw["letter"]
        matches = fetch_draw_matches(
            session, base_url, tournament_id, draw_num, info["is_doubles"]
        )
        players, rr_matches = build_roundrobin_division(
            matches, info["is_doubles"], full_results
        )
        groups.append({
            "name": f"Group {letter}",
            "players": players,
            "matches": rr_matches,
        })

    # Build playoff bracket
    playoff_bracket = None
    playoff_filename = None

    if div_info.get("playoff"):
        playoff_draw = div_info["playoff"]
        playoff_meta = fetch_draw_meta(
            session, base_url, tournament_id, playoff_draw["draw_num"]
        )
        playoff_draw_size = playoff_meta.get("draw_size", 0)

        if playoff_draw_size == 0:
            # Infer from match count on the playoff drawmatches page
            playoff_matches = fetch_draw_matches(
                session, base_url, tournament_id,
                playoff_draw["draw_num"], info["is_doubles"],
            )
            playoff_draw_size = len(playoff_matches) + 1
            playoff_draw_size = 2 ** math.ceil(
                math.log2(max(playoff_draw_size, 2))
            )

        playoff_bracket = build_playoff_bracket(playoff_draw_size)
        playoff_filename = division_to_filename(info["code"], "playoff")

        # Write standalone playoff JSON
        playoff_json = {
            "tournament": tournament_name,
            "name": f"{info['full_name']} Playoff",
            "code": info["code"],
            "category": info["category"],
            "source": f"{base_url}/sport/draw.aspx?id={tournament_id}&draw={playoff_draw['draw_num']}",
            "draw_type": "playoff",
            "format": "elimination",
            "linked_main_draw": division_to_filename(info["code"], "main_draw"),
        }
        if playoff_bracket:
            playoff_json["drawSize"] = playoff_bracket["drawSize"]
            playoff_json["rounds"] = playoff_bracket["rounds"]
        else:
            playoff_json["drawSize"] = 0
            playoff_json["rounds"] = []

        outpath = os.path.join(OUTPUT_DIR, playoff_filename)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(playoff_json, f, indent=2, ensure_ascii=False)

        index_entries.append({
            "file": playoff_filename,
            "name": playoff_json["name"],
            "code": info["code"],
            "category": info["category"],
            "draw_type": "playoff",
            "format": "elimination",
        })
        files_written += 1

    # Write main draw JSON
    filename = division_to_filename(info["code"], "main_draw")
    division_json = {
        "tournament": tournament_name,
        "name": info["full_name"],
        "code": info["code"],
        "category": info["category"],
        "source": f"{base_url}/sport/draws.aspx?id={tournament_id}",
        "draw_type": "main_draw",
        "format": "group_playoff",
        "groups": groups,
    }

    if playoff_bracket:
        division_json["playoff"] = playoff_bracket
    if playoff_filename:
        division_json["playoff_file"] = playoff_filename

    division_json["clubs"] = []

    outpath = os.path.join(OUTPUT_DIR, filename)
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(division_json, f, indent=2, ensure_ascii=False)

    index_entries.append({
        "file": filename,
        "name": info["full_name"],
        "code": info["code"],
        "category": info["category"],
        "draw_type": "main_draw",
        "format": "group_playoff",
    })
    files_written += 1

    return files_written


# ── Entry point ─────────────────────────────────────────────────

def main(url=None, full_results=False):
    if url is None:
        parser = argparse.ArgumentParser(
            description="Scrape tournament data from tournamentsoftware.com"
        )
        parser.add_argument("url", help="Tournament draws page URL")
        parser.add_argument(
            "--full-results",
            action="store_true",
            help="Include match results, scores, and durations",
        )
        args = parser.parse_args()
        url = args.url
        full_results = args.full_results

    print(f"Scraping: {url}")
    print(f"Full results: {full_results}")
    print(f"Output:  {OUTPUT_DIR}/\n")

    index, count = process_tournament(url, full_results)

    print(f"\nGenerated {count} division JSON files + tournament_index.json")
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
