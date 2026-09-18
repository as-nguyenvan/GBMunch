from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import MealLevel, SearchPreferences
from gatorgrub.extraction.extractor import DeterministicExtractor
from gatorgrub.ingestion.adapters import JsonFixtureAdapter
from gatorgrub.recommendation.ranker import rank_events
from gatorgrub.verification.verifier import EventVerifier

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "announcements.json"


def prepared():
    rows = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=NOW)
    parser, verifier = DeterministicExtractor(reference_time=NOW), EventVerifier()
    return [verifier.verify(parser.extract(row), now=NOW) for row in rows]


def prefs(**changes):
    values = dict(available_start=datetime(2026, 9, 18, 17, 10, tzinfo=TZ),
                  available_end=datetime(2026, 9, 18, 18, 45, tzinfo=TZ),
                  dietary_preferences=["vegetarian"], meal_preference=MealLevel.MEAL,
                  origin="Marston Science Library", max_walk_minutes=15)
    values.update(changes)
    return SearchPreferences(**values)


def test_ranking_filters_window_free_status_and_meal_then_sorts_deterministically():
    results = rank_events(prepared(), prefs())
    assert results
    assert all(r.event.food.free_food.value == "yes" for r in results)
    assert all(r.event.food.meal_level is MealLevel.MEAL for r in results)
    assert all(prefs().available_start <= r.event.start_time <= prefs().available_end for r in results)
    assert results[0].event.food.dietary.vegetarian.value == "yes"
    assert [r.score for r in results] == sorted([r.score for r in results], reverse=True)


def test_unknown_dietary_is_penalized_and_never_described_as_suitable():
    results = rank_events(prepared(), prefs())
    unknown = next(r for r in results if r.event.food.dietary.vegetarian.value == "unknown")
    assert unknown.components["dietary"] < 0
    assert "Vegetarian suitability is unknown" in unknown.explanation
    assert "vegetarian suitable" not in unknown.explanation.lower()


def test_optional_proximity_is_an_explicit_placeholder_and_scores_are_explained():
    result = rank_events(prepared(), prefs())[0]
    assert result.components.keys() >= {"confidence", "dietary", "meal", "freshness", "status", "proximity"}
    assert result.components["proximity"] == 0.05
    assert "15-minute proximity is a placeholder" in result.explanation


def test_ranking_uses_event_interval_overlap_and_excludes_non_overlaps():
    window = prefs(dietary_preferences=[], meal_preference=None)
    base = prepared()[0]
    ongoing = base.model_copy(deep=True, update={
        "event_id": "ongoing",
        "start_time": window.available_start - timedelta(hours=1),
        "end_time": window.available_start + timedelta(minutes=15),
    })
    ended = base.model_copy(deep=True, update={
        "event_id": "ended",
        "start_time": window.available_start - timedelta(hours=3),
        "end_time": window.available_start - timedelta(minutes=1),
    })
    later = base.model_copy(deep=True, update={
        "event_id": "later",
        "start_time": window.available_end + timedelta(minutes=1),
        "end_time": None,
    })

    results = rank_events([ongoing, ended, later], window)

    assert [result.event.event_id for result in results] == ["ongoing"]


def test_min_useful_minutes_excludes_trivial_overlap():
    window = prefs(
        dietary_preferences=[],
        meal_preference=None,
        available_start=datetime(2026, 9, 18, 17, 10, tzinfo=TZ),
        available_end=datetime(2026, 9, 18, 18, 45, tzinfo=TZ),
        min_useful_minutes=15,
    )
    base = prepared()[0]
    trivial = base.model_copy(deep=True, update={
        "event_id": "late",
        "start_time": datetime(2026, 9, 18, 18, 40, tzinfo=TZ),
        "end_time": datetime(2026, 9, 18, 20, 0, tzinfo=TZ),
    })
    useful = base.model_copy(deep=True, update={
        "event_id": "useful",
        "start_time": datetime(2026, 9, 18, 18, 0, tzinfo=TZ),
        "end_time": datetime(2026, 9, 18, 20, 0, tzinfo=TZ),
    })

    results = rank_events([trivial, useful], window)

    assert [result.event.event_id for result in results] == ["useful"]

