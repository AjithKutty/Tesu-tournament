"""Import API routes — Excel and web scraping."""

import os
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile, File

from api.models.schemas import ImportWebRequest, ImportResponse, DivisionSummary
from api.state.tournament_state import get_state
from api.services import import_service, config_service

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/excel", response_model=ImportResponse)
async def import_excel(file: UploadFile = File(...)):
    """Import tournament data from an Excel file."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are accepted")

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        summary = import_service.import_excel(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
    finally:
        os.unlink(tmp_path)

    # Load matches into state
    state = get_state()
    state.load_matches()

    # Auto-suggest category mapping
    div_codes = [d["code"] for d in summary["divisions"]]
    suggestions = config_service.suggest_division_map(div_codes, state.config)

    divisions = []
    for d in summary["divisions"]:
        divisions.append(DivisionSummary(
            code=d["code"],
            name=d["name"],
            suggested_category=suggestions.get(d["code"]),
        ))

    return ImportResponse(
        tournament_name=summary["tournament_name"],
        division_count=summary["division_count"],
        match_count=summary["match_count"],
        player_count=summary["player_count"],
        divisions=divisions,
    )


@router.post("/web", response_model=ImportResponse)
async def import_web(req: ImportWebRequest):
    """Import tournament data from tournamentsoftware.com."""
    if "tournamentsoftware.com" not in req.url:
        raise HTTPException(status_code=400, detail="URL must be from tournamentsoftware.com")

    try:
        summary = import_service.import_web(req.url, full_results=req.full_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")

    # Load matches into state
    state = get_state()
    state.load_matches()

    # Auto-suggest category mapping
    div_codes = [d["code"] for d in summary["divisions"]]
    suggestions = config_service.suggest_division_map(div_codes, state.config)

    divisions = []
    for d in summary["divisions"]:
        divisions.append(DivisionSummary(
            code=d["code"],
            name=d["name"],
            suggested_category=suggestions.get(d["code"]),
        ))

    return ImportResponse(
        tournament_name=summary["tournament_name"],
        division_count=summary["division_count"],
        match_count=summary["match_count"],
        player_count=summary["player_count"],
        divisions=divisions,
    )
