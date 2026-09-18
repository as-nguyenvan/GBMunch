from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import EndTimeBasis, VerificationStatus
from gatorgrub.extraction.extractor import DeterministicExtractor
from gatorgrub.ingestion.adapters import JsonFixtureAdapter, PastedTextAdapter
from gatorgrub.verification.verifier import EventVerifier, event_interval

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 12, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "announcements.json"


def verified():
    raw = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=NOW)
    extractor = DeterministicExtractor(reference_time=NOW)
    verifier = EventVerifier()
    return {c.metadata["case"]: verifier.verify(extractor.extract(c), now=NOW) for c in raw}


def test_verifier_terminal_statuses_and_no_free_evidence():
    events = verified()
    assert events["past"].verification_status is VerificationStatus.REVIEW_NEEDED
    assert "unknown end time; assumed window elapsed" in events["past"].confidence.reasons
    assert events["past"].end_time is None
    assert events["cancelled"].verification_status is VerificationStatus.CANCELLED
    assert events["low_info"].verification_status is VerificationStatus.REJECTED
    assert events["pizza_free_unknown"].verification_status is VerificationStatus.REJECTED


def test_verifier_keeps_an_event_active_until_its_end_time():
    raw = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=NOW)[0]
    event = DeterministicExtractor(reference_time=NOW).extract(raw)
    event.start_time = NOW - timedelta(minutes=30)
    event.end_time = NOW + timedelta(minutes=30)

    checked = EventVerifier().verify(event, now=NOW)

    assert checked.verification_status is not VerificationStatus.EXPIRED


def test_verifier_flags_conflicts_and_ambiguous_location_for_review():
    events = verified()
    assert events["conflicting_times"].verification_status is VerificationStatus.REVIEW_NEEDED
    assert events["ambiguous_location"].verification_status is VerificationStatus.REVIEW_NEEDED
    assert "ambiguous location" in events["ambiguous_location"].confidence.reasons


def test_verifier_confidence_is_transparent_and_can_be_trusted_or_likely():
    events = verified()
    trusted = events["explicit_free_pizza"]
    likely = events["missing_org"]
    assert trusted.verification_status is VerificationStatus.TRUSTED
    assert likely.verification_status is VerificationStatus.LIKELY
    assert trusted.confidence.overall > likely.confidence.overall
    assert trusted.confidence.fields["food"].reason == "explicit free-food evidence"


def test_stale_source_is_visible_and_requires_review():
    raw = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=NOW)[0]
    event = DeterministicExtractor(reference_time=NOW).extract(raw)
    event.sources[0].posted_at = NOW - timedelta(days=30)
    checked = EventVerifier().verify(event, now=NOW)
    assert checked.verification_status is VerificationStatus.REVIEW_NEEDED
    assert "stale source" in checked.confidence.reasons


def test_verifier_never_trusts_a_contradicted_free_food_claim():
    candidate = PastedTextAdapter().ingest(
        "Gator AI GBM tomorrow at 6 PM in Little 101. Free pizza? No, pizza costs $5.",
        retrieved_at=NOW,
    )
    extracted = DeterministicExtractor(reference_time=NOW).extract(candidate)

    checked = EventVerifier().verify(extracted, now=NOW)

    assert checked.verification_status is VerificationStatus.REJECTED
    assert checked.confidence.fields["food"].reason == "no explicit free-food evidence"


def test_unknown_end_time_stays_canonical_none_and_uses_labeled_heuristic():
    event = DeterministicExtractor(reference_time=NOW).extract(
        PastedTextAdapter().ingest(
            "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.",
            retrieved_at=NOW,
        )
    )
    interval = event_interval(event)

    assert event.end_time is None
    assert interval is not None
    assert interval.end_time_basis is EndTimeBasis.HEURISTIC_DEFAULT
    assert interval.effective_end_time == event.start_time + EventVerifier.DEFAULT_EVENT_DURATION


def test_unknown_end_does_not_confidently_expire_after_assumed_window():
    event = DeterministicExtractor(reference_time=NOW).extract(
        PastedTextAdapter().ingest(
            "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza. Open to all!",
            retrieved_at=NOW,
        )
    )
    later = event.start_time + EventVerifier.DEFAULT_EVENT_DURATION
    assumed = EventVerifier().verify(event.model_copy(deep=True), now=later)
    explicit = event.model_copy(deep=True)
    explicit.end_time = later
    ended = EventVerifier().verify(explicit, now=later)

    assert assumed.end_time is None
    assert assumed.verification_status is VerificationStatus.REVIEW_NEEDED
    assert assumed.status.value != "expired"
    assert ended.verification_status is VerificationStatus.EXPIRED

