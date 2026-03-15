"""Export API routes — website and schedule JSON generation."""

import sys
import os

from fastapi import APIRouter, HTTPException

from api.models.schemas import ExportResponse
from api.state.tournament_state import get_state

SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

BASE_DIR = os.path.dirname(SRC_DIR)

router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/website", response_model=ExportResponse)
async def export_website():
    """Generate the HTML website using the existing generate_website.py."""
    try:
        from generate_website import main as website_main
        website_main()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Website generation failed: {e}")

    path = os.path.join(BASE_DIR, "output", "webpages", "index.html")
    return ExportResponse(path=path)


@router.post("/schedule", response_model=ExportResponse)
async def export_schedule():
    """Write current schedule state to JSON files."""
    state = get_state()
    if not state.matches:
        raise HTTPException(status_code=400, detail="No matches loaded")

    try:
        from generate_schedule import write_schedules
        warnings = [c.message for c in state.validate_all()]
        write_schedules(
            state.matches, state.match_by_id,
            state.scheduled,
            [m for m in state.matches if m.id not in state.scheduled],
            warnings,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Schedule export failed: {e}")

    path = os.path.join(BASE_DIR, "output", "schedules")
    return ExportResponse(path=path)
