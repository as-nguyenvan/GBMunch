from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.acquisition.gatorconnect import GatorConnectClient
from gatorgrub.domain.models import SourceType, TriState, VerificationStatus
from gatorgrub.ingestion.gatorconnect import GatorConnectEventAdapter
from gatorgrub.pipeline import ProcessingPipeline
from gatorgrub.registry.organizations import OrganizationRegistry
from gatorgrub.storage.repository import InMemoryEventRepository

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "gatorconnect_events.json"
ORGS = Path(__file__).parent / "fixtures" / "organizations_sample.jsonl"


def pages():
    import json
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload


def test_client_paginates_without_network():
    payload = pages()
    calls = []

    def getter(url: str):
        calls.append(url)
        if "skip=0" in url:
            return {"@odata.count": 3, "value": payload["value"][:2]}
        if "skip=2" in url:
            return {"@odata.count": 3, "value": payload["value"][2:3]}
        return {"@odata.count": 3, "value": []}

    events = list(GatorConnectClient(getter=getter, page_size=2, delay_s=0).iter_events())
    assert len(events) == 3
    assert any("skip=0" in url for url in calls)
    assert any("skip=2" in url for url in calls)


def test_adapter_preserves_provenance_datetimes_and_unknown_end():
    registry = OrganizationRegistry.load(ORGS)
    candidates = GatorConnectEventAdapter(registry).ingest(pages()["value"], retrieved_at=NOW)
    by_id = {c.external_id: c for c in candidates}

    ordinary = by_id["12779993"]
    assert ordinary.source_type is SourceType.GATORCONNECT
    assert ordinary.source_url == "https://gatorconnect.ufl.edu/event/12779993"
    assert ordinary.external_id == "12779993"
    assert ordinary.metadata["canonical_organization_id"] == "gc-430308"
    assert ordinary.metadata["organization_mapped"] is True
    assert ordinary.metadata["structured_start"].tzinfo is not None
    assert ordinary.metadata["structured_end"] is not None

    no_end = by_id["gc-noend-1"]
    assert no_end.metadata.get("structured_end") is None

    unmapped = by_id["gc-unmapped-1"]
    assert unmapped.metadata["canonical_organization_id"] is None
    assert unmapped.metadata["organization_mapped"] is False
    assert unmapped.metadata["source_organization_id"] == "999999999"
    assert unmapped.metadata["organization_name"] == "Unknown Student Org"


def test_exact_organization_id_mapping_does_not_fuzzy_match():
    registry = OrganizationRegistry.load(ORGS)
    mapped = registry.lookup("430308")
    unknown = registry.lookup("999999999")
    assert mapped is not None
    assert mapped.canonical_id == "gc-430308"
    assert unknown is None


def test_fixture_events_pass_through_pipeline_without_network():
    registry = OrganizationRegistry.load(ORGS)
    candidates = GatorConnectEventAdapter(registry).ingest(pages()["value"], retrieved_at=NOW)
    repo = InMemoryEventRepository(clock=lambda: NOW)
    pipeline = ProcessingPipeline(repo, reference_time=NOW)
    events = [pipeline.process(candidate) for candidate in candidates]
    by_ext = {event.sources[0].external_id: event for event in events}

    food = by_ext["gc-food-1"]
    assert food.canonical_organization_id == "gc-429964"
    assert food.organization == "3D Printing Club"
    assert food.food.free_food is TriState.YES
    assert food.end_time is not None
    assert food.sources[0].url.endswith("/event/gc-food-1")

    unknown_food = by_ext["gc-food-unknown-1"]
    assert unknown_food.food.description == "pizza"
    assert unknown_food.food.free_food is TriState.UNKNOWN

    no_end = by_ext["gc-noend-1"]
    assert no_end.end_time is None

    cancelled = by_ext["gc-cancel-1"]
    assert cancelled.verification_status is VerificationStatus.CANCELLED

    unmapped = by_ext["gc-unmapped-1"]
    assert unmapped.canonical_organization_id is None
    assert unmapped.organization == "Unknown Student Org"


def test_acquired_events_are_served_by_existing_api():
    from fastapi.testclient import TestClient
    from gatorgrub.api.app import create_app

    registry = OrganizationRegistry.load(ORGS)
    candidates = GatorConnectEventAdapter(registry).ingest(pages()["value"], retrieved_at=NOW)
    repo = InMemoryEventRepository(clock=lambda: NOW)
    pipeline = ProcessingPipeline(repo, reference_time=NOW)
    for candidate in candidates:
        pipeline.process(candidate)

    web = TestClient(create_app(repo, clock=lambda: NOW))
    feed = web.get("/events").json()
    food = next(event for event in feed if event["sources"][0]["external_id"] == "gc-food-1")
    assert food["canonical_organization_id"] == "gc-429964"
    assert food["food"]["free_food"] == "yes"
    search = web.post("/search", json={
        "available_start": "2026-09-18T17:10:00-04:00",
        "available_end": "2026-09-18T19:00:00-04:00",
        "dietary_preferences": [],
        "meal_preference": None,
        "min_useful_minutes": 0,
    })
    assert search.status_code == 200
    assert any(item["event"]["sources"][0]["external_id"] == "gc-food-1" for item in search.json())

