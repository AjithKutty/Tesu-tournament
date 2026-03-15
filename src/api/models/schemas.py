"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MatchCard(BaseModel):
    id: str
    division_code: str
    division_name: str
    category_id: str
    category_label: str
    category_color: str
    round_name: str
    match_num: int
    player1: str
    player2: str
    duration_min: int
    is_sf_or_final: bool
    has_real_players: bool
    prerequisites: list[str] = Field(default_factory=list)
    result: str | None = None
    court: int | None = None
    time_minute: int | None = None
    time_display: str | None = None
    day: str | None = None
    pinned: bool = False
    conflict_ids: list[str] = Field(default_factory=list)


class Conflict(BaseModel):
    id: str
    type: str       # "double_booking", "rest_violation", "wrong_court", etc.
    severity: str   # "error" or "warning"
    match_ids: list[str]
    message: str
    player: str | None = None


class SessionInfo(BaseModel):
    name: str
    day_label: str
    start_time: str
    end_time: str
    start_minute: int
    end_minute: int
    courts: list[int]
    match_count: int = 0


class ScheduleState(BaseModel):
    matches: list[MatchCard] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    unscheduled: list[str] = Field(default_factory=list)
    sessions: list[SessionInfo] = Field(default_factory=list)


# ── Request models ─────────────────────────────────────────────

class ImportWebRequest(BaseModel):
    url: str
    full_results: bool = False


class MoveRequest(BaseModel):
    match_id: str
    court: int
    time_minute: int


class SwapRequest(BaseModel):
    match_id_a: str
    match_id_b: str


class UnscheduleRequest(BaseModel):
    match_id: str


class PinRequest(BaseModel):
    match_id: str
    pinned: bool


class ValidateMoveRequest(BaseModel):
    match_id: str
    court: int
    time_minute: int


class ResultUpdateRequest(BaseModel):
    match_id: str
    score: str


class FetchWebResultsRequest(BaseModel):
    url: str


class PrintRequest(BaseModel):
    time_minute: int | None = None
    match_ids: list[str] | None = None


class GenerateRequest(BaseModel):
    keep_pinned: bool = True


class DivisionMapRequest(BaseModel):
    division_category_map: dict[str, str]


class FilePathRequest(BaseModel):
    path: str


# ── Response models ────────────────────────────────────────────

class ImportResponse(BaseModel):
    tournament_name: str
    division_count: int
    match_count: int
    player_count: int
    divisions: list[DivisionSummary] = Field(default_factory=list)


class DivisionSummary(BaseModel):
    code: str
    name: str
    suggested_category: str | None = None


class MoveResponse(BaseModel):
    match: MatchCard
    conflicts: list[Conflict] = Field(default_factory=list)


class SwapResponse(BaseModel):
    matches: list[MatchCard]
    conflicts: list[Conflict] = Field(default_factory=list)


class ValidateResponse(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)


class ResultUpdateResponse(BaseModel):
    match: MatchCard
    resolved_matches: list[MatchCard] = Field(default_factory=list)


class FetchWebResultsResponse(BaseModel):
    updated_matches: list[MatchCard] = Field(default_factory=list)
    new_results_count: int = 0


class ExportResponse(BaseModel):
    path: str
