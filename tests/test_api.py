from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from gatorgrub.api.app import create_app
from gatorgrub.domain.models import (
    AttendanceInfo, EvidenceLevel, EventLocation, EventStatus, FoodEvent, FoodInfo,
    TriState,
)
from gatorgrub.storage.repository import InMemoryEventRepository


def client():
    return TestClient(create_app(InMemoryEventRepository()))


def test_health_and_empty_events():
    web = client()
    assert web.get("/health").json() == {"status": "ok"}
    assert web.get("/events").json() == []


def test_public_feed_only_exposes_trusted_or_likely_events():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 9, 17, 12, tzinfo=tz)
    repo = InMemoryEventRepository(clock=lambda: now)

    def add(event_id, *, ambiguous=False, free=TriState.YES, status=EventStatus.SCHEDULED,
            start_time=None, attendance=TriState.YES):
        repo.add(FoodEvent(
            event_id=event_id,
            event_name=event_id,
            start_time=start_time or now + timedelta(days=1),
            location=EventLocation(raw_text="Little 101", ambiguous=ambiguous),
            food=FoodInfo(free_food=free, free_food_evidence=(
                EvidenceLevel.EXPLICIT if free is not TriState.UNKNOWN else EvidenceLevel.UNKNOWN)),
            attendance=AttendanceInfo(open_to_all=attendance, evidence=EvidenceLevel.EXPLICIT),
            status=status,
        ))

    add("trusted")
    add("likely", attendance=TriState.UNKNOWN)
    add("review", ambiguous=True)
    add("rejected", free=TriState.UNKNOWN)
    add("cancelled", status=EventStatus.CANCELLED)
    add("expired", start_time=now - timedelta(days=1))

    response = TestClient(create_app(repo, clock=lambda: now)).get("/events")

    assert response.status_code == 200
    assert {event["event_id"] for event in response.json()} == {"trusted", "likely"}


def test_ingest_get_search_and_confirm_vertical_flow():
    web = client()
    ingested = web.post("/ingest", json={
        "text": "Gator AI GBM on September 18, 2099 from 5:30 PM-6:30 PM at Little Hall 101. FREE PIZZA. Open to all!"
    })
    assert ingested.status_code == 201
    event = ingested.json()
    event_id = event["event_id"]
    assert event["verification_status"] == "trusted"
    assert web.get(f"/events/{event_id}").json()["food"]["free_food"] == "yes"

    search = web.post("/search", json={
        "available_start": "2099-09-18T17:10:00-04:00",
        "available_end": "2099-09-18T18:45:00-04:00",
        "dietary_preferences": ["vegetarian"], "meal_preference": "meal",
        "origin": "Marston Science Library", "max_walk_minutes": 15
    })
    assert search.status_code == 200
    assert search.json()[0]["components"]["dietary"] < 0

    confirmed = web.post("/confirm", json={"event_id": event_id, "availability": "plenty"})
    assert confirmed.status_code == 200
    assert confirmed.json()["availability"] == "plenty"
    assert confirmed.json()["availability_confirmed_at"] is not None


def test_ingest_rejects_whitespace_only_text_at_request_boundary():
    response = client().post("/ingest", json={"text": " \n\t "})
    assert response.status_code == 422


def test_missing_event_and_bad_ingest_have_clean_http_errors():
    web = client()
    assert web.get("/events/nope").status_code == 404
    response = web.post("/ingest", json={"text": ""})
    assert response.status_code == 422


def test_api_uses_live_clock_for_each_relative_ingest():
    tz = ZoneInfo("America/New_York")
    current = [datetime(2026, 9, 17, 12, tzinfo=tz)]
    web = TestClient(create_app(clock=lambda: current[0]))

    first = web.post("/ingest", json={
        "text": "Gator AI GBM tomorrow at 6 PM in Little 101. Free pizza."
    }).json()
    current[0] += timedelta(days=1)
    second = web.post("/ingest", json={
        "text": "ACM GBM tomorrow at 7 PM in CSE E221. Free tacos."
    }).json()

    assert first["start_time"].startswith("2026-09-18T18:00:00")
    assert first["sources"][0]["retrieved_at"].startswith("2026-09-17T12:00:00")
    assert second["start_time"].startswith("2026-09-19T19:00:00")
    assert second["sources"][0]["retrieved_at"].startswith("2026-09-18T12:00:00")


def test_api_detail_and_confirm_apply_effective_expiration():
    tz = ZoneInfo("America/New_York")
    current = [datetime(2026, 9, 17, 12, tzinfo=tz)]
    repo = InMemoryEventRepository(clock=lambda: current[0])
    event = FoodEvent(
        event_id="expires",
        event_name="Dinner",
        start_time=current[0] + timedelta(hours=1),
        end_time=current[0] + timedelta(hours=3),
        location=EventLocation(raw_text="Little 101"),
        food=FoodInfo(free_food=TriState.YES, free_food_evidence=EvidenceLevel.EXPLICIT),
        attendance=AttendanceInfo(open_to_all=TriState.YES, evidence=EvidenceLevel.EXPLICIT),
    )
    repo.add(event)
    web = TestClient(create_app(repo, clock=lambda: current[0]))
    assert web.get("/events/expires").json()["verification_status"] == "trusted"

    current[0] = event.start_time + timedelta(hours=3)

    detail = web.get("/events/expires")
    confirmed = web.post("/confirm", json={
        "event_id": "expires", "availability": "plenty",
    })
    assert detail.json()["verification_status"] == "expired"
    assert confirmed.json()["verification_status"] == "expired"


def test_events_feed_can_collapse_series_without_changing_canonical_records():
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 9, 17, 12, tzinfo=tz)
    repo = InMemoryEventRepository(clock=lambda: now)
    for index, day in enumerate((23, 30)):
        repo.add(FoodEvent(
            event_id=f"gbm-{index}",
            organization="FBLS",
            event_name="GBM",
            start_time=datetime(2026, 9, day, 18, 30, tzinfo=tz),
            location=EventLocation(raw_text="Heavener 260", building="Heavener", room="260"),
            food=FoodInfo(free_food=TriState.YES, free_food_evidence=EvidenceLevel.EXPLICIT),
            attendance=AttendanceInfo(open_to_all=TriState.YES, evidence=EvidenceLevel.EXPLICIT),
            canonical_organization_id="gc-1",
        ))
    web = TestClient(create_app(repo, clock=lambda: now))
    raw = web.get("/events").json()
    collapsed = web.get("/events", params={"collapse_series": True}).json()
    assert len(raw) == 2
    assert len(collapsed) == 1
    assert collapsed[0]["occurrence_count"] == 2
    assert collapsed[0]["next_event_id"] == "gbm-0"
    assert len(repo.list()) == 2

