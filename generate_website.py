"""
Generate the tournament website (index.html) from JSON division files.

Usage:
    python generate_website.py

Reads:  divisions/tournament_index.json + divisions/*.json
Writes: index.html
"""

import json
import os
from html import escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIVISIONS_DIR = os.path.join(BASE_DIR, "divisions")
OUTPUT_FILE = os.path.join(BASE_DIR, "index.html")

# ── Category configuration ───────────────────────────────────────

CATEGORIES = [
    {"key": "Open A", "tab_id": "opena", "badge": "badge-open", "label": "Open A Division",
     "desc": "Men's Singles, Men's Doubles, Women's Doubles, Mixed Doubles"},
    {"key": "Open B", "tab_id": "openb", "badge": "badge-open", "label": "Open B Division",
     "desc": "Men's Singles, Women's Singles, Men's Doubles, Mixed Doubles"},
    {"key": "Open C", "tab_id": "open", "badge": "badge-open", "label": "Open C Division",
     "desc": "Men's Singles, Women's Singles, Men's Doubles, Women's Doubles, Mixed Doubles"},
    {"key": "Junior", "tab_id": "junior", "badge": "badge-junior", "label": "Junior Division",
     "desc": "Boys' Singles & Doubles — U11, U13, U15, U17"},
    {"key": "Veterans", "tab_id": "veterans", "badge": "badge-veterans", "label": "Veterans Division",
     "desc": "Men's Singles & Doubles, Mixed Doubles — 35+, 45+"},
    {"key": "Elite", "tab_id": "elite", "badge": "badge-elite", "label": "Elite Division",
     "desc": "Men's Singles, Women's Singles, Mixed Doubles"},
]


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


def render_match_card(match, round_abbrev=""):
    """Render a single match card for bracket view."""
    p1 = h(match.get("player1", ""))
    p2 = h(match.get("player2", ""))
    mnum = match.get("match", "")
    notes = match.get("notes", "")

    p1_class = ' bye-slot' if p1 == "Bye" else ""
    p2_class = ' bye-slot' if p2 == "Bye" else ""

    # Check if this is a structural placeholder
    is_placeholder = p1.startswith("Winner ") or p1.startswith("Slot ")
    if is_placeholder:
        p1_class = " bye-slot"
        p2_class = " bye-slot"

    return f"""<div class="bracket-match">
<div class="match-num">M{mnum}</div>
<div class="player-slot{p1_class}">{p1}</div>
<div class="player-slot{p2_class}">{p2}</div>
</div>"""


def render_bracket(rounds):
    """Render horizontal scrollable bracket with all rounds."""
    if not rounds:
        return ""

    round_htmls = []
    for rnd in rounds:
        name = h(rnd["name"])
        matches_html = "".join(render_match_card(m) for m in rnd["matches"])
        round_htmls.append(f"""<div class="bracket-round">
<div class="bracket-round-title">{name}</div>
{matches_html}
</div>""")

    connectors = '<div class="bracket-connector">&rarr;</div>'.join(round_htmls)
    return f"""<div class="section-title">Game Draws</div>
<div class="bracket">
{connectors}
</div>"""


def render_rr_matches(matches):
    """Render round-robin match cards."""
    if not matches:
        return ""

    cards = []
    for m in matches:
        p1 = h(m.get("player1", ""))
        p2 = h(m.get("player2", ""))
        cards.append(f"""<div class="rr-match">
<span class="p1">{p1}</span>
<span class="vs">VS</span>
<span class="p2">{p2}</span>
</div>""")

    return f"""<div class="section-title">Matches</div>
<div class="rr-matches">
{"".join(cards)}
</div>"""


def render_elimination_division(data):
    """Render an elimination bracket division body."""
    doubles = is_doubles(data)
    parts = []
    parts.append(render_player_table(data.get("players", []), doubles))
    parts.append(render_bracket(data.get("rounds", [])))
    return "\n".join(parts)


def render_roundrobin_division(data):
    """Render a round-robin division body."""
    doubles = is_doubles(data)
    parts = []
    parts.append(render_player_table(data.get("players", []), doubles))
    parts.append(render_rr_matches(data.get("matches", [])))
    return "\n".join(parts)


def render_group_playoff_division(data):
    """Render a group+playoff division body."""
    doubles = is_doubles(data)
    parts = []

    for group in data.get("groups", []):
        parts.append(f'<div class="group-title">{h(group["name"])}</div>')
        parts.append(render_player_table(group.get("players", []), doubles))
        parts.append(render_rr_matches(group.get("matches", [])))

    # Playoff bracket
    playoff = data.get("playoff")
    if playoff and playoff.get("rounds"):
        parts.append(f'<div class="section-title" style="margin-top:1.5rem;">Playoff Bracket (Top from each group)</div>')
        rounds = playoff["rounds"]
        round_htmls = []
        for rnd in rounds:
            name = h(rnd["name"])
            matches_html = "".join(render_match_card(m) for m in rnd["matches"])
            round_htmls.append(f"""<div class="bracket-round">
<div class="bracket-round-title">{name}</div>
{matches_html}
</div>""")
        connectors = '<div class="bracket-connector">&rarr;</div>'.join(round_htmls)
        parts.append(f'<div class="bracket">\n{connectors}\n</div>')

    return "\n".join(parts)


def render_division_card(data, badge_class):
    """Render a full division card (header + body)."""
    name = h(data.get("name", ""))
    fmt = data.get("format", "")
    fmt_label = format_label(fmt)
    player_count = count_players(data)
    count_label = f"{player_count} {'pairs' if is_doubles(data) else 'players'}"

    # Body content
    if fmt == "elimination":
        body = render_elimination_division(data)
    elif fmt == "round_robin":
        body = render_roundrobin_division(data)
    elif fmt == "group_playoff":
        body = render_group_playoff_division(data)
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
<p>{len(clubs)} clubs from Finland and abroad</p>
</div>
<div class="clubs-grid">
{"".join(cards)}
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
    --junior: #38a169;
    --open: #3182ce;
    --veterans: #dd6b20;
    --elite: #805ad5;
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
  .badge-junior { background: var(--junior); }
  .badge-open { background: var(--open); }
  .badge-veterans { background: var(--veterans); }
  .badge-elite { background: var(--elite); }
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
  .bracket { display: flex; gap: 0; overflow-x: auto; padding: 0.5rem 0; }
  .bracket-round { min-width: 220px; flex-shrink: 0; }
  .bracket-round-title { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: var(--text-light); padding: 0.3rem 0.5rem; background: var(--bg); border-radius: 4px; margin-bottom: 0.4rem; text-align: center; letter-spacing: 0.05em; }
  .bracket-match { background: var(--bg); border-radius: 6px; margin-bottom: 0.5rem; border: 1px solid var(--border); overflow: hidden; font-size: 0.8rem; }
  .bracket-match .match-num { font-size: 0.65rem; color: var(--text-light); padding: 0.15rem 0.4rem; background: var(--border); }
  .bracket-match .player-slot { padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); white-space: nowrap; }
  .bracket-match .player-slot:last-child { border-bottom: none; }
  .bracket-match .player-slot.bye-slot { color: var(--text-light); font-style: italic; }
  .bracket-connector { display: flex; align-items: center; justify-content: center; min-width: 20px; color: var(--text-light); font-size: 1.2rem; flex-shrink: 0; }
  .rr-matches { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.4rem; margin-top: 0.5rem; }
  .rr-match { display: flex; align-items: center; gap: 0.5rem; background: var(--bg); border-radius: 6px; padding: 0.4rem 0.7rem; font-size: 0.82rem; border: 1px solid var(--border); }
  .rr-match .vs { font-weight: 700; color: var(--accent-dark); font-size: 0.7rem; flex-shrink: 0; }
  .rr-match .p1, .rr-match .p2 { flex: 1; }
  .rr-match .p2 { text-align: right; }
  .clubs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.8rem; margin-top: 1rem; }
  .club-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 0.7rem 1rem; box-shadow: var(--shadow); font-size: 0.9rem; }
  .club-card strong { color: var(--primary); }
  .footer { text-align: center; padding: 2rem 1rem; color: var(--text-light); font-size: 0.8rem; border-top: 1px solid var(--border); margin-top: 2rem; }
  @media (max-width: 600px) {
    .hero h1 { font-size: 1.5rem; }
    .stats-bar { gap: 1rem; }
    .tab-btn { padding: 0.7rem 0.9rem; font-size: 0.82rem; }
    .content { padding: 1rem 0.5rem 2rem; }
    .draw-table { font-size: 0.82rem; }
    .draw-table th, .draw-table td { padding: 0.35rem 0.4rem; }
    .bracket-round { min-width: 180px; }
  }"""

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
}"""


def generate_html():
    # Load index
    with open(os.path.join(DIVISIONS_DIR, "tournament_index.json"), encoding="utf-8") as f:
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

    # Count total players
    total_players = 0
    total_main_divisions = 0
    for cat_entries in by_category.values():
        for entry in cat_entries:
            total_main_divisions += 1
            filepath = os.path.join(DIVISIONS_DIR, entry["file"])
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            total_players += count_players(data)

    clubs = index.get("clubs", [])

    # Build tabs
    tab_buttons = []
    for cat_cfg in CATEGORIES:
        active = " active" if cat_cfg == CATEGORIES[0] else ""
        tab_buttons.append(
            f'<button class="tab-btn{active}" data-tab="{cat_cfg["tab_id"]}">{cat_cfg["key"]}</button>'
        )
    tab_buttons.append('<button class="tab-btn" data-tab="clubs">Clubs</button>')

    # Build tab panels
    tab_panels = []
    for i, cat_cfg in enumerate(CATEGORIES):
        active = " active" if i == 0 else ""
        entries = by_category.get(cat_cfg["key"], [])

        cards = []
        for entry in entries:
            filepath = os.path.join(DIVISIONS_DIR, entry["file"])
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
            cards.append(render_division_card(data, cat_cfg["badge"]))

        panel = f"""<div class="tab-panel{active}" id="tab-{cat_cfg['tab_id']}">
<div class="cat-header">
<h2>{h(cat_cfg['label'])}</h2>
<p>{h(cat_cfg['desc'])}</p>
</div>
{"".join(cards)}
</div>"""
        tab_panels.append(panel)

    # Clubs tab
    tab_panels.append(f"""<div class="tab-panel" id="tab-clubs">
{render_clubs_tab(clubs)}
</div>""")

    # Assemble full page
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kumpoo Tervasulan Eliitti 2025</title>
<style>
{CSS}
</style>
</head>
<body>

<div class="hero">
<span class="shuttlecock">&#127992;</span>
<h1>Kumpoo Tervasulan Eliitti 2025</h1>
<p class="subtitle">Badminton Tournament Draws</p>
<div class="meta">
<span>Hosted by TeSu (Tervasulka)</span>
<span>badmintonfinland.tournamentsoftware.com</span>
</div>
</div>

<div class="stats-bar">
<div class="stat"><div class="num">{total_main_divisions}</div><div class="label">Divisions</div></div>
<div class="stat"><div class="num">{len(clubs)}</div><div class="label">Clubs</div></div>
<div class="stat"><div class="num">{total_players}+</div><div class="label">Players</div></div>
<div class="stat"><div class="num">{len(CATEGORIES)}</div><div class="label">Categories</div></div>
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
Kumpoo Tervasulan Eliitti 2025 &middot; Data from Badminton Finland Tournament Planner
</div>

<script>
{JS}
</script>
</body>
</html>"""

    return html


def main():
    print(f"Reading JSON files from: {DIVISIONS_DIR}/")
    html = generate_html()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Generated: {OUTPUT_FILE}")
    print(f"File size: {len(html):,} bytes")


if __name__ == "__main__":
    main()
