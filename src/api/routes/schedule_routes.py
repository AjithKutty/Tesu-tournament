"""Schedule API routes — generate, move, swap, validate."""

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    ScheduleState, MoveRequest, MoveResponse, SwapRequest, SwapResponse,
    UnscheduleRequest, PinRequest, ValidateMoveRequest, ValidateResponse,
    GenerateRequest, MatchCard,
)
from api.state.tournament_state import get_state

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("", response_model=ScheduleState)
async def get_schedule():
    state = get_state()
    if not state.matches:
        return ScheduleState()
    return state.get_schedule_state()


@router.post("/generate", response_model=ScheduleState)
async def generate_schedule(req: GenerateRequest):
    state = get_state()
    if not state.matches:
        raise HTTPException(status_code=400, detail="No matches loaded. Import data first.")
    return state.generate_schedule(keep_pinned=req.keep_pinned)


@router.post("/move", response_model=MoveResponse)
async def move_match(req: MoveRequest):
    state = get_state()
    try:
        card, conflicts = state.move_match(req.match_id, req.court, req.time_minute)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return MoveResponse(match=card, conflicts=conflicts)


@router.post("/swap", response_model=SwapResponse)
async def swap_matches(req: SwapRequest):
    state = get_state()
    try:
        cards, conflicts = state.swap_matches(req.match_id_a, req.match_id_b)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SwapResponse(matches=cards, conflicts=conflicts)


@router.post("/unschedule", response_model=MatchCard)
async def unschedule_match(req: UnscheduleRequest):
    state = get_state()
    try:
        return state.unschedule_match(req.match_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/pin", response_model=MatchCard)
async def pin_match(req: PinRequest):
    state = get_state()
    try:
        return state.pin_match(req.match_id, req.pinned)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/validate", response_model=ValidateResponse)
async def validate_schedule():
    state = get_state()
    conflicts = state.validate_all()
    return ValidateResponse(conflicts=conflicts)


@router.post("/validate-move", response_model=ValidateResponse)
async def validate_move(req: ValidateMoveRequest):
    state = get_state()
    conflicts = state.validate_move_preview(req.match_id, req.court, req.time_minute)
    return ValidateResponse(conflicts=conflicts)
