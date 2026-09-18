from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from gatorgrub.domain.models import (
    EvidenceLevel, EventLocation, EventSource, FoodEvent, FoodInfo, SourceType,
    TriState, VerificationStatus,
)
from gatorgrub.storage.repository import InMemoryEventRepository, Repository

TZ = ZoneInfo("America/New_York")
SOURCE = EventSource(type=SourceType.PASTED_TEXT, raw_text="Free pizza", retrieved_at=datetime(2026, 9, 17, 12, tzinfo=TZ))


def event(event_id="e1", minute=0):
    return FoodEvent(event_id=event_id, organization="Gator AI", event_name="GBM",
                     start_time=datetime(2026, 9, 18, 18, minute, tzinfo=TZ), sources=[SOURCE])


def test_repository_protocol_crud_and_duplicate_id_safety():
    repo: Repository = InMemoryEventRepository()
    repo.add(event())
    assert repo.get("e1").event_name == "GBM"
    assert len(repo.list()) == 1
    with pytest.raises(ValueError, match="already exists"):
        repo.add(event())
    changed = event()
    changed.event_name = "Updated GBM"
    repo.update(changed)
    assert repo.get("e1").event_name == "Updated GBM"
    assert repo.get("missing") is None


def test_repository_recalculates_expiration_after_ingestion_with_injected_clock():
    current = [datetime(2026, 9, 18, 17, tzinfo=TZ)]
    repo = InMemoryEventRepository(clock=lambda: current[0])
    scheduled = FoodEvent(
        event_id="fresh",
        event_name="Dinner",
        start_time=current[0] + timedelta(hours=1),
        location=EventLocation(raw_text="Little 101"),
        food=FoodInfo(free_food=TriState.YES, free_food_evidence=EvidenceLevel.EXPLICIT),
        sources=[SOURCE],
    )
    repo.add(scheduled)

    current[0] = scheduled.start_time + timedelta(hours=3)

    refreshed = repo.list()[0]
    assert refreshed.verification_status is VerificationStatus.REVIEW_NEEDED
    assert refreshed.end_time is None
    assert "unknown end time; assumed window elapsed" in refreshed.confidence.reasons


def test_repository_merge_collapses_duplicate_ids_and_sources():
    repo = InMemoryEventRepository()
    repo.add(event("e2", 0))
    second = event("e3", 5)
    second.sources[0] = second.sources[0].model_copy(update={"raw_text": "Another post"})
    repo.add(second)
    merged = repo.merge("e2", "e3")
    assert len(repo.list()) == 1
    assert repo.get(merged.event_id) is not None
    assert len(merged.sources) == 2
