"""
Load tournament configuration from YAML files.

Each tournament directory contains a config/ subdirectory with:
  tournament.yaml, venue.yaml, court_preferences.yaml,
  divisions.yaml, scheduling.yaml
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

    Returns a dict with keys: tournament, venue, court_preferences,
    divisions, scheduling, and resolved paths.
    """
    config_dir = os.path.join(tournament_dir, "config")

    tournament = _load_yaml(os.path.join(config_dir, "tournament.yaml"))
    venue = _load_yaml(os.path.join(config_dir, "venue.yaml"))
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


def get_draw_format(config, div_code, category, entry_count):
    """Determine draw format for a division when generating from entries.

    Resolution order:
      1. Per-division override in scheduling.draw_formats.divisions
      2. Per-category default in scheduling.draw_formats.categories
      3. Global default in scheduling.draw_formats.default
      4. Fallback: round_robin if <=6, elimination otherwise

    Returns (format_str, params_dict) where params_dict may contain
    'groups' and 'advancers_per_group' for group_playoff format.
    """
    df = config["scheduling"].get("draw_formats", {})
    divisions_cfg = df.get("divisions", {})
    categories_cfg = df.get("categories", {})
    default_fmt = df.get("default", None)

    # 1. Per-division override
    if div_code in divisions_cfg:
        div_cfg = divisions_cfg[div_code]
        if isinstance(div_cfg, dict):
            fmt = div_cfg.get("format", "elimination")
            params = {k: v for k, v in div_cfg.items() if k != "format"}
            return fmt, params
        else:
            return str(div_cfg), {}

    # 2. Per-category default
    if category in categories_cfg:
        cat_fmt = categories_cfg[category]
        if isinstance(cat_fmt, dict):
            fmt = cat_fmt.get("format", "elimination")
            params = {k: v for k, v in cat_fmt.items() if k != "format"}
            return fmt, params
        else:
            return str(cat_fmt), {}

    # 3. Global default (only for >6 entries)
    if entry_count <= 6:
        return "round_robin", {}

    if default_fmt:
        if isinstance(default_fmt, dict):
            fmt = default_fmt.get("format", "elimination")
            params = {k: v for k, v in default_fmt.items() if k != "format"}
            return fmt, params
        return str(default_fmt), {}

    # 4. Hardcoded fallback
    return "elimination", {}


def get_slot_duration(config):
    """Get scheduling slot duration in minutes."""
    return config["venue"].get("slot_duration", 30)


def _resolve_category_key(cats, category, config):
    """Look up a category in a config dict, trying both full name and level code.

    Supports e.g. both "Open A" (full category) and "A" (level code).
    """
    if category in cats:
        return cats[category]
    # Try matching via level_categories: if a level maps to this category,
    # check if that level code is a key in cats
    level_cats = config.get("divisions", {}).get("level_categories", {})
    for level, cat_name in level_cats.items():
        if cat_name == category and level in cats:
            return cats[level]
    return None


def get_match_duration(config, category):
    """Get match duration for a category from scheduling.match_duration."""
    md = config["scheduling"].get("match_duration", {})
    cats = md.get("categories", {})
    val = _resolve_category_key(cats, category, config)
    if val is not None:
        return val
    return md.get("default", 30)


def get_overrun_buffer(config, category):
    """Get overrun buffer for a category (minutes) from scheduling.overrun_buffer.

    The buffer creates a gap between consecutive matches on the same
    court, absorbing potential overruns.  Returns 0 if not configured.
    """
    ob = config["scheduling"].get("overrun_buffer", {})
    cats = ob.get("categories", {})
    val = _resolve_category_key(cats, category, config)
    if val is not None:
        return val
    return ob.get("default", 0)


# ── Rest rule accessors ──────────────────────────────────────────


def get_rest_rules(config):
    """Get the full rest_rules dict from scheduling config."""
    return config["scheduling"].get("rest_rules", {})


def get_same_division_rest(config, div_code):
    """Get rest period between games in the same division for a player."""
    rules = get_rest_rules(config)
    sd = rules.get("same_division_rest", {})
    divs = sd.get("divisions", {})
    if div_code in divs:
        return divs[div_code]
    return sd.get("default", 30)


def get_same_category_rest(config, category):
    """Get rest period between games in different divisions of the same category."""
    rules = get_rest_rules(config)
    sc = rules.get("same_category_rest", {})
    cats = sc.get("categories", {})
    val = _resolve_category_key(cats, category, config)
    if val is not None:
        return val
    return sc.get("default", 30)


def get_cross_division_rest(config):
    """Get minimum rest period between games in any two divisions."""
    rules = get_rest_rules(config)
    return rules.get("cross_division_rest", 30)


def get_player_rest_exception(config, player_name, div_code_a, div_code_b):
    """Check for a per-player rest exception between two divisions.

    Returns the overridden rest in minutes, or None if no exception applies.
    """
    rules = get_rest_rules(config)
    exceptions = rules.get("player_exceptions", {})
    player_exc = exceptions.get(player_name)
    if not player_exc:
        return None
    for exc in player_exc:
        pair = exc.get("between", [])
        if len(pair) == 2:
            if (div_code_a in pair and div_code_b in pair):
                return exc.get("rest", 0)
    return None


def compute_rest_between(config, div_code_a, category_a, div_code_b, category_b,
                         player_name=None):
    """Compute the required rest between two matches for the same player.

    Takes the division code and category of both matches and returns
    the maximum applicable rest period (in minutes).

    Rules applied (max of all applicable):
      - cross_division_rest: always applies
      - same_category_rest: if both matches are in the same category
      - same_division_rest: if both matches are in the same division

    If player_name is given, per-player exceptions are checked first.
    A player exception overrides all other rules for that division pair.
    """
    # Check per-player exception first
    if player_name:
        exc = get_player_rest_exception(config, player_name, div_code_a, div_code_b)
        if exc is not None:
            return exc

    rest = get_cross_division_rest(config)

    if category_a == category_b:
        rest = max(rest, get_same_category_rest(config, category_a))

    if div_code_a == div_code_b:
        rest = max(rest, get_same_division_rest(config, div_code_a))

    return rest


def get_court_preference(config, category, day_name=None):
    """Get court preference chain for a category, optionally for a specific day.

    If day_name is provided and the category has a day_overrides section
    with an entry for that day, the day-specific preferences are used
    (merged on top of the category defaults).

    Returns dict with keys: required_courts, preferred_courts,
    fallback_courts, last_resort_courts (each a list or None).
    """
    cats = config["court_preferences"].get("categories", {})
    default = config["court_preferences"].get("default", {})

    if category in cats:
        entry = cats[category]
    else:
        entry = default

    # Start with the base preference for this category
    result = {
        "required_courts": entry.get("required_courts"),
        "preferred_courts": entry.get("preferred_courts", default.get("preferred_courts")),
        "fallback_courts": entry.get("fallback_courts", default.get("fallback_courts")),
        "last_resort_courts": entry.get("last_resort_courts", default.get("last_resort_courts")),
    }

    # Apply day-specific overrides if present
    if day_name and category in cats:
        day_overrides = cats[category].get("day_overrides", {})
        if day_name in day_overrides:
            day_entry = day_overrides[day_name]
            for key in ("required_courts", "preferred_courts", "fallback_courts", "last_resort_courts"):
                if key in day_entry:
                    result[key] = day_entry[key]

    return result


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
    """Get global day constraints (rounds that must be on a specific day)."""
    return config["scheduling"].get("day_constraints", [])


def get_division_day_constraints(config):
    """Get per-division day constraints.

    Returns dict: division_code -> list of {rounds: [...], day: "..."}
    """
    return config["scheduling"].get("division_day_constraints", {})


def get_round_completion(config):
    """Get round-completion constraint settings.

    Returns (enabled, exceptions_set).
    When enabled, all matches in a round must finish before the next round
    starts (per division). Exceptions are division codes exempt from this rule.
    """
    rc = config["scheduling"].get("round_completion", {})
    enabled = rc.get("enabled", False)
    exceptions = set(rc.get("exceptions", []))
    return enabled, exceptions


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

    # Build court buffer blocks: list of (court, minute) to pre-block
    court_buffer_blocks = []
    buffers_config = config["venue"].get("court_buffers", [])
    for buf in buffers_config:
        pool = buf.get("courts", [])
        duration = buf.get("duration", 30)
        interval = buf.get("interval", 120)
        at_once = buf.get("courts_at_once", len(pool))
        buffer_slots = (duration + slot_duration - 1) // slot_duration

        # Apply buffers to each day
        for day in days:
            day_start = day["start_minute"]
            day_end = day["end_minute"]
            # Available courts from the pool on this day
            day_pool = [c for c in pool
                        if any(crt == c and s <= day_start < e
                               for crt, s, e in court_windows)]
            if not day_pool:
                continue

            # Generate buffer times at each interval from day start
            rotation_idx = 0
            t = day_start + interval
            while t < day_end:
                # Pick which courts to block (rotate through pool)
                start_idx = (rotation_idx * at_once) % len(day_pool)
                blocked_courts = []
                for i in range(at_once):
                    blocked_courts.append(day_pool[(start_idx + i) % len(day_pool)])

                for court in blocked_courts:
                    for s in range(buffer_slots):
                        court_buffer_blocks.append((court, t + s * slot_duration))

                rotation_idx += 1
                t += interval

    return {
        "slot_duration": slot_duration,
        "days": days,
        "sessions": sessions,
        "all_courts": all_courts,
        "all_slots": all_slots,
        "day_start_minutes": day_start_minutes,
        "court_windows": court_windows,
        "court_buffer_blocks": court_buffer_blocks,
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
