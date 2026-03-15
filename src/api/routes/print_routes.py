"""Print API routes — match card HTML generation."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from api.models.schemas import PrintRequest
from api.state.tournament_state import get_state
from api.services.print_service import generate_match_cards_html

router = APIRouter(prefix="/api/print", tags=["print"])


@router.post("/match-cards", response_class=HTMLResponse)
async def print_match_cards(req: PrintRequest):
    """Generate printable HTML for match cards."""
    state = get_state()

    # Filter matches based on request
    cards = []
    if req.match_ids:
        for mid in req.match_ids:
            match = state.match_by_id.get(mid)
            if match:
                cards.append(state._match_to_card(match))
    elif req.time_minute is not None:
        for match in state.matches:
            if match.id in state.scheduled:
                _, minute = state.scheduled[match.id]
                if minute == req.time_minute:
                    cards.append(state._match_to_card(match))
    else:
        # All scheduled matches
        for match in state.matches:
            if match.id in state.scheduled:
                cards.append(state._match_to_card(match))

    # Sort by court, then time
    cards.sort(key=lambda c: (c.court or 0, c.time_minute or 0))

    html = generate_match_cards_html(cards, state.config.name)
    return HTMLResponse(content=html)
