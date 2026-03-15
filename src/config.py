"""
Load tournament configuration from YAML files.

Each tournament directory contains a config/ subdirectory with:
  tournament.yaml, venue.yaml, match_rules.yaml,
  court_preferences.yaml, divisions.yaml, scheduling.yaml
"""

import os
import yaml


def _load_yaml(path):
    """Load a YAML file, returning empty dict if missing."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(tournament_dir):
    """Load all config files from a tournament directory.

    Returns a dict with keys: tournament, venue, match_rules,
    court_preferences, divisions, scheduling, and resolved paths.
    """
    config_dir = os.path.join(tournament_dir, "config")

    tournament = _load_yaml(os.path.join(config_dir, "tournament.yaml"))
    venue = _load_yaml(os.path.join(config_dir, "venue.yaml"))
    match_rules = _load_yaml(os.path.join(config_dir, "match_rules.yaml"))
    court_prefs = _load_yaml(os.path.join(config_dir, "court_preferences.yaml"))
    divisions = _load_yaml(os.path.join(config_dir, "divisions.yaml"))
    scheduling = _load_yaml(os.path.join(config_dir, "scheduling.yaml"))

    # Resolve directory paths
    paths = {
        "tournament_dir": os.path.abspath(tournament_dir),
        "config_dir": os.path.abspath(config_dir),
        "input_dir": os.path.abspath(os.path.join(tournament_dir, "input")),
        "scraped_dir": os.path.abspath(os.path.join(tournament_dir, "scraped")),
        "divisions_dir": os.path.abspath(os.path.join(tournament_dir, "output", "divisions")),
        "schedules_dir": os.path.abspath(os.path.join(tournament_dir, "output", "schedules")),
        "webpages_dir": os.path.abspath(os.path.join(tournament_dir, "output", "webpages")),
    }

    return {
        "tournament": tournament,
        "venue": venue,
        "match_rules": match_rules,
        "court_preferences": court_prefs,
        "divisions": divisions,
        "scheduling": scheduling,
        "paths": paths,
    }


# ── Config accessor helpers ──────────────────────────────────────


def get_tournament_name(config):
    """Get tournament name from config."""
    return config["tournament"].get("name", "Tournament")


def get_event_names(config):
    """Get event code → full name mapping."""
    return config["divisions"].get("event_names", {
        "MS": "Men's Singles",
        "WS": "Women's Singles",
        "MD": "Men's Doubles",
        "WD": "Women's Doubles",
        "XD": "Mixed Doubles",
        "BS": "Boys' Singles",
        "BD": "Boys' Doubles",
    })


def get_level_categories(config):
    """Get level → category mapping."""
    return config["divisions"].get("level_categories", {
        "A": "Open A", "B": "Open B", "C": "Open C",
        "U11": "Junior", "U13": "Junior", "U15": "Junior", "U17": "Junior",
        "35": "Veterans", "45": "Veterans", "V": "Elite",
    })


def get_doubles_events(config):
    """Get set of doubles event codes."""
    return set(config["divisions"].get("doubles_events", ["MD", "WD", "XD", "BD"]))


def get_category_order(config):
    """Get ordered list of category names from tabs config."""
    tabs = config["divisions"].get("tabs", [])
    return [t["category"] for t in tabs]


def get_tab_config(config):
    """Get tab display configuration."""
    return config["divisions"].get("tabs", [])


def get_format_overrides(config):
    """Get per-division format overrides."""
    return config["divisions"].get("format_overrides", {})


def get_slot_duration(config):
    """Get scheduling slot duration in minutes."""
    return config["venue"].get("slot_duration", 30)


def get_match_duration(config, category):
    """Get match duration for a category."""
    cats = config["match_rules"].get("categories", {})
    if category in cats:
        return cats[category].get("match_duration",
                                  config["match_rules"].get("default", {}).get("match_duration", 30))
    return config["match_rules"].get("default", {}).get("match_duration", 30)


def get_rest_period(config, category):
    """Get rest period for a category."""
    cats = config["match_rules"].get("categories", {})
    if category in cats:
        return cats[category].get("rest_period",
                                  config["match_rules"].get("default", {}).get("rest_period", 30))
    return config["match_rules"].get("default", {}).get("rest_period", 30)


def get_court_preference(config, category):
    """Get court preference chain for a category.

    Returns dict with keys: required_courts, preferred_courts,
    fallback_courts, last_resort_courts (each a list or None).
    """
    cats = config["court_preferences"].get("categories", {})
    default = config["court_preferences"].get("default", {})

    if category in cats:
        entry = cats[category]
    else:
        entry = default

    return {
        "required_courts": entry.get("required_courts"),
        "preferred_courts": entry.get("preferred_courts", default.get("preferred_courts")),
        "fallback_courts": entry.get("fallback_courts", default.get("fallback_courts")),
        "last_resort_courts": entry.get("last_resort_courts", default.get("last_resort_courts")),
    }


def get_priorities(config):
    """Get priority name → numeric value mapping."""
    return config["scheduling"].get("priorities", {
        "elite_pool": 5, "pool": 10, "round_1": 20, "group_playoff": 30,
        "round_2": 40, "quarter_final": 50, "semi_final": 60, "final": 70,
    })


def get_round_priority_map(config):
    """Get round name → priority key mapping."""
    return config["scheduling"].get("round_priority_map", {
        "Round 1": "round_1", "Round 2": "round_2",
        "Quarter-Final": "quarter_final",
        "Semi-Final": "semi_final", "Final": "final",
    })


def get_elite_divisions(config):
    """Get set of division codes that get elite priority."""
    return set(config["scheduling"].get("elite_divisions", []))


def get_day_constraints(config):
    """Get day constraints (rounds that must be on a specific day)."""
    return config["scheduling"].get("day_constraints", [])


# ── Venue model ──────────────────────────────────────────────────


def build_venue_model(config):
    """Build the time/court model from venue config.

    Returns a dict with:
      - slot_duration: int (minutes)
      - days: list of day dicts with minute offsets
      - sessions: list of session dicts with minute offsets
      - all_courts: set of all court numbers
      - all_slots: sorted list of all time slots (minute offsets)
      - day_start_minutes: dict of day_name -> start minute offset
    """
    slot_duration = get_slot_duration(config)
    days_config = config["venue"].get("days", [])

    days = []
    sessions = []
    all_courts = set()
    all_slots = []
    day_start_minutes = {}
    # Court availability: list of (court, start_minute, end_minute)
    court_windows = []

    current_minute = 0

    for day_cfg in days_config:
        day_name = day_cfg["name"]
        day_start_h, day_start_m = map(int, day_cfg["start_time"].split(":"))
        day_start_minutes[day_name] = current_minute

        # Compute court windows for this day
        for court_group in day_cfg.get("courts", []):
            end_h, end_m = map(int, court_group["end_time"].split(":"))
            # Minutes from day start to court end
            court_end_offset = (end_h - day_start_h) * 60 + (end_m - day_start_m)

            for court_num in court_group["numbers"]:
                all_courts.add(court_num)
                court_windows.append((court_num, current_minute, current_minute + court_end_offset))

        # Compute day end (latest court end)
        day_end_offsets = []
        for court_group in day_cfg.get("courts", []):
            end_h, end_m = map(int, court_group["end_time"].split(":"))
            day_end_offsets.append((end_h - day_start_h) * 60 + (end_m - day_start_m))
        day_end = current_minute + max(day_end_offsets) if day_end_offsets else current_minute

        # Generate slots for this day
        t = current_minute
        while t < day_end:
            all_slots.append(t)
            t += slot_duration

        # Process sessions for this day
        for sess_cfg in day_cfg.get("sessions", []):
            sess_start_h, sess_start_m = map(int, sess_cfg["start_time"].split(":"))
            sess_end_h, sess_end_m = map(int, sess_cfg["end_time"].split(":"))

            sess_start_offset = (sess_start_h - day_start_h) * 60 + (sess_start_m - day_start_m)
            sess_end_offset = (sess_end_h - day_start_h) * 60 + (sess_end_m - day_start_m)

            sess_file = sess_cfg["name"].replace(" ", "_") + ".json"
            sessions.append({
                "name": sess_cfg["name"],
                "file": sess_file,
                "date": day_name,
                "start": current_minute + sess_start_offset,
                "end": current_minute + sess_end_offset,
                "start_time": sess_cfg["start_time"],
                "end_time": sess_cfg["end_time"],
            })

        days.append({
            "name": day_name,
            "start_minute": current_minute,
            "end_minute": day_end,
            "start_time": day_cfg["start_time"],
        })

        # Next day starts after a gap (assume 24h from start to start)
        current_minute += 24 * 60

    all_slots.sort()

    return {
        "slot_duration": slot_duration,
        "days": days,
        "sessions": sessions,
        "all_courts": all_courts,
        "all_slots": all_slots,
        "day_start_minutes": day_start_minutes,
        "court_windows": court_windows,
    }


def minute_to_display(venue_model, minute):
    """Convert minute offset to (day_name, 'HH:MM')."""
    for day in venue_model["days"]:
        if day["start_minute"] <= minute < day["start_minute"] + 24 * 60:
            offset = minute - day["start_minute"]
            start_h, start_m = map(int, day["start_time"].split(":"))
            total_minutes = start_h * 60 + start_m + offset
            h = total_minutes // 60
            m = total_minutes % 60
            return day["name"], f"{h:02d}:{m:02d}"
    # Fallback
    h, m = divmod(minute, 60)
    return "Unknown", f"{h:02d}:{m:02d}"
