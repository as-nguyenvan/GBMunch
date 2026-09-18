from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.deduplication.matcher import EventDeduplicator
from gatorgrub.domain.models import EvidenceLevel, EventLocation, EventStatus, TriState
from gatorgrub.extraction.extractor import DeterministicExtractor
from gatorgrub.ingestion.adapters import JsonFixtureAdapter

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "announcements.json"


def events():
    rows = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=NOW)
    parser = DeterministicExtractor(reference_time=NOW)
    return {r.metadata["case"]: parser.extract(r) for r in rows}


def test_duplicate_match_is_explainable_and_merges_all_sources():
    data = events()
    matcher = EventDeduplicator(time_tolerance_minutes=15)
    decision = matcher.compare(data["duplicate_a"], data["duplicate_b"])
    assert decision.is_duplicate
    assert "same date" in decision.reasons
    assert "time within 15 minutes" in decision.reasons
    merged = matcher.merge(data["duplicate_a"], data["duplicate_b"])
    assert len(merged.sources) == 2
    assert merged.event_id == min(data["duplicate_a"].event_id, data["duplicate_b"].event_id)


def test_cancellation_update_takes_precedence_when_duplicates_merge():
    data = events()
    cancellation = data["duplicate_b"].model_copy(deep=True)
    cancellation.status = EventStatus.CANCELLED
    cancellation.status_evidence = EvidenceLevel.EXPLICIT

    merged = EventDeduplicator().merge(data["duplicate_a"], cancellation)

    assert merged.status is EventStatus.CANCELLED


def test_merge_enriches_unknown_free_food_but_surfaces_explicit_contradictions():
    data = events()
    unknown = data["duplicate_a"].model_copy(deep=True)
    unknown.food.free_food = TriState.UNKNOWN
    unknown.food.free_food_evidence = EvidenceLevel.UNKNOWN
    explicit = data["duplicate_b"].model_copy(deep=True)

    enriched = EventDeduplicator().merge(unknown, explicit)
    assert enriched.food.free_food is TriState.YES
    assert enriched.food.free_food_evidence is EvidenceLevel.EXPLICIT

    contradiction = explicit.model_copy(deep=True)
    contradiction.food.free_food = TriState.NO
    contradiction.food.free_food_evidence = EvidenceLevel.EXPLICIT
    conflicted = EventDeduplicator().merge(data["duplicate_a"], contradiction)
    assert conflicted.food.free_food is TriState.UNKNOWN
    assert "conflicting free-food claims" in conflicted.conflicts


def test_merge_is_order_independent_and_surfaces_explicit_food_and_time_disagreements():
    left = events()["duplicate_a"]
    left.start_time = datetime(2026, 9, 18, 18, 0, tzinfo=TZ)
    right = events()["duplicate_b"]
    right.start_time = left.start_time + timedelta(minutes=10)
    right.food.description = "tacos"
    right.sources[0].retrieved_at = NOW + timedelta(minutes=1)

    matcher = EventDeduplicator()
    forward = matcher.merge(left, right)
    reverse = matcher.merge(right, left)

    assert forward.model_dump() == reverse.model_dump()
    assert forward.conflicts >= ["conflicting food descriptions", "conflicting start times"]
    assert forward.sources == sorted(
        forward.sources,
        key=lambda source: (
            source.retrieved_at.isoformat(), source.type.value, source.url or "",
            source.external_id or "", source.raw_text,
        ),
    )


def test_merge_clears_an_end_time_that_would_precede_the_selected_start():
    later_start = events()["duplicate_a"].model_copy(deep=True)
    later_start.start_time = datetime(2026, 9, 18, 18, 10, tzinfo=TZ)
    later_start.end_time = None
    earlier_interval = events()["duplicate_b"].model_copy(deep=True)
    earlier_interval.start_time = datetime(2026, 9, 18, 18, 0, tzinfo=TZ)
    earlier_interval.end_time = datetime(2026, 9, 18, 18, 5, tzinfo=TZ)

    merged = EventDeduplicator().merge(later_start, earlier_interval)

    assert merged.start_time == later_start.start_time
    assert merged.end_time is None
    assert "conflicting event intervals" in merged.conflicts


def test_merge_deterministically_keeps_the_newest_copy_of_the_same_source():
    left = events()["duplicate_a"]
    right = events()["duplicate_b"]
    right.sources[0] = left.sources[0].model_copy(deep=True)
    right.sources[0].retrieved_at = left.sources[0].retrieved_at + timedelta(minutes=1)

    matcher = EventDeduplicator()
    forward = matcher.merge(left, right)
    reverse = matcher.merge(right, left)

    assert forward.model_dump() == reverse.model_dump()
    assert len(forward.sources) == 1
    assert forward.sources[0].retrieved_at == right.sources[0].retrieved_at


def test_missing_organization_uses_strong_core_match_without_merging_different_locations():
    base = events()["duplicate_a"]
    missing_org = base.model_copy(deep=True)
    missing_org.event_id = "missing-org"
    missing_org.organization = None

    matcher = EventDeduplicator()
    assert matcher.compare(base, missing_org).is_duplicate

    other_location = missing_org.model_copy(deep=True)
    other_location.event_id = "other-location"
    other_location.location = EventLocation(building="Reitz", room="2355", raw_text="Reitz 2355")
    assert not matcher.compare(base, other_location).is_duplicate


def test_org_less_generic_events_require_compatible_food_to_match():
    left = events()["duplicate_a"].model_copy(deep=True)
    left.organization = None
    right = events()["duplicate_b"].model_copy(deep=True)
    right.organization = None

    matcher = EventDeduplicator()
    assert matcher.compare(left, right).is_duplicate

    different_food = right.model_copy(deep=True)
    different_food.food.description = "tacos"
    assert not matcher.compare(left, different_food).is_duplicate


def test_similar_food_events_on_same_day_are_not_automatically_duplicates():
    data = events()
    matcher = EventDeduplicator()
    decision = matcher.compare(data["explicit_free_pizza"], data["conflicting_times"])
    assert not decision.is_duplicate
    assert decision.score < 0.8
    same_org_different_time = matcher.compare(data["explicit_free_pizza"], data["duplicate_a"])
    assert not same_org_different_time.is_duplicate


def test_same_org_generic_title_close_times_and_different_rooms_do_not_merge():
    left = events()["duplicate_a"].model_copy(deep=True)
    right = events()["duplicate_b"].model_copy(deep=True)
    right.start_time = left.start_time + timedelta(minutes=10)
    right.location = EventLocation(building="Little Hall", room="109", raw_text="Little 109")

    decision = EventDeduplicator().compare(left, right)

    assert not decision.is_duplicate
    assert "contradictory explicit location" in decision.reasons


def test_similar_organization_names_do_not_merge_distinct_events():
    left = events()["duplicate_a"].model_copy(deep=True)
    right = events()["duplicate_a"].model_copy(deep=True)
    right.event_id = "other"
    right.organization = "Gator AI Club"
    right.event_name = "Workshop"
    right.location = EventLocation(building="Weil", room="270", raw_text="Weil 270")

    assert not EventDeduplicator().compare(left, right).is_duplicate


def test_true_duplicate_with_formatting_differences_still_merges():
    data = events()
    matcher = EventDeduplicator()
    assert matcher.compare(data["duplicate_a"], data["duplicate_b"]).is_duplicate
    merged = matcher.merge(data["duplicate_a"], data["duplicate_b"])
    assert len(merged.sources) == 2


def test_duplicate_with_one_missing_room_can_still_merge():
    left = events()["duplicate_a"].model_copy(deep=True)
    right = events()["duplicate_b"].model_copy(deep=True)
    right.location = EventLocation(building="Little Hall", raw_text="Little Hall")

    decision = EventDeduplicator().compare(left, right)

    assert decision.is_duplicate

