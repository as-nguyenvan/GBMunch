from pathlib import Path

from gatorgrub.demo import run_demo


def test_offline_demo_is_stable_and_exercises_full_pipeline():
    output = run_demo(Path(__file__).parent / "fixtures" / "announcements.json")
    assert output["raw_candidates"] == 20
    assert output["canonical_events"] == 19
    assert output["query"]["available_window"] == "2026-09-18 17:10–18:45 America/New_York"
    assert output["query"]["origin"] == "Marston Science Library"
    assert output["query"]["max_walk_minutes"] == 15
    assert output["results"]
    assert output["results"][0]["vegetarian"] == "yes"
    assert output["results"][0]["components"]
    assert output["results"][0]["explanation"]
