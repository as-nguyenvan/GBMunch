from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.deduplication.matcher import EventDeduplicator
from gatorgrub.domain.models import MealLevel, SearchPreferences
from gatorgrub.extraction.extractor import DeterministicExtractor
from gatorgrub.ingestion.adapters import JsonFixtureAdapter
from gatorgrub.storage.repository import InMemoryEventRepository
from gatorgrub.verification.verifier import EventVerifier

TZ = ZoneInfo("America/New_York")
FIXED_NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)


def run_demo(fixture_path: Path) -> dict:
    candidates = JsonFixtureAdapter().ingest(fixture_path, retrieved_at=FIXED_NOW)
    extractor = DeterministicExtractor(reference_time=FIXED_NOW)
    verifier = EventVerifier()
    verified = [verifier.verify(extractor.extract(candidate), now=FIXED_NOW) for candidate in candidates]
    canonical = EventDeduplicator().collapse(verified)
    repository = InMemoryEventRepository(clock=lambda: FIXED_NOW)
    for event in canonical:
        repository.add(event)
    preferences = SearchPreferences(
        available_start=datetime(2026, 9, 18, 17, 10, tzinfo=TZ),
        available_end=datetime(2026, 9, 18, 18, 45, tzinfo=TZ),
        dietary_preferences=["vegetarian"], meal_preference=MealLevel.MEAL,
        origin="Marston Science Library", max_walk_minutes=15,
    )
    results = repository.search(preferences)
    return {
        "raw_candidates": len(candidates),
        "canonical_events": len(canonical),
        "query": {
            "available_window": "2026-09-18 17:10–18:45 America/New_York",
            "dietary_preferences": ["vegetarian"], "meal_preference": "meal",
            "origin": preferences.origin, "max_walk_minutes": preferences.max_walk_minutes,
        },
        "results": [{
            "event_id": result.event.event_id,
            "organization": result.event.organization,
            "event_name": result.event.event_name,
            "start_time": result.event.start_time.isoformat() if result.event.start_time else None,
            "food": result.event.food.description,
            "vegetarian": result.event.food.dietary.vegetarian.value,
            "score": result.score,
            "components": result.components,
            "explanation": result.explanation,
        } for result in results],
    }
