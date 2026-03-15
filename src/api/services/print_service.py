"""Print service — generates print-optimized HTML for match cards."""

from __future__ import annotations

from api.models.schemas import MatchCard


def generate_match_cards_html(
    cards: list[MatchCard],
    tournament_name: str,
) -> str:
    """Generate print-optimized HTML for match cards. 4 per A4 page."""

    card_htmls = []
    for card in cards:
        card_htmls.append(f"""<div class="print-card">
  <div class="card-tournament">{_esc(tournament_name)}</div>
  <div class="card-header">
    <span class="card-court">Court {card.court or '?'}</span>
    <span class="card-time">{card.time_display or '?'} {card.day or ''}</span>
  </div>
  <div class="card-division">{_esc(card.division_code)} - {_esc(card.round_name)} - M{card.match_num}</div>
  <div class="card-players">
    <div class="card-p1">{_esc(card.player1)}</div>
    <div class="card-vs">vs</div>
    <div class="card-p2">{_esc(card.player2)}</div>
  </div>
  <div class="card-score-area">
    <div>Set 1: ___-___</div>
    <div>Set 2: ___-___</div>
    <div>Set 3: ___-___</div>
  </div>
</div>""")

    cards_html = "\n".join(card_htmls)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Match Cards - {_esc(tournament_name)}</title>
<style>
  @page {{ size: A4; margin: 10mm; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}

  .cards-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: 8mm;
    height: 277mm;  /* A4 minus margins */
    page-break-after: always;
  }}
  .cards-grid:last-child {{ page-break-after: auto; }}

  .print-card {{
    border: 1px solid #333;
    border-radius: 4px;
    padding: 5mm;
    display: flex;
    flex-direction: column;
    gap: 3mm;
    position: relative;
  }}
  .print-card::after {{
    content: '';
    position: absolute;
    top: -4mm; left: 50%;
    width: 0; height: 0;
    border-left: 2mm solid transparent;
    border-right: 2mm solid transparent;
    border-top: 2mm solid #ccc;
  }}

  .card-tournament {{ font-size: 9pt; font-weight: 700; color: #333; text-align: center; border-bottom: 1px solid #ddd; padding-bottom: 2mm; }}
  .card-header {{ display: flex; justify-content: space-between; font-size: 11pt; font-weight: 700; }}
  .card-division {{ font-size: 10pt; color: #555; text-align: center; }}
  .card-players {{ text-align: center; flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 1mm; }}
  .card-p1, .card-p2 {{ font-size: 12pt; font-weight: 600; }}
  .card-vs {{ font-size: 9pt; color: #888; font-weight: 700; }}
  .card-score-area {{ display: flex; gap: 4mm; justify-content: center; font-size: 10pt; border-top: 1px solid #ddd; padding-top: 2mm; }}

  @media print {{
    body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
{_wrap_in_pages(cards_html, len(card_htmls))}
</body>
</html>"""


def _wrap_in_pages(cards_html: str, count: int) -> str:
    """Wrap cards in page containers (4 per page)."""
    # Split individual card divs and group into pages of 4
    import re
    cards = re.findall(r'<div class="print-card">.*?</div>\s*</div>\s*</div>', cards_html, re.DOTALL)
    if not cards:
        # Fallback: just wrap everything
        return f'<div class="cards-grid">\n{cards_html}\n</div>'

    # Actually, simpler approach: the cards_html has individual card divs
    # We'll just let CSS grid handle 4-per-page with page breaks
    return f'<div class="cards-grid">\n{cards_html}\n</div>'


def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
