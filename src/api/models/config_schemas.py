"""Tournament configuration Pydantic models.

All tournament-specific data is parameterised here — nothing is hardcoded
for a particular tournament. The app works for any number of days, courts,
divisions, categories, match durations, and rest periods.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CourtAvailability(BaseModel):
    court: int
    available_from: str  # "09:00"
    available_to: str    # "22:00"


class DayConfig(BaseModel):
    label: str                              # "Saturday", "Sunday", "Day 1"
    date: str | None = None                 # "2025-11-15" (optional)
    courts: list[CourtAvailability]


class SessionConfig(BaseModel):
    name: str                               # "Saturday Morning"
    day_index: int                          # 0-based index into days[]
    start_time: str                         # "09:00"
    end_time: str                           # "13:00"


class CategoryConfig(BaseModel):
    id: str                                 # "elite", "junior", "open_a"
    label: str                              # "Elite", "Junior", "Open A"
    color: str = "#3182ce"                  # CSS hex color
    duration_minutes: int = 30
    rest_minutes: int = 30
    required_courts: list[int] | None = None     # Must use these courts
    preferred_courts: list[int] | None = None    # Try these first
    sf_final_day_index: int | None = None        # SF/Final must be on this day


class TournamentConfig(BaseModel):
    name: str = ""
    slot_duration_minutes: int = 30
    days: list[DayConfig] = Field(default_factory=list)
    sessions: list[SessionConfig] = Field(default_factory=list)
    categories: list[CategoryConfig] = Field(default_factory=list)
    division_category_map: dict[str, str] = Field(default_factory=dict)


def time_str_to_minutes(time_str: str) -> int:
    """Convert "HH:MM" to minutes from midnight."""
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def minutes_to_time_str(minutes: int) -> int:
    """Convert minutes from midnight to "HH:MM"."""
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"
