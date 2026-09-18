from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from gatorgrub.domain.models import (
    DietaryInfo, EvidenceLevel, EventLocation, EventSource, FoodEvent, FoodInfo,
    MealLevel, RawEventCandidate, SearchPreferences, SourceType, TriState,
)


def test_raw_candidate_requires_aware_retrieved_at():
    with pytest.raises(ValidationError):
        RawEventCandidate(source_type=SourceType.PASTED_TEXT, raw_text="food", retrieved_at=datetime(2026, 9, 17, 12))


def test_explicit_offsets_are_preserved_and_naive_event_times_use_uf_timezone():
    source = EventSource(type=SourceType.PASTED_TEXT, raw_text="free pizza", retrieved_at=datetime.now(timezone.utc))
    aware = FoodEvent(event_id="aware", event_name="Lunch", start_time=datetime.fromisoformat("2026-09-18T18:00:00-07:00"), sources=[source])
    naive = FoodEvent(event_id="naive", event_name="Lunch", start_time=datetime(2026, 9, 18, 18), sources=[source])
    assert aware.start_time.utcoffset().total_seconds() == -7 * 3600
    assert naive.start_time.tzinfo.key == "America/New_York"


def test_unknown_facts_are_explicit_and_provenance_is_multiple():
    source = EventSource(type=SourceType.JSON_FIXTURE, raw_text="pizza", retrieved_at=datetime.now(timezone.utc))
    event = FoodEvent(event_id="e1", event_name="GBM", sources=[source, source])
    assert event.food.free_food is TriState.UNKNOWN
    assert event.food.free_food_evidence is EvidenceLevel.UNKNOWN
    assert event.food.dietary.vegetarian is TriState.UNKNOWN
    assert event.attendance.open_to_all is TriState.UNKNOWN
    assert len(event.sources) == 2


def test_confidence_rejects_values_outside_unit_interval():
    with pytest.raises(ValidationError):
        FoodEvent(event_id="bad", event_name="Bad", confidence={"overall": 1.2})


def test_search_preferences_reject_unsupported_dietary_names():
    with pytest.raises(ValidationError):
        SearchPreferences(
            available_start=datetime(2026, 9, 18, 17, 10),
            available_end=datetime(2026, 9, 18, 18, 45),
            dietary_preferences=["gluten_free"],
        )


def test_search_preferences_normalize_naive_local_times():
    prefs = SearchPreferences(
        available_start=datetime(2026, 9, 18, 17, 10),
        available_end=datetime(2026, 9, 18, 18, 45),
        dietary_preferences=["vegetarian"], meal_preference=MealLevel.MEAL,
    )
    assert prefs.available_start.tzinfo.key == "America/New_York"
