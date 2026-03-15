"""Results API routes — score entry and web fetch."""

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    ResultUpdateRequest, ResultUpdateResponse,
    FetchWebResultsRequest, FetchWebResultsResponse,
)
from api.state.tournament_state import get_state
from api.services import import_service

router = APIRouter(prefix="/api/results", tags=["results"])


@router.post("/update", response_model=ResultUpdateResponse)
async def update_result(req: ResultUpdateRequest):
    state = get_state()
    try:
        card, resolved = state.update_result(req.match_id, req.score)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ResultUpdateResponse(match=card, resolved_matches=resolved)


@router.post("/fetch-web", response_model=FetchWebResultsResponse)
async def fetch_web_results(req: FetchWebResultsRequest):
    """Fetch latest results from tournamentsoftware.com and merge into state."""
    if "tournamentsoftware.com" not in req.url:
        raise HTTPException(status_code=400, detail="URL must be from tournamentsoftware.com")

    try:
        summary = import_service.import_web(req.url, full_results=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Web fetch failed: {e}")

    # Reload matches and merge results
    state = get_state()
    old_results = dict(state.results)
    old_scheduled = dict(state.scheduled)
    old_pinned = set(state.pinned)

    state.load_matches()

    # Restore previous state
    state.results = old_results
    state.scheduled = {k: v for k, v in old_scheduled.items() if k in state.match_by_id}
    state.pinned = {p for p in old_pinned if p in state.match_by_id}

    # TODO: Extract new results from the re-imported data
    # For now, return empty since the full implementation needs
    # result extraction from the web scraper output

    return FetchWebResultsResponse(
        updated_matches=[],
        new_results_count=0,
    )
