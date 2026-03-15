"""Configuration API routes."""

from fastapi import APIRouter, HTTPException

from api.models.config_schemas import TournamentConfig
from api.models.schemas import DivisionMapRequest, FilePathRequest
from api.state.tournament_state import get_state
from api.services import config_service

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=TournamentConfig)
async def get_config():
    return get_state().config


@router.post("", response_model=TournamentConfig)
async def set_config(config: TournamentConfig):
    get_state().set_config(config)
    return get_state().config


@router.get("/templates")
async def get_templates():
    return {"templates": config_service.list_templates()}


@router.post("/load", response_model=TournamentConfig)
async def load_config(req: FilePathRequest):
    try:
        config = config_service.load_config(req.path)
        get_state().set_config(config)
        return config
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Config file not found: {req.path}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/save")
async def save_config(req: FilePathRequest):
    try:
        config_service.save_config(get_state().config, req.path)
        return {"path": req.path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/division-map", response_model=TournamentConfig)
async def set_division_map(req: DivisionMapRequest):
    state = get_state()
    state.config.division_category_map = req.division_category_map
    state._rebuild_category_map()
    # Reload matches with updated category durations/rest
    if state.matches:
        for match in state.matches:
            cat = state.get_category_for_division(match.division_code)
            if cat:
                match.duration_min = cat.duration_minutes
                match.rest_min = cat.rest_minutes
    return state.config
