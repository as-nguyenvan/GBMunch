from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from gatorgrub.domain.models import (
    AvailabilityStatus, FoodEvent, SearchPreferences, TriState, VerificationStatus,
)
from gatorgrub.verification.verifier import event_interval, is_publishable


class RankedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: FoodEvent
    score: float
    components: dict[str, float]
    explanation: str


def rank_events(events: list[FoodEvent], preferences: SearchPreferences) -> list[RankedEvent]:
    ranked: list[RankedEvent] = []
    for event in events:
        if not is_publishable(event) or event.availability is AvailabilityStatus.GONE:
            continue
        if not event.start_time:
            continue
        interval = event_interval(event)
        if interval is None:
            continue
        overlap_start = max(interval.start_time, preferences.available_start)
        overlap_end = min(interval.effective_end_time, preferences.available_end)
        useful_minutes = (overlap_end - overlap_start).total_seconds() / 60
        if useful_minutes < preferences.min_useful_minutes:
            continue
        if preferences.require_free and event.food.free_food is not TriState.YES:
            continue
        if preferences.meal_preference and event.food.meal_level is not preferences.meal_preference:
            continue

        confidence = round(event.confidence.overall * 0.25, 4)
        meal = 0.20 if not preferences.meal_preference or event.food.meal_level is preferences.meal_preference else 0.0
        dietary = 0.0
        explanations = ["Overlaps your available window", "explicitly advertises free food"]
        for preference in preferences.dietary_preferences:
            value = getattr(event.food.dietary, preference, TriState.UNKNOWN)
            label = preference.capitalize()
            if value is TriState.YES:
                dietary += 0.20
                explanations.append(f"{label} availability is explicitly confirmed")
            elif value is TriState.NO:
                dietary -= 0.20
                explanations.append(f"{label} availability is explicitly ruled out")
            else:
                dietary -= 0.10
                explanations.append(f"{label} suitability is unknown")
        source_time = max((source.posted_at or source.retrieved_at for source in event.sources), default=preferences.available_start)
        age_hours = max(0.0, (preferences.available_start - source_time).total_seconds() / 3600)
        freshness = round(max(0.0, 0.10 - min(age_hours, 72) / 720), 4)
        status = {
            VerificationStatus.TRUSTED: 0.15,
            VerificationStatus.LIKELY: 0.10,
            VerificationStatus.REVIEW_NEEDED: 0.02,
        }.get(event.verification_status, 0.0)
        proximity = 0.05 if preferences.origin and preferences.max_walk_minutes is not None else 0.0
        if proximity:
            explanations.append(f"{preferences.max_walk_minutes}-minute proximity is a placeholder, not a measured walk")
        components = {"confidence": confidence, "dietary": round(dietary, 4), "meal": meal,
                      "freshness": freshness, "status": status, "proximity": proximity}
        score = round(sum(components.values()), 4)
        ranked.append(RankedEvent(event=event, score=score, components=components,
                                  explanation=". ".join(explanations) + "."))
    return sorted(ranked, key=lambda item: (-item.score, item.event.start_time, item.event.event_id))
