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


def get_match_duration(config, category, div_code=None):
    """Get match duration from scheduling.match_duration.

    Resolution order: per-division override → per-category → default.
    """
    md = config["scheduling"].get("match_duration", {})
    # Per-division override (highest precedence)
    if div_code:
        divs = md.get("divisions", {})
        if div_code in divs:
            return divs[div_code]
    # Per-category
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


def get_court_preference(config, category, day_name=None, round_name=None):
    """Get court preference chain for a category.

    Overrides applied in order (later overrides earlier):
      1. Base category preference (or default)
      2. Day-specific overrides (day_overrides)
      3. Round-specific overrides (round_overrides within the category)

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

    # Apply round-specific overrides (e.g., Junior SF/Final on different courts)
    if round_name and category in cats:
        round_overrides = cats[category].get("round_overrides", {})
        # Strip "Playoff " prefix for matching
        bare_round = round_name.replace("Playoff ", "") if round_name.startswith("Playoff ") else round_name
        if bare_round in round_overrides:
            rnd_entry = round_overrides[bare_round]
            for key in ("required_courts", "preferred_courts", "fallback_courts", "last_resort_courts"):
                if key in rnd_entry:
                    result[key] = rnd_entry[key]

    return result


def resolve_priority(config, round_name, category, div_code, day_name=None):
    """Resolve the scheduling priority for a specific match.

    Checks in order (highest precedence first):
      1. Per-day per-division override in priorities.day_overrides.<day>.divisions
      2. Per-day base override in priorities.day_overrides.<day>.rounds
      3. Per-division override in priorities.divisions
      4. Per-category override in priorities.categories
      5. Base round priority in priorities.rounds
      6. Fallback default (50)

    Supports both new hierarchical format and legacy flat format.
    """
    prio_cfg = config["scheduling"].get("priorities", {})

    # New hierarchical format: priorities.rounds / categories / divisions
    if "rounds" in prio_cfg:
        base_rounds = prio_cfg.get("rounds", {})
        cat_overrides = prio_cfg.get("categories", {})
        div_overrides = prio_cfg.get("divisions", {})
        day_overrides = prio_cfg.get("day_overrides", {})

        # Per-day overrides (highest precedence)
        if day_name and day_name in day_overrides:
            day_cfg = day_overrides[day_name]
            day_div = day_cfg.get("divisions", {})
            day_rounds = day_cfg.get("rounds", {})
            if div_code in day_div and round_name in day_div[div_code]:
                return day_div[div_code][round_name]
            if round_name in day_rounds:
                return day_rounds[round_name]

        # Division override
        if div_code in div_overrides and round_name in div_overrides[div_code]:
            return div_overrides[div_code][round_name]

        # Category override
        if category in cat_overrides and round_name in cat_overrides[category]:
            return cat_overrides[category][round_name]
        # Also try level code for category
        level_cats = config.get("divisions", {}).get("level_categories", {})
        for level, cat_name in level_cats.items():
            if cat_name == category and level in cat_overrides:
                if round_name in cat_overrides[level]:
                    return cat_overrides[level][round_name]

        # Base round priority
        if round_name in base_rounds:
            return base_rounds[round_name]

        return 50  # default fallback

    # Legacy flat format: priorities + round_priority_map + elite_divisions + division_priorities
    round_map = config["scheduling"].get("round_priority_map", {
        "Round 1": "round_1", "Round 2": "round_2",
        "Quarter-Final": "quarter_final",
        "Semi-Final": "semi_final", "Final": "final",
    })
    elite_divs = set(config["scheduling"].get("elite_divisions", []))
    div_adjustments = config["scheduling"].get("division_priorities", {})

    # Resolve round name to priority key, then to numeric value
    priority_key = round_map.get(round_name)
    if priority_key:
        priority = prio_cfg.get(priority_key, 50)
    elif round_name == "Pool":
        if div_code in elite_divs:
            priority = prio_cfg.get("elite_pool", 5)
        else:
            priority = prio_cfg.get("pool", 20)
    elif "Pool" in round_name:
        # Group pool rounds
        priority = prio_cfg.get("pool", 20)
    elif round_name.startswith("Playoff "):
        base_name = round_name.replace("Playoff ", "")
        base_key = round_map.get(base_name)
        if base_key:
            priority = max(prio_cfg.get(base_key, 50),
                          prio_cfg.get("group_playoff", 40))
        else:
            priority = prio_cfg.get("group_playoff", 40)
    else:
        priority = 50

    # Apply per-division adjustment
    priority += div_adjustments.get(div_code, 0)

    return priority


def get_time_deadlines(config):
    """Get time deadline constraints.

    Returns list of dicts: {rounds: [...], divisions: [...] or None, deadline: "Day HH:MM"}
    """
    return config["scheduling"].get("time_deadlines", [])


def get_match_density(config):
    """Get match density limit settings.

    Returns dict with:
      max_matches: int (max matches within window, 0 = unlimited)
      time_window: int (minutes)
      player_exceptions: dict of player_name -> {max_matches, time_window}
    """
    md = config["scheduling"].get("match_density", {})
    return {
        "max_matches": md.get("max_matches", 0),
        "time_window": md.get("time_window", 180),
        "player_exceptions": md.get("player_exceptions", {}),
    }


def get_potential_conflict_avoidance(config):
    """Get potential conflict avoidance settings.

    Returns dict: category -> set of round names where all possible players
    should be checked for time overlaps across divisions.
    """
    pca = config["scheduling"].get("potential_conflict_avoidance", {})
    result = {}

    # Default rounds (apply to all categories not explicitly listed)
    default_rounds = set(pca.get("default", {}).get("rounds", []))

    # Per-category overrides
    categories = pca.get("categories", {})

    # Resolve level codes to full category names
    level_cats = config.get("divisions", {}).get("level_categories", {})
    resolved_categories = {}
    for key, val in categories.items():
        rounds = set(val.get("rounds", []))
        # Check if key is a level code
        if key in level_cats:
            resolved_categories[level_cats[key]] = rounds
        else:
            resolved_categories[key] = rounds

    result["_default"] = default_rounds
    result.update(resolved_categories)
    return result


def _parse_time_limit_value(val):
    """Parse a time limit value that may be int or dict.

    Returns (limit, is_hard) or None.
    - Plain int/float: (val, False) — soft limit (WARN)
    - Dict with 'limit' key: (limit, hard) — respects 'hard' flag
    """
    if isinstance(val, (int, float)):
        return (val, False)
    if isinstance(val, dict):
        limit = val.get("limit")
        if limit is not None:
            return (limit, bool(val.get("hard", False)))
    return None


def get_round_time_limit(config, round_name, category, div_code=None):
    """Get time limit for a round in minutes.

    All matches of this round within a division/group must finish within
    this many minutes of the first match starting.

    Returns (limit_minutes, is_hard) or None.
    - is_hard=True: verifier reports as FAIL, scheduler does not relax
    - is_hard=False: verifier reports as WARN, scheduler may relax

    Plain int values in config are treated as soft limits (backward compat).
    Dict values with {limit: N, hard: true} are hard limits.

    Resolution: per-division → per-category → per-round → default.
    """
    # Strip "Playoff " for matching
    bare_round = round_name.replace("Playoff ", "") if round_name.startswith("Playoff ") else round_name

    rtl = config["scheduling"].get("round_time_limit", {})

    # Per-division override (can be a dict of round -> limit)
    if div_code:
        divs = rtl.get("divisions", {})
        if div_code in divs:
            div_cfg = divs[div_code]
            if isinstance(div_cfg, dict) and bare_round in div_cfg:
                result = _parse_time_limit_value(div_cfg[bare_round])
                if result is not None:
                    return result
            elif isinstance(div_cfg, (int, float)):
                return (div_cfg, False)

    # Per-category override (can be a dict of round -> limit)
    cats = rtl.get("categories", {})
    cat_val = _resolve_category_key(cats, category, config)
    if cat_val is not None:
        if isinstance(cat_val, dict) and bare_round in cat_val:
            result = _parse_time_limit_value(cat_val[bare_round])
            if result is not None:
                return result
        elif isinstance(cat_val, (int, float)):
            return (cat_val, False)

    # Per-round default
    rounds_cfg = rtl.get("rounds", {})
    if bare_round in rounds_cfg:
        result = _parse_time_limit_value(rounds_cfg[bare_round])
        if result is not None:
            return result

    # Global default
    default = rtl.get("default")
    if default is not None:
        result = _parse_time_limit_value(default)
        if result is not None:
            return result

    # Backwards compatibility: check pool_time_limit for pool rounds
    if "Pool" in round_name:
        ptl = config["scheduling"].get("pool_time_limit", {})
        if div_code:
            divs = ptl.get("divisions", {})
            if div_code in divs:
                return (divs[div_code], False)
        cat_val = _resolve_category_key(ptl.get("categories", {}), category, config)
        if cat_val is not None:
            return (cat_val, False)
        default = ptl.get("default")
        if default is not None:
            return (default, False)

    return None


def get_pool_round_same_day(config, category, div_code=None):
    """Check if pool round same-day grouping is enabled.

    When True, each pool round (R1, R2, R3) within a division is a
    separate same-day unit. When False, all pool matches share one key.

    Resolution: per-division → per-category → default → True.
    """
    cfg = config["scheduling"].get("pool_round_same_day", {})

    # Plain bool value (e.g., pool_round_same_day: true)
    if isinstance(cfg, bool):
        return cfg

    # Per-division override
    if div_code:
        divs = cfg.get("divisions", {})
        if div_code in divs:
            return bool(divs[div_code])

    # Per-category
    cats = cfg.get("categories", {})
    cat_val = _resolve_category_key(cats, category, config)
    if cat_val is not None:
        return bool(cat_val)

    # Default (if config key exists but no default specified, fallback to True)
    return bool(cfg.get("default", True))


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
            court_end_offset = (end_h - day_start_h) * 60 + (end_m - day_start_m)

            # Optional per-group start_time (defaults to day start)
            group_start_offset = 0
            if "start_time" in court_group:
                gs_h, gs_m = map(int, court_group["start_time"].split(":"))
                group_start_offset = (gs_h - day_start_h) * 60 + (gs_m - day_start_m)

            for court_num in court_group["numbers"]:
                all_courts.add(court_num)
                court_windows.append((
                    court_num,
                    current_minute + group_start_offset,
                    current_minute + court_end_offset,
                ))

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
    # Per-day court_buffers (in each day config) take precedence over
    # global court_buffers. Days without their own use the global config.
    court_buffer_blocks = []
    global_buffers = config["venue"].get("court_buffers", [])

    # Build day_name -> day_config lookup
    day_cfg_lookup = {dc["name"]: dc for dc in days_config}

    def _generate_buffers(buffers_list, day):
        """Generate buffer blocks for a day from a list of buffer configs."""
        blocks = []
        day_start = day["start_minute"]
        day_end = day["end_minute"]
        for buf in buffers_list:
            pool = buf.get("courts", [])
            duration = buf.get("duration", 30)
            interval = buf.get("interval", 120)
            at_once = buf.get("courts_at_once", len(pool))
            buf_slots = (duration + slot_duration - 1) // slot_duration

            # Optional end_time: stop generating buffers at or after this time
            buf_end_time = buf.get("end_time")
            if buf_end_time:
                eh, em = map(int, buf_end_time.split(":"))
                dsh, dsm = map(int, day["start_time"].split(":"))
                effective_end = day_start + (eh - dsh) * 60 + (em - dsm)
            else:
                effective_end = day_end

            day_pool = [c for c in pool
                        if any(crt == c and s <= day_start < e
                               for crt, s, e in court_windows)]
            if not day_pool:
                continue

            rotation_idx = 0
            t = day_start + interval
            while t < effective_end:
                start_idx = (rotation_idx * at_once) % len(day_pool)
                blocked_courts = []
                for i in range(at_once):
                    blocked_courts.append(day_pool[(start_idx + i) % len(day_pool)])
                for court in blocked_courts:
                    for s in range(buf_slots):
                        blocks.append((court, t + s * slot_duration))
                rotation_idx += 1
                t += interval
        return blocks

    for day in days:
        day_cfg = day_cfg_lookup.get(day["name"], {})
        day_buffers = day_cfg.get("court_buffers")
        if day_buffers is not None:
            # Per-day config (even if empty list — means no buffers for this day)
            court_buffer_blocks.extend(_generate_buffers(day_buffers, day))
        else:
            # Fall back to global config
            court_buffer_blocks.extend(_generate_buffers(global_buffers, day))

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
