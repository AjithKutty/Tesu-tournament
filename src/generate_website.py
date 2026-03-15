"""
Generate the tournament website from JSON division and schedule files.

Usage:
    python generate_website.py
    python generate_website.py --tournament path/to/tournament

Reads:  divisions/tournament_index.json + divisions/*.json
        schedules/schedule_index.json + schedules/*.json
Writes: index.html
"""

import argparse
import json
import os
from html import escape

from config import (load_config, get_tournament_name, get_tab_config,
                     get_category_order)


def _hex_to_rgb(hex_color):
    """Convert '#RRGGBB' to (r, g, b) tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r, g, b):
    """Convert (r, g, b) to '#RRGGBB'."""
    return f'#{int(r):02x}{int(g):02x}{int(b):02x}'


def _vary_color(base_hex, index, total):
    """Generate a color variation from a base hex color.

    Shifts lightness slightly for each division within a category,
    keeping hue consistent.  index 0 = base color, higher = lighter.
    """
    if total <= 1:
        return base_hex
    r, g, b = _hex_to_rgb(base_hex)
    # Shift towards lighter or darker — spread evenly across range
    # Center on the base, go darker for first half, lighter for second
    offset = (index - (total - 1) / 2) * (30 / max(total - 1, 1))
    r = max(0, min(255, r + offset))
    g = max(0, min(255, g + offset))
    b = max(0, min(255, b + offset))
    return _rgb_to_hex(r, g, b)


def h(text):
    """HTML-escape text."""
    return escape(str(text)) if text else ""


def is_doubles(data):
    """Check if a division is doubles based on its player data."""
    players = data.get("players", [])
    if not players:
        # Check groups
        for g in data.get("groups", []):
            for p in g.get("players", []):
                if "players" in p:
                    return True
        return False
    return "players" in players[0]


def format_label(fmt):
    """Human-readable format label."""
    labels = {
        "elimination": "Elimination Bracket",
        "round_robin": "Round Robin",
        "group_playoff": "Groups + Playoff",
    }
    return labels.get(fmt, fmt)


def count_players(data):
    """Count total players/pairs in a division."""
    fmt = data.get("format")
    if fmt == "group_playoff":
        return sum(len(g["players"]) for g in data.get("groups", []))
    return len(data.get("players", []))


# ── Schedule data loader ──────────────────────────────────────────

def load_schedule_data(schedules_dir):
    """Load schedule files and build a lookup dict for cross-referencing."""
    idx_path = os.path.join(schedules_dir, "schedule_index.json")
    if not os.path.exists(idx_path):
        return {}, []

    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)

    lookup = {}
    all_sessions = []
    for sess_info in idx["sessions"]:
        sess_path = os.path.join(schedules_dir, sess_info["file"])
        if not os.path.exists(sess_path):
            continue
        with open(sess_path, encoding="utf-8") as f:
            sess_data = json.load(f)
        all_sessions.append(sess_data)
        for m in sess_data["matches"]:
            key = (m["division"], m["round"], m["match_num"])
            lookup[key] = {
                "time": m["time"],
                "court": m["court"],
                "date": sess_data["date"],
            }

    return lookup, all_sessions


# ── HTML rendering functions ─────────────────────────────────────

def render_player_row_singles(p):
    pos = p.get("position", "")
    name = h(p.get("name", ""))
    club = h(p.get("club", ""))
    seed = p.get("seed")
    status = p.get("status")

    seed_html = f' <span class="seed">[{h(seed)}]</span>' if seed else ""
    status_html = ""
    if status == "WDN":
        status_html = ' <span class="wdn">WDN</span>'
    elif status == "SUB":
        status_html = ' <span class="sub">SUB</span>'

    return f'<tr><td>{pos}</td><td>{name}{seed_html}{status_html}</td><td class="club">{club}</td></tr>'


def render_player_row_doubles(p):
    pos = p.get("position", "")
    pair = p.get("players", [])
    seed = p.get("seed")
    status = p.get("status")

    names = " / ".join(h(pl.get("name", "")) for pl in pair)
    clubs = " / ".join(h(pl.get("club", "")) for pl in pair)

    seed_html = f' <span class="seed">[{h(seed)}]</span>' if seed else ""
    status_html = ""
    if status == "WDN":
        status_html = ' <span class="wdn">WDN</span>'
    elif status == "SUB":
        status_html = ' <span class="sub">SUB</span>'

    return f'<tr><td>{pos}</td><td>{names}{seed_html}{status_html}</td><td class="club">{clubs}</td></tr>'


def render_player_table(players, doubles):
    """Render draw table with all players."""
    name_header = "Pair" if doubles else "Player"
    rows = []
    for p in players:
        if doubles:
            rows.append(render_player_row_doubles(p))
        else:
            rows.append(render_player_row_singles(p))

    return f"""<div class="section-title">Players</div>
<table class="draw-table">
<thead><tr><th>#</th><th>{name_header}</th><th>Club</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>"""


def render_match_card(match, div_code="", round_name="", schedule_lookup=None):
    """Render a single match card for bracket view."""
    p1 = h(match.get("player1", ""))
    p2 = h(match.get("player2", ""))
    mnum = match.get("match", "")

    p1_class = ' bye-slot' if p1 == "Bye" else ""
    p2_class = ' bye-slot' if p2 == "Bye" else ""

    # Check if this is a structural placeholder
    is_placeholder = p1.startswith("Winner ") or p1.startswith("Slot ")
    if is_placeholder:
        p1_class = " bye-slot"
        p2_class = " bye-slot"

    # Schedule annotation
    sched_html = ""
    if schedule_lookup and div_code:
        info = schedule_lookup.get((div_code, round_name, mnum))
        if info:
            day = info["date"][:3]
            sched_html = f'<span class="match-schedule">{day} {info["time"]} Ct {info["court"]}</span>'

    return f"""<div class="bracket-match">
<div class="match-num">M{mnum}{sched_html}</div>
<div class="player-slot{p1_class}">{p1}</div>
<div class="player-slot{p2_class}">{p2}</div>
</div>"""


def _render_bracket_inner(rounds, div_code="", schedule_lookup=None):
    """Build bracket HTML parts (rounds + connector columns)."""
    parts = []
    for i, rnd in enumerate(rounds):
        name = h(rnd["name"])
        sched_round = rnd.get("_schedule_round", rnd["name"])
        match_wraps = "".join(
            f'<div class="match-wrap">{render_match_card(m, div_code, sched_round, schedule_lookup)}</div>'
            for m in rnd["matches"]
        )
        parts.append(
            f'<div class="bracket-round">'
            f'<div class="bracket-round-title">{name}</div>'
            f'<div class="bracket-matches">{match_wraps}</div>'
            f'</div>'
        )

        # Add connector lines between this round and the next
        if i < len(rounds) - 1:
            n_cur = len(rnd["matches"])
            n_next = len(rounds[i + 1]["matches"])
            if n_cur == 2 * n_next and n_next > 0:
                cells = ""
                for j in range(n_cur):
                    cls = "conn-top" if j % 2 == 0 else "conn-bot"
                    cells += f'<div class="conn-cell {cls}"></div>'
                parts.append(
                    f'<div class="bracket-conn-col">'
                    f'<div class="bracket-round-title">&nbsp;</div>'
                    f'<div class="bracket-conn">{cells}</div>'
                    f'</div>'
                )
    return f'<div class="bracket">\n{"".join(parts)}\n</div>'


def render_bracket(rounds, div_code="", schedule_lookup=None):
    """Render horizontal scrollable bracket with tree-style alignment."""
    if not rounds:
        return ""
    return (
        f'<div class="section-title">Game Draws</div>\n'
        + _render_bracket_inner(rounds, div_code, schedule_lookup)
    )


def render_bracket_playoff(rounds, div_code="", schedule_lookup=None):
    """Render playoff bracket (no section title, supports _schedule_round)."""
    if not rounds:
        return ""
    return _render_bracket_inner(rounds, div_code, schedule_lookup)


def render_rr_matches(matches, div_code="", round_prefix="Pool", schedule_lookup=None):
    """Render round-robin match cards."""
    if not matches:
        return ""

    cards = []
    for m in matches:
        p1 = h(m.get("player1", ""))
        p2 = h(m.get("player2", ""))

        sched_html = ""
        if schedule_lookup and div_code:
            info = schedule_lookup.get((div_code, round_prefix, m.get("match")))
            if info:
                day = info["date"][:3]
                sched_html = f'<span class="match-schedule">{day} {info["time"]} Ct {info["court"]}</span>'

        cards.append(f"""<div class="rr-match">
<span class="p1">{p1}</span>
<span class="vs">VS</span>
<span class="p2">{p2}</span>
{sched_html}
</div>""")

    return f"""<div class="section-title">Matches</div>
<div class="rr-matches">
{"".join(cards)}
</div>"""


def render_elimination_division(data, schedule_lookup=None):
    """Render an elimination bracket division body."""
    doubles = is_doubles(data)
    div_code = data.get("code", "")
    parts = []
    parts.append(render_player_table(data.get("players", []), doubles))
    parts.append(render_bracket(data.get("rounds", []), div_code, schedule_lookup))
    return "\n".join(parts)


def render_roundrobin_division(data, schedule_lookup=None):
    """Render a round-robin division body."""
    doubles = is_doubles(data)
    div_code = data.get("code", "")
    parts = []
    parts.append(render_player_table(data.get("players", []), doubles))
    parts.append(render_rr_matches(data.get("matches", []), div_code, "Pool", schedule_lookup))
    return "\n".join(parts)


def render_group_playoff_division(data, schedule_lookup=None):
    """Render a group+playoff division body."""
    doubles = is_doubles(data)
    div_code = data.get("code", "")
    parts = []

    for group in data.get("groups", []):
        group_name = group["name"]
        parts.append(f'<div class="group-title">{h(group_name)}</div>')
        parts.append(render_player_table(group.get("players", []), doubles))
        round_prefix = f"{group_name} Pool"
        parts.append(render_rr_matches(group.get("matches", []), div_code, round_prefix, schedule_lookup))

    # Playoff bracket
    playoff = data.get("playoff")
    if playoff and playoff.get("rounds"):
        parts.append(f'<div class="section-title" style="margin-top:1.5rem;">Playoff Bracket (Top from each group)</div>')
        # Remap round names for schedule lookup (prefix with "Playoff ")
        playoff_rounds = []
        for rnd in playoff["rounds"]:
            playoff_rounds.append({
                "name": rnd["name"],
                "matches": rnd["matches"],
                "_schedule_round": f"Playoff {rnd['name']}"
            })
        parts.append(render_bracket_playoff(playoff_rounds, div_code, schedule_lookup))

    return "\n".join(parts)


def render_division_card(data, badge_class, schedule_lookup=None):
    """Render a full division card (header + body)."""
    name = h(data.get("name", ""))
    fmt = data.get("format", "")
    fmt_label = format_label(fmt)
    player_count = count_players(data)
    count_label = f"{player_count} {'pairs' if is_doubles(data) else 'players'}"

    # Body content
    if fmt == "elimination":
        body = render_elimination_division(data, schedule_lookup)
    elif fmt == "round_robin":
        body = render_roundrobin_division(data, schedule_lookup)
    elif fmt == "group_playoff":
        body = render_group_playoff_division(data, schedule_lookup)
    else:
        body = "<p>Unknown format</p>"

    return f"""<div class="division-card">
<div class="division-header" onclick="toggleCard(this)">
<div class="left">
<h3>{name}</h3>
<span class="badge {badge_class}">{fmt_label}</span>
<span class="format-tag">{count_label}</span>
</div>
<span class="chevron">&#9660;</span>
</div>
<div class="division-body">
{body}
</div>
</div>"""


def render_clubs_tab(clubs):
    """Render the clubs tab content."""
    cards = []
    for club in sorted(clubs):
        cards.append(f'<div class="club-card"><strong>{h(club)}</strong></div>')

    return f"""<div class="cat-header">
<h2>Participating Clubs</h2>
<p>{len(clubs)} clubs</p>
</div>
<div class="clubs-grid">
{"".join(cards)}
</div>"""


def _split_player_names(player_str):
    """Split a player string into individual names.

    Singles: "Luka Penttinen" -> ["Luka Penttinen"]
    Doubles: "Iiro Romppainen / Emilia Mattila" -> ["Iiro Romppainen", "Emilia Mattila"]
    Placeholders/Bye: return empty list.
    """
    if not player_str or player_str == "Bye":
        return []
    if player_str.startswith("Winner ") or player_str.startswith("Slot "):
        return []
    return [n.strip() for n in player_str.split(" / ") if n.strip()]


def build_player_schedule(all_sessions, divisions_dir):
    """Build a map of individual player_name -> list of scheduled match dicts.

    Doubles pairs are split so each partner appears separately in the
    dropdown.  Each match dict includes a 'partner' field (None for
    singles, partner name for doubles).
    """
    player_matches = {}  # individual player_name -> list of match dicts

    if not all_sessions:
        return player_matches

    for sess in all_sessions:
        for m in sess.get("matches", []):
            p1_str = m.get("player1", "")
            p2_str = m.get("player2", "")
            date = sess.get("date", "")
            time = m.get("time", "")
            court = m.get("court", "")
            div = m.get("division", "")
            rnd = m.get("round", "")
            mnum = m.get("match_num", "")
            dur = m.get("duration_min", 30)
            cat = m.get("category", "")

            p1_names = _split_player_names(p1_str)
            p2_names = _split_player_names(p2_str)

            # For each individual on side 1, record the match
            for name in p1_names:
                partner = [n for n in p1_names if n != name]
                if name not in player_matches:
                    player_matches[name] = []
                player_matches[name].append({
                    "date": date, "time": time, "court": court,
                    "division": div, "round": rnd, "match_num": mnum,
                    "opponent": p2_str, "duration_min": dur, "category": cat,
                    "partner": partner[0] if partner else None,
                })

            # For each individual on side 2, record the match
            for name in p2_names:
                partner = [n for n in p2_names if n != name]
                if name not in player_matches:
                    player_matches[name] = []
                player_matches[name].append({
                    "date": date, "time": time, "court": court,
                    "division": div, "round": rnd, "match_num": mnum,
                    "opponent": p1_str, "duration_min": dur, "category": cat,
                    "partner": partner[0] if partner else None,
                })

    # Sort each player's matches by day then time
    day_order = {}
    for sess in all_sessions:
        d = sess.get("date", "")
        if d not in day_order:
            day_order[d] = len(day_order)

    for player in player_matches:
        player_matches[player].sort(
            key=lambda m: (day_order.get(m["date"], 99), m["time"])
        )

    return player_matches


def render_players_tab(player_matches, badge_lookup):
    """Render the Players tab with a searchable dropdown and match list."""
    if not player_matches:
        return '<p style="color: var(--text-light); padding: 1rem;">No schedule data available.</p>'

    sorted_players = sorted(player_matches.keys())

    # Build dropdown options
    options = ['<option value="">-- Select a player --</option>']
    for name in sorted_players:
        count = len(player_matches[name])
        options.append(f'<option value="{h(name)}">{h(name)} ({count} matches)</option>')

    # Build per-player match cards (hidden by default, shown via JS)
    player_panels = []
    for name in sorted_players:
        matches = player_matches[name]
        cards = []
        for m in matches:
            badge = badge_lookup.get(m["division"],
                    badge_lookup.get(m["category"], "badge-open"))
            opp = h(m["opponent"])
            partner_html = ""
            if m.get("partner"):
                partner_html = f'<div class="player-match-partner">with {h(m["partner"])}</div>'
            cards.append(f"""<div class="player-match-card">
<div class="player-match-header">
<span class="badge {badge}">{h(m['division'])}</span>
<span class="player-match-round">{h(m['round'])} M{m['match_num']}</span>
<span class="player-match-time">{h(m['date'][:3])} {h(m['time'])} &middot; Court {m['court']}</span>
</div>
{partner_html}<div class="player-match-opponent">vs {opp}</div>
</div>""")

        safe_name = h(name)
        player_panels.append(
            f'<div class="player-schedule" data-player="{safe_name}" style="display:none;">\n'
            f'<div class="player-match-count">{len(matches)} scheduled match{"es" if len(matches) != 1 else ""}</div>\n'
            + "\n".join(cards)
            + "\n</div>"
        )

    return f"""<div class="cat-header">
<h2>Player Schedule</h2>
<p>{len(sorted_players)} players</p>
</div>
<div class="player-select-wrap">
<select id="player-select" class="player-select" onchange="showPlayerSchedule(this.value)">
{"".join(options)}
</select>
</div>
<div id="player-schedules">
{"".join(player_panels)}
</div>"""


# ── Page assembly ────────────────────────────────────────────────

CSS = """:root {
    --primary: #0d2137;
    --primary-light: #163a5c;
    --accent: #00b894;
    --accent-dark: #00997a;
    --bg: #f0f4f8;
    --card-bg: #ffffff;
    --text: #2d3748;
    --text-light: #718096;
    --border: #e2e8f0;
    --shadow: 0 2px 8px rgba(0,0,0,0.08);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
  .hero { background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 100%); color: white; text-align: center; padding: 3rem 1rem 2rem; }
  .hero h1 { font-size: 2.2rem; font-weight: 700; margin-bottom: 0.3rem; }
  .hero .subtitle { font-size: 1.1rem; opacity: 0.85; margin-bottom: 1rem; }
  .hero .meta { display: flex; justify-content: center; gap: 2rem; flex-wrap: wrap; font-size: 0.95rem; opacity: 0.75; }
  .shuttlecock { font-size: 2.5rem; margin-bottom: 0.5rem; display: block; }
  .stats-bar { display: flex; justify-content: center; gap: 2rem; flex-wrap: wrap; background: var(--card-bg); padding: 1rem; border-bottom: 1px solid var(--border); box-shadow: var(--shadow); }
  .stat { text-align: center; }
  .stat .num { font-size: 1.5rem; font-weight: 700; color: var(--accent-dark); }
  .stat .label { font-size: 0.8rem; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.05em; }
  .tabs-wrapper { position: sticky; top: 0; z-index: 100; background: var(--card-bg); border-bottom: 2px solid var(--border); box-shadow: var(--shadow); }
  .tabs { display: flex; justify-content: center; gap: 0; max-width: 900px; margin: 0 auto; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .tab-btn { padding: 0.9rem 1.4rem; border: none; background: none; cursor: pointer; font-size: 0.9rem; font-weight: 600; color: var(--text-light); border-bottom: 3px solid transparent; transition: all 0.2s; white-space: nowrap; }
  .tab-btn:hover { color: var(--text); background: #f7fafc; }
  .tab-btn.active { color: var(--accent-dark); border-bottom-color: var(--accent); }
  .content { max-width: 1100px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .cat-header { margin-bottom: 1.5rem; }
  .cat-header h2 { font-size: 1.4rem; margin-bottom: 0.2rem; }
  .cat-header p { color: var(--text-light); font-size: 0.9rem; }
  .division-card { background: var(--card-bg); border-radius: 12px; box-shadow: var(--shadow); margin-bottom: 1.5rem; overflow: hidden; border: 1px solid var(--border); }
  .division-header { padding: 1rem 1.2rem; cursor: pointer; display: flex; align-items: center; justify-content: space-between; user-select: none; transition: background 0.15s; }
  .division-header:hover { background: #f7fafc; }
  .division-header .left { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
  .division-header h3 { font-size: 1.05rem; font-weight: 600; }
  .badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 20px; font-size: 0.7rem; font-weight: 700; color: white; text-transform: uppercase; letter-spacing: 0.04em; }
  /* Badge colors are generated from divisions.yaml config */
  .format-tag { font-size: 0.78rem; color: var(--text-light); background: var(--bg); padding: 0.2rem 0.6rem; border-radius: 6px; }
  .chevron { font-size: 1.2rem; color: var(--text-light); transition: transform 0.3s; }
  .division-card.open .chevron { transform: rotate(180deg); }
  .division-body { display: none; padding: 0 1.2rem 1.2rem; }
  .division-card.open .division-body { display: block; }
  .draw-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 0.5rem; }
  .draw-table th { text-align: left; padding: 0.5rem 0.6rem; background: var(--bg); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-light); border-bottom: 2px solid var(--border); }
  .draw-table td { padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }
  .draw-table tr:last-child td { border-bottom: none; }
  .draw-table tr:hover { background: #f7fafc; }
  .seed { color: var(--accent-dark); font-weight: 700; font-size: 0.8rem; }
  .club { color: var(--text-light); font-size: 0.82rem; }
  .wdn { color: #e53e3e; font-weight: 600; font-size: 0.75rem; }
  .sub { color: #d69e2e; font-weight: 600; font-size: 0.75rem; }
  .group-title { font-size: 0.95rem; font-weight: 700; margin: 1rem 0 0.3rem; padding: 0.4rem 0.7rem; background: var(--primary); color: white; border-radius: 6px; display: inline-block; }
  .group-title:first-child { margin-top: 0; }
  .section-title { font-size: 0.95rem; font-weight: 700; margin: 1.2rem 0 0.5rem; padding-bottom: 0.3rem; border-bottom: 2px solid var(--accent); color: var(--primary); }
  .bracket { display: flex; align-items: stretch; overflow-x: auto; padding: 0.5rem 0; gap: 0; }
  .bracket-round { min-width: 220px; flex-shrink: 0; display: flex; flex-direction: column; }
  .bracket-round-title { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-light); padding: 0.3rem 0.5rem; background: var(--bg); border-radius: 4px; text-align: center; letter-spacing: 0.05em; }
  .bracket-matches { display: flex; flex-direction: column; flex: 1; }
  .match-wrap { flex: 1; display: flex; align-items: center; padding: 2px 0; }
  .bracket-match { background: var(--bg); border-radius: 6px; border: 1px solid var(--border); overflow: hidden; font-size: 0.8rem; width: 100%; }
  .bracket-match .match-num { font-size: 0.65rem; color: var(--text-light); padding: 0.15rem 0.4rem; background: var(--border); }
  .bracket-match .player-slot { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); white-space: nowrap; }
  .bracket-match .player-slot:last-child { border-bottom: none; }
  .bracket-match .player-slot.bye-slot { color: var(--text-light); font-style: italic; }
  .bracket-conn-col { display: flex; flex-direction: column; flex-shrink: 0; }
  .bracket-conn-col > .bracket-round-title { visibility: hidden; }
  .bracket-conn { display: flex; flex-direction: column; flex: 1; min-width: 24px; }
  .conn-cell { flex: 1; position: relative; }
  .conn-cell.conn-top::after { content: ''; position: absolute; top: 50%; left: 0; right: 0; bottom: 0; border-top: 2px solid var(--border); border-right: 2px solid var(--border); border-top-right-radius: 4px; }
  .conn-cell.conn-bot::after { content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 50%; border-bottom: 2px solid var(--border); border-right: 2px solid var(--border); border-bottom-right-radius: 4px; }
  .conn-cell.conn-bot::before { content: ''; position: absolute; top: 0; right: -12px; width: 12px; border-top: 2px solid var(--border); }
  .rr-matches { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.4rem; margin-top: 0.5rem; }
  .rr-match { display: flex; align-items: center; gap: 0.5rem; background: var(--bg); border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.82rem; border: 1px solid var(--border); }
  .rr-match .vs { font-weight: 700; color: var(--accent-dark); font-size: 0.7rem; flex-shrink: 0; }
  .rr-match .p1, .rr-match .p2 { flex: 1; }
  .rr-match .p2 { text-align: right; }
  .clubs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.8rem; margin-top: 1rem; }
  .club-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 0.7rem 1rem; box-shadow: var(--shadow); font-size: 0.9rem; }
  .club-card strong { color: var(--primary); }
  .footer { text-align: center; padding: 2rem 1rem; color: var(--text-light); font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 2rem; }
  .match-schedule { font-size: 0.6rem; color: var(--accent-dark); font-weight: 600; float: right; letter-spacing: 0.02em; }
  .rr-match .match-schedule { float: none; display: block; text-align: center; font-size: 0.7rem; margin-top: 0.15rem; }
  @media (max-width: 600px) {
    .hero h1 { font-size: 1.5rem; }
    .stats-bar { gap: 1rem; }
    .tab-btn { padding: 0.7rem 0.9rem; font-size: 0.82rem; }
    .content { padding: 1rem 0.5rem 2rem; }
    .draw-table { font-size: 0.82rem; }
    .draw-table th, .draw-table td { padding: 0.35rem 0.4rem; }
    .bracket-round { min-width: 180px; }
  }
  .schedule-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin-top: 0.5rem; }
  .schedule-grid { border-collapse: collapse; font-size: 0.75rem; min-width: 100%; }
  .schedule-grid th { position: sticky; top: 0; background: var(--primary); color: white; padding: 0.4rem 0.3rem; text-align: center; font-size: 0.75rem; z-index: 10; white-space: nowrap; min-width: 130px; }
  .schedule-grid th:first-child { min-width: 55px; left: 0; z-index: 15; }
  .schedule-grid .time-cell { font-weight: 700; background: var(--primary-light); color: white; text-align: center; padding: 0.4rem 0.3rem; position: sticky; left: 0; z-index: 5; white-space: nowrap; }
  .sched-cell { border: 1px solid var(--border); padding: 0.3rem; vertical-align: top; background: var(--card-bg); }
  .sched-cell:hover { background: #f0f7ff; }
  .sched-div { margin-bottom: 0.15rem; display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; }
  .sched-div .badge { font-size: 0.6rem; padding: 0.1rem 0.4rem; }
  .sched-round { font-size: 0.6rem; color: var(--text-light); }
  .sched-p { font-size: 0.7rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 150px; }
  .sched-vs { font-size: 0.55rem; color: var(--accent-dark); font-weight: 700; }
  .sched-empty { border: 1px solid #edf2f7; background: var(--bg); }
  .sched-panel { display: none; }
  .sched-panel.active { display: block; }
  .sched-tabs { display: flex; gap: 0.3rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .sched-tab-btn { padding: 0.5rem 1rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); cursor: pointer; font-size: 0.82rem; transition: all 0.2s; }
  .sched-tab-btn.active { background: var(--primary); color: white; border-color: var(--primary); }
  #tab-schedule .content { max-width: none; padding: 1rem; }
  .player-select-wrap { margin-bottom: 1rem; }
  .player-select { width: 100%; max-width: 400px; padding: 0.6rem 0.8rem; border: 1px solid var(--border); border-radius: 8px; font-size: 0.95rem; background: var(--card-bg); color: var(--text); cursor: pointer; }
  .player-select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,184,148,0.15); }
  .player-match-count { font-size: 0.85rem; color: var(--text-light); margin-bottom: 0.8rem; }
  .player-match-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 0.7rem 1rem; margin-bottom: 0.5rem; box-shadow: var(--shadow); }
  .player-match-header { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.3rem; }
  .player-match-round { font-size: 0.8rem; color: var(--text-light); }
  .player-match-time { font-size: 0.8rem; font-weight: 600; color: var(--accent-dark); margin-left: auto; }
  .player-match-partner { font-size: 0.8rem; color: var(--accent-dark); font-weight: 600; margin-bottom: 0.15rem; }
  .player-match-opponent { font-size: 0.9rem; }"""

JS = """document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
  });
});
function toggleCard(header) {
  header.closest('.division-card').classList.toggle('open');
}
document.querySelectorAll('.sched-tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.sched-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sched-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('sched-' + btn.dataset.session).classList.add('active');
  });
});
function showPlayerSchedule(name) {
  document.querySelectorAll('.player-schedule').forEach(el => { el.style.display = 'none'; });
  if (name) {
    const panels = document.querySelectorAll('.player-schedule');
    for (const el of panels) {
      if (el.dataset.player === name) { el.style.display = 'block'; break; }
    }
  }
}"""


def add_30min(time_str):
    """Add 30 minutes to a HH:MM time string."""
    hh, mm = map(int, time_str.split(":"))
    mm += 30
    if mm >= 60:
        hh += 1
        mm -= 60
    return f"{hh:02d}:{mm:02d}"


def time_slots_range(start_str, end_str):
    """Generate 30-min time slots from start to end (exclusive)."""
    slots = []
    current = start_str
    while current < end_str:
        slots.append(current)
        current = add_30min(current)
    return slots


def render_schedule_grid(session_data, badge_lookup):
    """Render a time x court grid table for one session."""
    matches = session_data.get("matches", [])
    if not matches:
        return '<p style="color: var(--text-light); padding: 1rem;">No matches in this session.</p>'

    # Determine courts and time slots
    courts = sorted(set(m["court"] for m in matches))
    time_slots = time_slots_range(session_data["start"], session_data["end"])

    # Build grid and blocked set
    grid = {}
    blocked = set()
    for m in matches:
        grid[(m["time"], m["court"])] = m
        if m["duration_min"] > 30:
            next_time = add_30min(m["time"])
            blocked.add((next_time, m["court"]))

    # Header row
    header_cells = '<th>Time</th>'
    for c in courts:
        header_cells += f'<th>Court {c}</th>'

    # Body rows
    rows = []
    for t in time_slots:
        cells = f'<td class="time-cell">{t}</td>'
        for c in courts:
            if (t, c) in blocked:
                continue  # rowspan from previous row already covers this cell
            elif (t, c) in grid:
                m = grid[(t, c)]
                badge = badge_lookup.get(m.get("division", ""),
                        badge_lookup.get(m.get("category", ""), "badge-open"))
                div_code = h(m["division"])
                rnd = h(m.get("round", ""))
                mnum = m.get("match_num", "")
                p1 = h(m["player1"])
                p2 = h(m["player2"])
                rowspan = ' rowspan="2"' if m["duration_min"] > 30 else ""
                cells += f'''<td class="sched-cell"{rowspan}>
<div class="sched-div"><span class="badge {badge}">{div_code}</span><span class="sched-round">{rnd} M{mnum}</span></div>
<div class="sched-p" title="{p1}">{p1}</div>
<div class="sched-vs">vs</div>
<div class="sched-p" title="{p2}">{p2}</div>
</td>'''
            else:
                cells += '<td class="sched-empty"></td>'
        rows.append(f'<tr>{cells}</tr>')

    return f"""<div class="schedule-wrap">
<table class="schedule-grid">
<thead><tr>{header_cells}</tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</div>"""


def render_schedule_panel(all_sessions, badge_lookup):
    """Render the Schedule tab panel content with session sub-tabs and grids."""
    if not all_sessions:
        return '<p style="color: var(--text-light); padding: 1rem;">No schedule data available.</p>'

    tab_ids = []
    tab_buttons = []
    tab_panels = []

    for sess in all_sessions:
        if not sess.get("matches"):
            continue
        sess_id = sess["session"].lower().replace(" ", "_")
        tab_ids.append(sess_id)
        active = " active" if len(tab_ids) == 1 else ""
        label = sess["session"]
        count = len(sess["matches"])
        tab_buttons.append(
            f'<button class="sched-tab-btn{active}" data-session="{sess_id}">{label} ({count})</button>'
        )
        grid = render_schedule_grid(sess, badge_lookup)
        tab_panels.append(f'<div class="sched-panel{active}" id="sched-{sess_id}">{grid}</div>')

    total = sum(len(s.get("matches", [])) for s in all_sessions)

    return f"""<div class="cat-header">
<h2>Match Schedule</h2>
<p>{total} matches across {len(tab_ids)} sessions</p>
</div>
<div class="sched-tabs">
{"".join(tab_buttons)}
</div>
{"".join(tab_panels)}"""


def generate_html(config, schedule_lookup=None, all_sessions=None):
    divisions_dir = config["paths"]["divisions_dir"]
    tournament_name = get_tournament_name(config)
    tab_config = get_tab_config(config)
    description = config["tournament"].get("description", "")

    # Load index
    with open(os.path.join(divisions_dir, "tournament_index.json"), encoding="utf-8") as f:
        index = json.load(f)

    # Group main_draw divisions by category
    by_category = {}
    for entry in index["divisions"]:
        if entry["draw_type"] != "main_draw":
            continue
        cat = entry["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(entry)

    # Build per-division badge lookup and generate badge CSS
    # Each division gets its own color, varied from the category base color.
    # Optional division_colors in divisions.yaml can override specific divisions.
    division_colors_config = config["divisions"].get("division_colors", {})
    badge_lookup = {}      # division_code -> badge_class
    category_badge = {}    # category -> badge_class (fallback)
    badge_css_lines = []

    for tab in tab_config:
        cat = tab["category"]
        base_color = tab.get("badge_color", "#3182ce")
        category_badge[cat] = tab["badge_class"]

        divs_in_cat = by_category.get(cat, [])
        for i, entry in enumerate(divs_in_cat):
            div_code = entry["code"]
            safe_class = "badge-" + div_code.lower().replace(" ", "-").replace("/", "")
            badge_lookup[div_code] = safe_class

            # Use explicit override, or auto-vary from base
            if div_code in division_colors_config:
                color = division_colors_config[div_code]
            else:
                color = _vary_color(base_color, i, len(divs_in_cat))

            badge_css_lines.append(f'  .{safe_class} {{ background: {color}; }}')

    badge_css = "\n".join(badge_css_lines)

    # Filter tab config to only categories present in data
    active_tabs = [tab for tab in tab_config if tab["category"] in by_category]

    # Count total players
    total_players = 0
    total_main_divisions = 0
    for cat_entries in by_category.values():
        for entry in cat_entries:
            total_main_divisions += 1
            filepath = os.path.join(divisions_dir, entry["file"])
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            total_players += count_players(data)

    clubs = index.get("clubs", [])

    # Build tabs
    tab_buttons = []
    for tab in active_tabs:
        active = " active" if tab == active_tabs[0] else ""
        tab_buttons.append(
            f'<button class="tab-btn{active}" data-tab="{tab["tab_id"]}">{tab["category"]}</button>'
        )
    tab_buttons.append('<button class="tab-btn" data-tab="clubs">Clubs</button>')
    if all_sessions:
        tab_buttons.append('<button class="tab-btn" data-tab="players">Players</button>')
        tab_buttons.append('<button class="tab-btn" data-tab="schedule">Schedule</button>')

    # Build tab panels
    tab_panels = []
    for i, tab in enumerate(active_tabs):
        active = " active" if i == 0 else ""
        entries = by_category.get(tab["category"], [])

        cards = []
        for entry in entries:
            filepath = os.path.join(divisions_dir, entry["file"])
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            div_badge = badge_lookup.get(entry["code"], tab["badge_class"])
            cards.append(render_division_card(data, div_badge, schedule_lookup))

        panel = f"""<div class="tab-panel{active}" id="tab-{tab['tab_id']}">
<div class="cat-header">
<h2>{h(tab['category'])}</h2>
</div>
{"".join(cards)}
</div>"""
        tab_panels.append(panel)

    # Clubs tab
    tab_panels.append(f"""<div class="tab-panel" id="tab-clubs">
{render_clubs_tab(clubs)}
</div>""")

    # Players tab
    if all_sessions:
        player_matches = build_player_schedule(all_sessions, divisions_dir)
        tab_panels.append(f"""<div class="tab-panel" id="tab-players">
{render_players_tab(player_matches, badge_lookup)}
</div>""")

    # Schedule tab
    if all_sessions:
        tab_panels.append(f"""<div class="tab-panel" id="tab-schedule">
{render_schedule_panel(all_sessions, badge_lookup)}
</div>""")

    # Hero meta line: use description from config if available
    meta_html = ""
    if description:
        meta_html = f"""<div class="meta">
<span>{h(description)}</span>
</div>"""

    # Assemble full page
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{h(tournament_name)}</title>
<style>
{CSS}
{badge_css}
</style>
</head>
<body>

<div class="hero">
<span class="shuttlecock">&#127992;</span>
<h1>{h(tournament_name)}</h1>
<p class="subtitle">Badminton Tournament</p>
{meta_html}
</div>

<div class="stats-bar">
<div class="stat"><div class="num">{total_main_divisions}</div><div class="label">Divisions</div></div>
<div class="stat"><div class="num">{len(clubs)}</div><div class="label">Clubs</div></div>
<div class="stat"><div class="num">{total_players}+</div><div class="label">Players</div></div>
<div class="stat"><div class="num">{len(active_tabs)}</div><div class="label">Categories</div></div>
</div>

<div class="tabs-wrapper">
<div class="tabs">
{"".join(tab_buttons)}
</div>
</div>

<div class="content">

{"".join(tab_panels)}

</div>

<div class="footer">
{h(tournament_name)} &middot; Data from Badminton Finland Tournament Planner
</div>

<script>
{JS}
</script>
</body>
</html>"""

    return html


def main(config=None):
    if config is None:
        parser = argparse.ArgumentParser(description="Generate tournament website")
        parser.add_argument("--tournament", default=None,
                            help="Path to tournament directory (default: auto-detect)")
        args = parser.parse_args()

        if args.tournament:
            tournament_dir = args.tournament
        else:
            # Default: look for tournament dir relative to project root
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            tournament_dir = base_dir

        config = load_config(tournament_dir)

    divisions_dir = config["paths"]["divisions_dir"]
    schedules_dir = config["paths"]["schedules_dir"]
    output_file = os.path.join(config["paths"]["webpages_dir"], "index.html")

    print(f"Reading JSON files from: {divisions_dir}/")

    # Load schedule data for cross-referencing
    schedule_lookup, all_sessions = load_schedule_data(schedules_dir)
    if schedule_lookup:
        print(f"Loaded schedule: {len(schedule_lookup)} matches from {len(all_sessions)} sessions")

    # Generate index.html (single page with all tabs including schedule)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    html = generate_html(config, schedule_lookup, all_sessions)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {output_file} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
