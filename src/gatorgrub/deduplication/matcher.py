from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from gatorgrub.domain.models import EvidenceLevel, EventStatus, FoodEvent, TriState


@dataclass(frozen=True)
class MatchDecision:
    is_duplicate: bool
    score: float
    reasons: tuple[str, ...]


class EventDeduplicator:
    def __init__(self, time_tolerance_minutes: int = 15, threshold: float = 0.8):
        self.time_tolerance_minutes = time_tolerance_minutes
        self.threshold = threshold

    @staticmethod
    def _similar(left: str | None, right: str | None, cutoff: float = 0.65) -> bool:
        if not left or not right:
            return False
        return SequenceMatcher(None, left.casefold(), right.casefold()).ratio() >= cutoff

    def compare(self, left: FoodEvent, right: FoodEvent) -> MatchDecision:
        score = 0.0
        reasons: list[str] = []
        organization_match = self._similar(left.organization, right.organization)
        if organization_match:
            score += 0.25
            reasons.append("similar organization")
        title_match = self._similar(left.event_name, right.event_name)
        if title_match:
            score += 0.20
            reasons.append("similar title")
        same_date = False
        time_compatible = True
        if left.start_time and right.start_time:
            same_date = left.start_time.date() == right.start_time.date()
            if same_date:
                score += 0.20
                reasons.append("same date")
            delta = abs((left.start_time - right.start_time).total_seconds()) / 60
            time_compatible = delta <= self.time_tolerance_minutes
            if time_compatible:
                score += 0.15
                reasons.append(f"time within {self.time_tolerance_minutes} minutes")
        left_location = left.location.raw_text or left.location.building
        right_location = right.location.raw_text or right.location.building
        location_match = self._similar(left_location, right_location, cutoff=0.5)
        if location_match:
            score += 0.20
            reasons.append("similar location")
        score = round(score, 3)
        organization_missing = not left.organization or not right.organization
        generic_titles = {"general body meeting", "gbm", "campus event", "untitled event"}
        food_match = self._similar(left.food.description, right.food.description, cutoff=0.8)
        non_generic_title = (
            title_match
            and left.event_name.casefold() not in generic_titles
            and right.event_name.casefold() not in generic_titles
        )
        source_match = any(
            (left_source.external_id and left_source.external_id == right_source.external_id)
            or (left_source.url and left_source.url == right_source.url)
            for left_source in left.sources
            for right_source in right.sources
        )
        rooms_conflict = bool(
            left.location.room
            and right.location.room
            and left.location.room.casefold() != right.location.room.casefold()
        )
        buildings_conflict = bool(
            left.location.building
            and right.location.building
            and not self._similar(left.location.building, right.location.building, cutoff=0.5)
        )
        if (rooms_conflict or buildings_conflict) and not source_match:
            reasons.append("contradictory explicit location")
            return MatchDecision(False, score, tuple(reasons))
        distinguishing_signal = food_match or non_generic_title or source_match
        strong_core_match = (
            organization_missing
            and title_match
            and same_date
            and time_compatible
            and location_match
            and distinguishing_signal
        )
        automatic = score >= self.threshold and time_compatible
        return MatchDecision((automatic or strong_core_match) and time_compatible,
                             score, tuple(reasons))

    def merge(self, left: FoodEvent, right: FoodEvent) -> FoodEvent:
        decision = self.compare(left, right)
        if not decision.is_duplicate:
            raise ValueError("events do not satisfy duplicate threshold")

        def latest_source(event: FoodEvent) -> str:
            return max(
                ((source.posted_at or source.retrieved_at).isoformat() for source in event.sources),
                default="",
            )

        def event_key(event: FoodEvent) -> tuple[float, str, str]:
            return (event.confidence.overall, latest_source(event), event.event_id)

        preferred = max((left, right), key=event_key)
        merged = preferred.model_copy(deep=True)
        merged.event_id = min(left.event_id, right.event_id)

        unique_sources = {}
        for source in [*left.sources, *right.sources]:
            identity = (source.type, source.url, source.external_id, source.raw_text)
            source_key = (
                (source.posted_at or source.retrieved_at).isoformat(),
                source.retrieved_at.isoformat(),
                source.posted_at.isoformat() if source.posted_at else "",
            )
            existing = unique_sources.get(identity)
            if existing is None:
                unique_sources[identity] = source
            else:
                existing_key = (
                    (existing.posted_at or existing.retrieved_at).isoformat(),
                    existing.retrieved_at.isoformat(),
                    existing.posted_at.isoformat() if existing.posted_at else "",
                )
                if source_key > existing_key:
                    unique_sources[identity] = source
        merged.sources = sorted(
            (source.model_copy(deep=True) for source in unique_sources.values()),
            key=lambda source: (
                source.retrieved_at.isoformat(), source.type.value, source.url or "",
                source.external_id or "", source.raw_text,
            ),
        )

        merged.confidence = max((left, right), key=event_key).confidence.model_copy(deep=True)
        if len(merged.sources) > 1:
            merged.confidence.overall = min(1.0, merged.confidence.overall + 0.05)
            if "corroborated by multiple sources" not in merged.confidence.reasons:
                merged.confidence.reasons.append("corroborated by multiple sources")

        conflicts = set(left.conflicts + right.conflicts)

        if left.start_time and right.start_time and left.start_time != right.start_time:
            conflicts.add("conflicting start times")
            merged.start_time = max(
                (left, right),
                key=lambda event: (
                    event.confidence.time, latest_source(event),
                    event.start_time.isoformat() if event.start_time else "", event.event_id,
                ),
            ).start_time
        elif not merged.start_time:
            merged.start_time = left.start_time or right.start_time

        if left.end_time and right.end_time and left.end_time != right.end_time:
            conflicts.add("conflicting end times")
            merged.end_time = max(
                (left, right),
                key=lambda event: (
                    event.confidence.time, latest_source(event),
                    event.end_time.isoformat() if event.end_time else "", event.event_id,
                ),
            ).end_time
        elif not merged.end_time:
            merged.end_time = left.end_time or right.end_time

        if merged.start_time and merged.end_time and merged.end_time < merged.start_time:
            merged.end_time = None
            conflicts.add("conflicting event intervals")

        evidence_rank = {
            EvidenceLevel.UNKNOWN: 0,
            EvidenceLevel.INFERRED: 1,
            EvidenceLevel.EXPLICIT: 2,
        }
        if (
            left.food.description
            and right.food.description
            and left.food.description.casefold() != right.food.description.casefold()
        ):
            if (
                left.food.description_evidence is EvidenceLevel.EXPLICIT
                and right.food.description_evidence is EvidenceLevel.EXPLICIT
            ):
                conflicts.add("conflicting food descriptions")
            food_event = max(
                (left, right),
                key=lambda event: (
                    evidence_rank[event.food.description_evidence], event.confidence.food,
                    latest_source(event), event.food.description or "", event.event_id,
                ),
            )
            merged.food.description = food_event.food.description
            merged.food.description_evidence = food_event.food.description_evidence
            merged.food.meal_level = food_event.food.meal_level
        elif not merged.food.description:
            food_event = left if left.food.description else right
            merged.food.description = food_event.food.description
            merged.food.description_evidence = food_event.food.description_evidence
            merged.food.meal_level = food_event.food.meal_level

        if (
            left.food.free_food_evidence is EvidenceLevel.EXPLICIT
            and right.food.free_food_evidence is EvidenceLevel.EXPLICIT
            and {left.food.free_food, right.food.free_food} == {TriState.YES, TriState.NO}
        ):
            merged.food.free_food = TriState.UNKNOWN
            merged.food.free_food_evidence = EvidenceLevel.UNKNOWN
            conflicts.add("conflicting free-food claims")
        else:
            free_event = max(
                (left, right),
                key=lambda event: (
                    evidence_rank[event.food.free_food_evidence], event.confidence.food,
                    latest_source(event), event.food.free_food.value, event.event_id,
                ),
            )
            merged.food.free_food = free_event.food.free_food
            merged.food.free_food_evidence = free_event.food.free_food_evidence

        if merged.organization is None:
            merged.organization = left.organization or right.organization
        if not merged.location.raw_text:
            located = left if left.location.raw_text else right
            merged.location = located.location.model_copy(deep=True)

        for field in ("vegetarian", "vegan", "halal", "kosher"):
            left_value = getattr(left.food.dietary, field)
            right_value = getattr(right.food.dietary, field)
            if left_value is TriState.UNKNOWN:
                value = right_value
            elif right_value is TriState.UNKNOWN or left_value is right_value:
                value = left_value
            else:
                value = TriState.UNKNOWN
                conflicts.add(f"conflicting {field} claims")
            setattr(merged.food.dietary, field, value)

        left_attendance = left.attendance.open_to_all
        right_attendance = right.attendance.open_to_all
        if left_attendance is TriState.UNKNOWN and right_attendance is not TriState.UNKNOWN:
            merged.attendance = right.attendance.model_copy(deep=True)
        elif right_attendance is TriState.UNKNOWN and left_attendance is not TriState.UNKNOWN:
            merged.attendance = left.attendance.model_copy(deep=True)
        elif (
            left_attendance is not TriState.UNKNOWN
            and right_attendance is not TriState.UNKNOWN
            and left_attendance is not right_attendance
        ):
            merged.attendance.open_to_all = TriState.UNKNOWN
            merged.attendance.evidence = EvidenceLevel.UNKNOWN
            merged.attendance.requirements = None
            conflicts.add("conflicting attendance claims")

        left_status = EventStatus.SCHEDULED if left.status is EventStatus.EXPIRED else left.status
        right_status = EventStatus.SCHEDULED if right.status is EventStatus.EXPIRED else right.status
        if left_status is right_status:
            merged.status = left_status
            merged.status_evidence = max(
                (left.status_evidence, right.status_evidence),
                key=lambda evidence: evidence_rank[evidence],
            )
        elif EvidenceLevel.EXPLICIT in {left.status_evidence, right.status_evidence}:
            explicit_events = [
                event for event in (left, right)
                if event.status_evidence is EvidenceLevel.EXPLICIT
            ]
            if len(explicit_events) == 1:
                status_event = explicit_events[0]
                merged.status = (
                    EventStatus.SCHEDULED
                    if status_event.status is EventStatus.EXPIRED
                    else status_event.status
                )
                merged.status_evidence = EvidenceLevel.EXPLICIT
            else:
                left_observed = latest_source(left)
                right_observed = latest_source(right)
                if left_observed != right_observed:
                    status_event = max((left, right), key=lambda event: (latest_source(event), event.event_id))
                    merged.status = status_event.status
                    merged.status_evidence = EvidenceLevel.EXPLICIT
                else:
                    merged.status = EventStatus.SCHEDULED
                    merged.status_evidence = EvidenceLevel.UNKNOWN
                    conflicts.add("conflicting event status")
        else:
            merged.status = EventStatus.SCHEDULED
            merged.status_evidence = EvidenceLevel.UNKNOWN
            conflicts.add("conflicting event status")

        merged.conflicts = sorted(conflicts)
        return merged

    def collapse(self, events: list[FoodEvent]) -> list[FoodEvent]:
        canonical: list[FoodEvent] = []
        for event in events:
            for index, existing in enumerate(canonical):
                if self.compare(existing, event).is_duplicate:
                    canonical[index] = self.merge(existing, event)
                    break
            else:
                canonical.append(event)
        return canonical
