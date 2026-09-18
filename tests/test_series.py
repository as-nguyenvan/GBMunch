from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import EventLocation, FoodEvent, FoodInfo, TriState
from gatorgrub.recommendation.series import collapse_event_series
from gatorgrub.verification.verifier import EventVerifier

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)


def event(event_id, org, title, start, location="Heavener 260", canonical="gc-1"):
    item = FoodEvent(
        event_id=event_id,
        organization=org,
        event_name=title,
        start_time=start,
        end_time=start + timedelta(hours=1),
        location=EventLocation(raw_text=location, building="Heavener", room="260" if "260" in location else "101"),
        food=FoodInfo(free_food=TriState.YES),
        canonical_organization_id=canonical,
    )
    return EventVerifier().verify(item, now=NOW)


def test_weekly_same_org_title_and_location_collapse_to_next_occurrence():
    events = [
        event("a", "FBLS", "GBM", datetime(2026, 9, 23, 18, 30, tzinfo=TZ)),
        event("b", "FBLS", "GBM", datetime(2026, 9, 30, 18, 30, tzinfo=TZ)),
        event("c", "FBLS", "GBM", datetime(2026, 10, 7, 18, 30, tzinfo=TZ)),
    ]
    grouped = collapse_event_series(events, now=NOW)
    assert len(events) == 3
    assert len(grouped) == 1
    item = grouped[0]
    assert item.next_event_id == "a"
    assert item.occurrence_count == 3
    assert item.upcoming_dates[0] == events[0].start_time


def test_same_title_different_location_or_org_is_not_grouped():
    shared = datetime(2026, 9, 23, 18, 30, tzinfo=TZ)
    different_location = [
        event("a", "FBLS", "GBM", shared, location="Heavener 260"),
        event("b", "FBLS", "GBM", shared + timedelta(days=7), location="Little 101"),
    ]
    different_org = [
        event("a", "FBLS", "GBM", shared, canonical="gc-1"),
        event("b", "Other Club", "GBM", shared + timedelta(days=7), canonical="gc-2"),
    ]
    assert len(collapse_event_series(different_location, now=NOW)) == 2
    assert len(collapse_event_series(different_org, now=NOW)) == 2
