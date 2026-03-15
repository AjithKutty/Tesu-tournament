"""Tournament configuration service — load/save configs, templates, auto-mapping."""

from __future__ import annotations

import json
import os
import re

from api.models.config_schemas import TournamentConfig

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


# ── Division-to-category auto-suggestion ───────────────────────

# Patterns to guess category from division code
_CATEGORY_PATTERNS = [
    (re.compile(r"^[A-Z]{2,3}\s+V$"), "elite"),           # "MS V", "WS V", "XD V"
    (re.compile(r"^[A-Z]{2,3}\s+A$"), "open_a"),           # "MS A", "MD A"
    (re.compile(r"^[A-Z]{2,3}\s+B$"), "open_b"),           # "MS B", "MD B"
    (re.compile(r"^[A-Z]{2,3}\s+C$"), "open_c"),           # "MS C", "MD C"
    (re.compile(r"^[A-Z]{2,3}\s+U\d+"), "junior"),         # "BS U17", "BD U13"
    (re.compile(r"^[A-Z]{2,3}\s+\d{2,3}$"), "veterans"),   # "MS 35", "MD 45"
]


def suggest_category(division_code: str, available_categories: list[str]) -> str | None:
    """Suggest a category ID for a division code based on naming patterns."""
    for pattern, cat_id in _CATEGORY_PATTERNS:
        if pattern.match(division_code) and cat_id in available_categories:
            return cat_id
    return None


def suggest_division_map(division_codes: list[str], config: TournamentConfig) -> dict[str, str | None]:
    """Auto-suggest category mapping for all divisions."""
    available = [c.id for c in config.categories]
    result = {}
    for code in division_codes:
        result[code] = suggest_category(code, available)
    return result


# ── Template management ────────────────────────────────────────

def list_templates() -> list[dict]:
    """List available built-in templates."""
    templates = []
    if not os.path.isdir(TEMPLATES_DIR):
        return templates
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if fname.endswith(".json"):
            path = os.path.join(TEMPLATES_DIR, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                templates.append({
                    "id": fname.replace(".json", ""),
                    "name": data.get("name", fname),
                    "file": fname,
                })
            except (json.JSONDecodeError, OSError):
                pass
    return templates


def load_template(template_id: str) -> TournamentConfig:
    """Load a built-in template by ID."""
    path = os.path.join(TEMPLATES_DIR, f"{template_id}.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Template not found: {template_id}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return TournamentConfig(**data)


# ── Save / Load config ────────────────────────────────────────

def save_config(config: TournamentConfig, path: str):
    """Save tournament config to a JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)


def load_config(path: str) -> TournamentConfig:
    """Load tournament config from a JSON file."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return TournamentConfig(**data)
