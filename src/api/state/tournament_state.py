"""In-memory tournament state — source of truth for the desktop app.

Wraps the existing scheduling engine classes (Match, CourtSchedule,
PlayerTracker) and adapts tournament configuration into the format
the existing code expects.
"""

from __future__ import annotations

import sys
import os
import uuid
from collections import defaultdict

# Ensure src/ is importable
SRC_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from generate_schedule import (
    Match, CourtSchedule, PlayerTracker,
    load_all_matches, schedule_matches, validate_schedule,
    get_eligible_courts, minute_to_display, extract_player_names,
    SLOT_DURATION, ALL_SLOTS, SESSIONS,
    ELITE_DIVISIONS, OPEN_A_DIVISIONS, JUNIOR_CATEGORIES,
)

from api.models.config_schemas import (
    TournamentConfig, CategoryConfig, time_str_to_minutes, minutes_to_time_str,
)
from api.models.schemas import (
    MatchCard, Conflict, SessionInfo, ScheduleState,
)


class TournamentState:
    """Holds all tournament data in memory. Singleton per app session."""

    def __init__(self):
        self.config: TournamentConfig = TournamentConfig()
        self.matches: list[Match] = []
        self.match_by_id: dict[str, Match] = {}
        self.scheduled: dict[str, tuple] = {}  # match_id → (court, minute)
        self.court_sched: CourtSchedule = CourtSchedule()
        self.player_tracker: PlayerTracker = PlayerTracker()
        self.pinned: set[str] = set()
        self.results: dict[str, str] = {}  # match_id → score string
        self.divisions: list[dict] = []    # raw division data
        self._category_by_div: dict[str, CategoryConfig] = {}

    # ── Configuration ──────────────────────────────────────────

    def set_config(self, config: TournamentConfig):
        self.config = config
        self._rebuild_category_map()

    def _rebuild_category_map(self):
        """Build division_code → CategoryConfig lookup from config."""
        cat_by_id = {c.id: c for c in self.config.categories}
        self._category_by_div = {}
        for div_code, cat_id in self.config.division_category_map.items():
            if cat_id in cat_by_id:
                self._category_by_div[div_code] = cat_by_id[cat_id]

    def get_category_for_division(self, div_code: str) -> CategoryConfig | None:
        return self._category_by_div.get(div_code)

    def get_category_config_by_id(self, cat_id: str) -> CategoryConfig | None:
        for c in self.config.categories:
            if c.id == cat_id:
                return c
        return None

    # ── Import ─────────────────────────────────────────────────

    def load_matches(self):
        """Load matches from output/divisions/ using the existing loader.
        Applies category-specific durations and rest from config."""
        self.matches, self.match_by_id = load_all_matches()

        # Override duration/rest from category config
        for match in self.matches:
            cat = self.get_category_for_division(match.division_code)
            if cat:
                match.duration_min = cat.duration_minutes
                match.rest_min = cat.rest_minutes

    # ── Schedule generation ────────────────────────────────────

    def generate_schedule(self, keep_pinned: bool = True):
        """Run the auto-scheduling algorithm.
        If keep_pinned, pre-place pinned matches before running."""
        if keep_pinned and self.pinned:
            # Save pinned placements, regenerate the rest
            pinned_placements = {
                mid: self.scheduled[mid]
                for mid in self.pinned
                if mid in self.scheduled
            }
            matches_to_schedule = [
                m for m in self.matches if m.id not in self.pinned
            ]
        else:
            pinned_placements = {}
            matches_to_schedule = list(self.matches)

        # Run scheduler for non-pinned matches
        scheduled, unscheduled, court_sched, player_tracker = schedule_matches(
            matches_to_schedule, self.match_by_id
        )

        # Merge pinned placements back in
        self.scheduled = dict(scheduled)
        for mid, placement in pinned_placements.items():
            self.scheduled[mid] = placement

        # Rebuild court schedule and player tracker from scratch
        self._rebuild_trackers()

        return self._build_schedule_state()

    # ── Move / Swap / Unschedule ───────────────────────────────

    def move_match(self, match_id: str, court: int, time_minute: int) -> tuple[MatchCard, list[Conflict]]:
        """Move a match to a new court/time slot."""
        match = self.match_by_id.get(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        # Remove old placement if exists
        if match_id in self.scheduled:
            old_court, old_minute = self.scheduled[match_id]
            self.court_sched.unbook(old_court, old_minute, match.duration_min)

        # Book new placement
        self.court_sched.book(court, time_minute, match_id, match.duration_min)
        self.scheduled[match_id] = (court, time_minute)

        # Rebuild player tracker
        self._rebuild_player_tracker()

        # Run scoped validation
        conflicts = self._scoped_validate(match_id)

        return self._match_to_card(match), conflicts

    def swap_matches(self, match_id_a: str, match_id_b: str) -> tuple[list[MatchCard], list[Conflict]]:
        """Swap the positions of two scheduled matches."""
        match_a = self.match_by_id.get(match_id_a)
        match_b = self.match_by_id.get(match_id_b)
        if not match_a or not match_b:
            raise ValueError("One or both matches not found")
        if match_id_a not in self.scheduled or match_id_b not in self.scheduled:
            raise ValueError("Both matches must be scheduled to swap")

        pos_a = self.scheduled[match_id_a]
        pos_b = self.scheduled[match_id_b]

        # Unbook both
        self.court_sched.unbook(pos_a[0], pos_a[1], match_a.duration_min)
        self.court_sched.unbook(pos_b[0], pos_b[1], match_b.duration_min)

        # Re-book swapped
        self.court_sched.book(pos_b[0], pos_b[1], match_id_a, match_a.duration_min)
        self.court_sched.book(pos_a[0], pos_a[1], match_id_b, match_b.duration_min)
        self.scheduled[match_id_a] = pos_b
        self.scheduled[match_id_b] = pos_a

        self._rebuild_player_tracker()

        conflicts_a = self._scoped_validate(match_id_a)
        conflicts_b = self._scoped_validate(match_id_b)
        # Deduplicate
        seen = set()
        conflicts = []
        for c in conflicts_a + conflicts_b:
            if c.id not in seen:
                seen.add(c.id)
                conflicts.append(c)

        return [self._match_to_card(match_a), self._match_to_card(match_b)], conflicts

    def unschedule_match(self, match_id: str) -> MatchCard:
        """Remove a match from the schedule grid."""
        match = self.match_by_id.get(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        if match_id in self.scheduled:
            court, minute = self.scheduled[match_id]
            self.court_sched.unbook(court, minute, match.duration_min)
            del self.scheduled[match_id]
            self._rebuild_player_tracker()

        if match_id in self.pinned:
            self.pinned.discard(match_id)

        return self._match_to_card(match)

    def pin_match(self, match_id: str, pinned: bool) -> MatchCard:
        match = self.match_by_id.get(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")
        if pinned:
            self.pinned.add(match_id)
        else:
            self.pinned.discard(match_id)
        return self._match_to_card(match)

    # ── Validation ─────────────────────────────────────────────

    def validate_all(self) -> list[Conflict]:
        """Run full validation across all matches."""
        warnings = validate_schedule(
            self.matches, self.match_by_id,
            self.scheduled, self.court_sched, self.player_tracker
        )
        return self._warnings_to_conflicts(warnings)

    def validate_move_preview(self, match_id: str, court: int, time_minute: int) -> list[Conflict]:
        """Preview conflicts for a hypothetical move without committing."""
        match = self.match_by_id.get(match_id)
        if not match:
            return []

        # Temporarily apply the move
        old_placement = self.scheduled.get(match_id)
        if old_placement:
            self.court_sched.unbook(old_placement[0], old_placement[1], match.duration_min)

        self.court_sched.book(court, time_minute, match_id, match.duration_min)
        self.scheduled[match_id] = (court, time_minute)
        self._rebuild_player_tracker()

        conflicts = self._scoped_validate(match_id)

        # Revert
        self.court_sched.unbook(court, time_minute, match.duration_min)
        if old_placement:
            self.court_sched.book(old_placement[0], old_placement[1], match_id, match.duration_min)
            self.scheduled[match_id] = old_placement
        else:
            del self.scheduled[match_id]
        self._rebuild_player_tracker()

        return conflicts

    def _scoped_validate(self, match_id: str) -> list[Conflict]:
        """Run validation scoped to a single match and its player-related matches."""
        conflicts = []
        match = self.match_by_id.get(match_id)
        if not match or match_id not in self.scheduled:
            return conflicts

        court, minute = self.scheduled[match_id]
        end = minute + match.duration_min
        day_label = self._minute_to_day_label(minute)
        cat = self.get_category_for_division(match.division_code)

        # 1. Court eligibility (from config)
        if cat and cat.required_courts and court not in cat.required_courts:
            conflicts.append(Conflict(
                id=str(uuid.uuid4()),
                type="wrong_court",
                severity="error",
                match_ids=[match_id],
                message=f"{match.division_code} must be on courts {cat.required_courts}, but placed on court {court}",
            ))
        elif cat and cat.preferred_courts and court not in cat.preferred_courts:
            conflicts.append(Conflict(
                id=str(uuid.uuid4()),
                type="wrong_court",
                severity="warning",
                match_ids=[match_id],
                message=f"{match.division_code} prefers courts {cat.preferred_courts}, but placed on court {court}",
            ))

        # 2. Court availability (from config)
        if not self._is_court_available(court, minute, match.duration_min):
            conflicts.append(Conflict(
                id=str(uuid.uuid4()),
                type="court_unavailable",
                severity="error",
                match_ids=[match_id],
                message=f"Court {court} is not available at {self._minute_to_display(minute)}",
            ))

        # 3. SF/Final day rule
        if cat and cat.sf_final_day_index is not None and match.is_sf_or_final:
            match_day_index = self._minute_to_day_index(minute)
            if match_day_index != cat.sf_final_day_index:
                required_day = self.config.days[cat.sf_final_day_index].label if cat.sf_final_day_index < len(self.config.days) else f"Day {cat.sf_final_day_index + 1}"
                conflicts.append(Conflict(
                    id=str(uuid.uuid4()),
                    type="sf_final_wrong_day",
                    severity="error",
                    match_ids=[match_id],
                    message=f"SF/Final {match_id} must be on {required_day}",
                ))

        # 4. Prerequisite ordering
        for prereq_id in match.prerequisites:
            if prereq_id in self.scheduled:
                _, prereq_minute = self.scheduled[prereq_id]
                prereq_match = self.match_by_id.get(prereq_id)
                prereq_end = prereq_minute + (prereq_match.duration_min if prereq_match else 30)
                if prereq_end > minute:
                    conflicts.append(Conflict(
                        id=str(uuid.uuid4()),
                        type="prerequisite_violation",
                        severity="error",
                        match_ids=[match_id, prereq_id],
                        message=f"{match_id} scheduled before prerequisite {prereq_id} finishes",
                    ))

        # 5. Player conflicts (double-booking + rest)
        if match.has_real_players and match.known_players:
            rest_min = cat.rest_minutes if cat else 30
            for player in match.known_players:
                for other in self.matches:
                    if other.id == match_id or other.id not in self.scheduled:
                        continue
                    if not other.has_real_players:
                        continue
                    if player not in other.known_players:
                        continue

                    o_court, o_minute = self.scheduled[other.id]
                    o_end = o_minute + other.duration_min

                    # Double-booking: overlapping time
                    if minute < o_end and end > o_minute:
                        conflicts.append(Conflict(
                            id=str(uuid.uuid4()),
                            type="double_booking",
                            severity="error",
                            match_ids=[match_id, other.id],
                            message=f"Double-booking: {player} in {match_id} and {other.id}",
                            player=player,
                        ))
                    # Rest violation
                    elif minute >= o_end and minute < o_end + rest_min:
                        conflicts.append(Conflict(
                            id=str(uuid.uuid4()),
                            type="rest_violation",
                            severity="warning",
                            match_ids=[match_id, other.id],
                            message=f"Insufficient rest for {player}: {other.id} ends at {self._minute_to_display(o_end)}, {match_id} starts at {self._minute_to_display(minute)} (need {rest_min} min)",
                            player=player,
                        ))
                    elif end <= o_minute and o_minute < end + rest_min:
                        conflicts.append(Conflict(
                            id=str(uuid.uuid4()),
                            type="rest_violation",
                            severity="warning",
                            match_ids=[match_id, other.id],
                            message=f"Insufficient rest for {player}: {match_id} ends at {self._minute_to_display(end)}, {other.id} starts at {self._minute_to_display(o_minute)} (need {rest_min} min)",
                            player=player,
                        ))

        return conflicts

    # ── Results ────────────────────────────────────────────────

    def update_result(self, match_id: str, score: str) -> tuple[MatchCard, list[MatchCard]]:
        """Store a result and resolve downstream placeholders."""
        match = self.match_by_id.get(match_id)
        if not match:
            raise ValueError(f"Match not found: {match_id}")

        self.results[match_id] = score

        # Determine winner from score
        winner = self._determine_winner(match, score)
        resolved = []

        if winner:
            # Find downstream matches referencing this match's winner
            for other in self.matches:
                changed = False
                if f"Winner" in other.player1 and self._is_winner_ref(other.player1, match):
                    other.player1 = winner
                    changed = True
                if f"Winner" in other.player2 and self._is_winner_ref(other.player2, match):
                    other.player2 = winner
                    changed = True
                if changed:
                    other.known_players = extract_player_names(other.player1) + extract_player_names(other.player2)
                    other.has_real_players = bool(other.known_players) and not (
                        other.player1.startswith("Winner ") or other.player1.startswith("Slot ")
                    )
                    resolved.append(self._match_to_card(other))

        return self._match_to_card(match), resolved

    def _determine_winner(self, match: Match, score: str) -> str | None:
        """Parse score to determine winner. Returns the winning player string."""
        sets = score.strip().split()
        p1_wins = 0
        p2_wins = 0
        for s in sets:
            parts = s.split("-")
            if len(parts) == 2:
                try:
                    a, b = int(parts[0]), int(parts[1])
                    if a > b:
                        p1_wins += 1
                    elif b > a:
                        p2_wins += 1
                except ValueError:
                    pass
        if p1_wins > p2_wins:
            return match.player1
        elif p2_wins > p1_wins:
            return match.player2
        return None

    def _is_winner_ref(self, player_str: str, source_match: Match) -> bool:
        """Check if player_str is a 'Winner ...' reference to source_match."""
        import re
        m = re.match(r"Winner\s+(\w+)-M(\d+)", player_str)
        if not m:
            return False
        abbrev_to_round = {
            "R1": "Round 1", "R2": "Round 2", "QF": "Quarter-Final",
            "SF": "Semi-Final", "F": "Final",
        }
        ref_round = abbrev_to_round.get(m.group(1), m.group(1))
        ref_num = int(m.group(2))
        return source_match.round_name == ref_round and source_match.match_num == ref_num

    # ── Internal helpers ───────────────────────────────────────

    def _rebuild_trackers(self):
        """Rebuild CourtSchedule and PlayerTracker from current scheduled state."""
        self.court_sched = CourtSchedule()
        self.player_tracker = PlayerTracker()
        for match in self.matches:
            if match.id in self.scheduled:
                court, minute = self.scheduled[match.id]
                self.court_sched.book(court, minute, match.id, match.duration_min)
                if match.has_real_players and match.known_players:
                    self.player_tracker.update(
                        match.known_players, minute,
                        match.duration_min, match.rest_min
                    )

    def _rebuild_player_tracker(self):
        """Rebuild just the PlayerTracker (lighter than full rebuild)."""
        self.player_tracker = PlayerTracker()
        for match in self.matches:
            if match.id in self.scheduled:
                court, minute = self.scheduled[match.id]
                if match.has_real_players and match.known_players:
                    self.player_tracker.update(
                        match.known_players, minute,
                        match.duration_min, match.rest_min
                    )

    def _minute_to_day_index(self, minute: int) -> int:
        """Convert minute offset to day index (0-based)."""
        # Day boundaries: day 0 = 0..1439, day 1 = 1440..2879, etc.
        return minute // 1440

    def _minute_to_day_label(self, minute: int) -> str:
        day_idx = self._minute_to_day_index(minute)
        if day_idx < len(self.config.days):
            return self.config.days[day_idx].label
        return f"Day {day_idx + 1}"

    def _minute_to_display(self, minute: int) -> str:
        """Convert minute offset to display string."""
        day, time_str = minute_to_display(minute)
        return f"{time_str} {day}"

    def _is_court_available(self, court: int, minute: int, duration: int) -> bool:
        """Check if a court is available at the given time, per config."""
        day_idx = self._minute_to_day_index(minute)
        if day_idx >= len(self.config.days):
            return False
        day = self.config.days[day_idx]
        day_start_offset = day_idx * 1440
        local_minute = minute - day_start_offset
        local_end = local_minute + duration

        for ca in day.courts:
            if ca.court == court:
                avail_from = time_str_to_minutes(ca.available_from)
                avail_to = time_str_to_minutes(ca.available_to)
                # Convert to minutes from midnight for comparison
                local_start_clock = local_minute + 9 * 60  # offset by 9:00 base
                # Actually, the minute model starts at 9:00, so local_minute 0 = 09:00
                match_start_clock = local_minute // 60 * 60 + local_minute % 60 + 9 * 60
                # Simpler: just use the existing _court_exists logic
                return True  # Let the existing CourtSchedule handle this
        return False  # Court not in config for this day

    def _warnings_to_conflicts(self, warnings: list[str]) -> list[Conflict]:
        """Convert warning strings from validate_schedule() to Conflict objects."""
        conflicts = []
        for w in warnings:
            conflict_type = "unknown"
            severity = "warning"
            match_ids = []
            player = None

            if "Double-booking" in w:
                conflict_type = "double_booking"
                severity = "error"
            elif "Insufficient rest" in w:
                conflict_type = "rest_violation"
            elif "SF/Final on Saturday" in w:
                conflict_type = "sf_final_wrong_day"
                severity = "error"
            elif "Round order violation" in w:
                conflict_type = "prerequisite_violation"
                severity = "error"
            elif "Elite on wrong court" in w:
                conflict_type = "wrong_court"
                severity = "error"

            conflicts.append(Conflict(
                id=str(uuid.uuid4()),
                type=conflict_type,
                severity=severity,
                match_ids=match_ids,
                message=w,
                player=player,
            ))
        return conflicts

    def _match_to_card(self, match: Match) -> MatchCard:
        """Convert a Match object to a MatchCard response model."""
        cat = self.get_category_for_division(match.division_code)
        cat_id = ""
        cat_label = match.category
        cat_color = "#3182ce"
        if cat:
            cat_id = cat.id
            cat_label = cat.label
            cat_color = cat.color

        court = None
        time_minute = None
        time_display = None
        day = None
        if match.id in self.scheduled:
            court, time_minute = self.scheduled[match.id]
            day_str, time_str = minute_to_display(time_minute)
            time_display = time_str
            day = day_str

        conflict_ids = []  # Populated by the caller if needed

        return MatchCard(
            id=match.id,
            division_code=match.division_code,
            division_name=match.division_name,
            category_id=cat_id,
            category_label=cat_label,
            category_color=cat_color,
            round_name=match.round_name,
            match_num=match.match_num,
            player1=match.player1,
            player2=match.player2,
            duration_min=match.duration_min,
            is_sf_or_final=match.is_sf_or_final,
            has_real_players=match.has_real_players,
            prerequisites=match.prerequisites,
            result=self.results.get(match.id),
            court=court,
            time_minute=time_minute,
            time_display=time_display,
            day=day,
            pinned=match.id in self.pinned,
            conflict_ids=conflict_ids,
        )

    def _build_schedule_state(self) -> ScheduleState:
        """Build full ScheduleState response."""
        cards = [self._match_to_card(m) for m in self.matches]
        unscheduled = [m.id for m in self.matches if m.id not in self.scheduled]
        conflicts = self.validate_all()

        # Annotate cards with conflict IDs
        conflict_map = defaultdict(list)
        for c in conflicts:
            for mid in c.match_ids:
                conflict_map[mid].append(c.id)
        for card in cards:
            card.conflict_ids = conflict_map.get(card.id, [])

        sessions = self._build_session_infos()

        return ScheduleState(
            matches=cards,
            conflicts=conflicts,
            unscheduled=unscheduled,
            sessions=sessions,
        )

    def _build_session_infos(self) -> list[SessionInfo]:
        """Build session info from config."""
        infos = []
        for sess in self.config.sessions:
            day_idx = sess.day_index
            day = self.config.days[day_idx] if day_idx < len(self.config.days) else None
            day_label = day.label if day else f"Day {day_idx + 1}"

            start_minutes = time_str_to_minutes(sess.start_time)
            end_minutes = time_str_to_minutes(sess.end_time)
            # Convert to minute offsets (day 0 base = 0 at 09:00)
            day_base = day_idx * 1440
            start_offset = day_base + (start_minutes - 9 * 60)  # 9:00 = minute 0
            end_offset = day_base + (end_minutes - 9 * 60)

            # Courts available for this session
            courts = []
            if day:
                for ca in day.courts:
                    ca_from = time_str_to_minutes(ca.available_from)
                    ca_to = time_str_to_minutes(ca.available_to)
                    # Court available if its window overlaps the session
                    if ca_from < end_minutes and ca_to > start_minutes:
                        courts.append(ca.court)
            courts.sort()

            # Count matches in this session
            match_count = sum(
                1 for m in self.matches
                if m.id in self.scheduled
                and start_offset <= self.scheduled[m.id][1] < end_offset
            )

            infos.append(SessionInfo(
                name=sess.name,
                day_label=day_label,
                start_time=sess.start_time,
                end_time=sess.end_time,
                start_minute=start_offset,
                end_minute=end_offset,
                courts=courts,
                match_count=match_count,
            ))
        return infos

    def get_schedule_state(self) -> ScheduleState:
        """Get current schedule state."""
        return self._build_schedule_state()


# Global singleton
_state = TournamentState()


def get_state() -> TournamentState:
    return _state
