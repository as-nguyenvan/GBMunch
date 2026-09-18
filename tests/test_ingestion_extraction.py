import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import EvidenceLevel, EventStatus, SourceType, TriState, VerificationStatus
from gatorgrub.extraction.extractor import DeterministicExtractor, Extractor
from gatorgrub.ingestion.adapters import JsonFixtureAdapter, PastedTextAdapter, SourceAdapter
from gatorgrub.verification.verifier import EventVerifier

TZ = ZoneInfo("America/New_York")
REF = datetime(2026, 9, 17, 12, tzinfo=TZ)
FIXTURE = Path(__file__).parent / "fixtures" / "announcements.json"


def test_adapters_share_raw_candidate_contract():
    pasted: SourceAdapter = PastedTextAdapter()
    fixtures: SourceAdapter = JsonFixtureAdapter()
    one = pasted.ingest("Free pizza", retrieved_at=REF)
    many = fixtures.ingest(FIXTURE, retrieved_at=REF)
    assert one.source_type is SourceType.PASTED_TEXT
    assert len(many) == 20
    assert all(item.source_type is SourceType.JSON_FIXTURE for item in many)


def test_json_adapter_preserves_posted_at_for_staleness_and_excludes_envelope_metadata():
    candidates = JsonFixtureAdapter().ingest([{
        "id": "old-post",
        "text": "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.",
        "source_url": "https://example.test/event",
        "posted_at": "2026-08-01T12:00:00-04:00",
        "case": "stale",
    }], retrieved_at=REF)
    candidate = candidates[0]

    assert candidate.posted_at == datetime.fromisoformat("2026-08-01T12:00:00-04:00")
    assert candidate.metadata == {"case": "stale"}
    event = DeterministicExtractor(reference_time=REF).extract(candidate)
    assert EventVerifier().verify(event, now=REF).verification_status is VerificationStatus.REVIEW_NEEDED


def test_extractor_boundary_and_unknown_preservation():
    extractor: Extractor = DeterministicExtractor(reference_time=REF)
    candidates = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=REF)
    by_case = {c.metadata["case"]: extractor.extract(c) for c in candidates}
    assert by_case["explicit_free_pizza"].food.free_food is TriState.YES
    assert by_case["explicit_free_pizza"].food.free_food_evidence is EvidenceLevel.EXPLICIT
    assert by_case["pizza_free_unknown"].food.description == "pizza"
    assert by_case["pizza_free_unknown"].food.free_food is TriState.UNKNOWN
    assert by_case["emoji_only"].food.description == "possible pizza"
    assert by_case["emoji_only"].food.description_evidence is EvidenceLevel.INFERRED
    assert by_case["emoji_only"].food.free_food is TriState.UNKNOWN
    assert by_case["absent_dietary"].food.dietary.vegetarian is TriState.UNKNOWN
    assert by_case["absent_dietary"].food.dietary.halal is TriState.UNKNOWN
    assert by_case["pizza_free_unknown"].attendance.open_to_all is TriState.UNKNOWN


def test_extractor_does_not_infer_free_or_dietary_claims_from_unscoped_words():
    extractor = DeterministicExtractor(reference_time=REF)

    free_admission = extractor.extract(PastedTextAdapter().ingest(
        "Gator AI GBM tomorrow at 6 PM in Little 101. Free admission; pizza costs $5.",
        retrieved_at=REF,
    ))
    sugar_free = extractor.extract(PastedTextAdapter().ingest(
        "ACM GBM tomorrow at 7 PM in CSE E221. Sugar-free cookies cost $2.",
        retrieved_at=REF,
    ))
    negated = extractor.extract(PastedTextAdapter().ingest(
        "Dinner tomorrow at 6 PM in Reitz 2365. Free pasta; no vegetarian or vegan options.",
        retrieved_at=REF,
    ))
    organization_only = extractor.extract(PastedTextAdapter().ingest(
        "Vegan Club meeting tomorrow at 6 PM in Reitz 2365. Free pizza.",
        retrieved_at=REF,
    ))

    assert free_admission.food.free_food is TriState.UNKNOWN
    assert sugar_free.food.free_food is TriState.UNKNOWN
    assert negated.food.dietary.vegetarian is TriState.NO
    assert negated.food.dietary.vegan is TriState.NO
    assert organization_only.food.dietary.vegan is TriState.UNKNOWN


def test_extractor_rejects_negated_or_contradicted_free_food_claims():
    extractor = DeterministicExtractor(reference_time=REF)

    denied = extractor.extract(PastedTextAdapter().ingest(
        "Gator AI GBM tomorrow at 6 PM in Little 101. No free pizza.",
        retrieved_at=REF,
    ))
    contradicted = extractor.extract(PastedTextAdapter().ingest(
        "Gator AI GBM tomorrow at 6 PM in Little 101. Free pizza? No, pizza costs $5.",
        retrieved_at=REF,
    ))
    direct = extractor.extract(PastedTextAdapter().ingest(
        "Gator AI GBM tomorrow at 6 PM in Little 101. FREE PIZZA.",
        retrieved_at=REF,
    ))

    assert denied.food.free_food is TriState.UNKNOWN
    assert contradicted.food.free_food is TriState.UNKNOWN
    assert direct.food.free_food is TriState.YES


def test_extractor_recognizes_explicit_free_meals_but_not_bare_meal_words():
    extractor = DeterministicExtractor(reference_time=REF)

    def extract(phrase: str):
        return extractor.extract(PastedTextAdapter().ingest(
            f"Gator AI GBM tomorrow at 6 PM in Little 101. {phrase}",
            retrieved_at=REF,
        ))

    for phrase in ("enjoy free dinner", "free lunch", "free breakfast", "complimentary dinner"):
        assert extract(phrase).food.free_food is TriState.YES, phrase

    for phrase in ("dinner provided", "lunch available"):
        assert extract(phrase).food.free_food is TriState.UNKNOWN, phrase

    paid = extract("bring $5 for dinner")
    assert paid.food.free_food is not TriState.YES

    historical = extract("last week's free dinner was awesome")
    assert historical.food.free_food is TriState.UNKNOWN



def test_extractor_keeps_hedged_historical_and_paid_free_food_claims_unknown():
    extractor = DeterministicExtractor(reference_time=REF)
    phrases = (
        "FREE PIZZA? Maybe 👀",
        "might have free pizza",
        "hopefully free pizza",
        "Last semester's free food GBM was awesome!",
        "We had free pizza last week",
        "Our last meeting had free food",
        "Pizza fundraiser: $3/slice",
        "Pizza available, bring $5",
        "We'll have pizza for $4",
    )

    for phrase in phrases:
        candidate = PastedTextAdapter().ingest(
            f"Gator AI GBM tomorrow at 6 PM in Little 101. {phrase}",
            retrieved_at=REF,
        )
        event = extractor.extract(candidate)
        checked = EventVerifier().verify(event, now=REF)
        assert event.food.free_food is TriState.UNKNOWN, phrase
        assert event.food.free_food_evidence is EvidenceLevel.UNKNOWN, phrase
        assert checked.verification_status is VerificationStatus.REJECTED, phrase


def test_extractor_surfaces_restricted_free_food_claims_for_review():
    extractor = DeterministicExtractor(reference_time=REF)
    for phrase in (
        "Members get free pizza; non-members pay $8.",
        "Free pizza for the first 20 members.",
    ):
        event = extractor.extract(PastedTextAdapter().ingest(
            f"Gator AI GBM tomorrow at 6 PM in Little 101. {phrase}",
            retrieved_at=REF,
        ))
        checked = EventVerifier().verify(event, now=REF)
        assert event.food.free_food is TriState.UNKNOWN
        assert event.food.offer_restrictions is not None
        assert checked.verification_status is VerificationStatus.REVIEW_NEEDED


def test_extractor_distinguishes_cancellation_from_explicit_reinstatement():
    extractor = DeterministicExtractor(reference_time=REF)

    def status(sentence: str):
        candidate = PastedTextAdapter().ingest(
            f"Gator AI GBM tomorrow at 6 PM in Little 101. Free pizza. {sentence}",
            retrieved_at=REF,
        )
        return extractor.extract(candidate)

    for sentence in ("UPDATE: cancelled.", "This event was called off.", "This event will not take place."):
        event = status(sentence)
        assert event.status is EventStatus.CANCELLED
        assert event.status_evidence is EvidenceLevel.EXPLICIT

    for sentence in (
        "Last week's meeting was cancelled, but tonight we're back.",
        "This event is not cancelled.",
        "Cancelled? Nope, see you tonight.",
        "UPDATE 2: we're back on, new room.",
    ):
        event = status(sentence)
        assert event.status is EventStatus.SCHEDULED
        assert event.status_evidence is EvidenceLevel.EXPLICIT


def test_extractor_handles_dates_times_location_conflicts_and_status():
    extractor = DeterministicExtractor(reference_time=REF)
    candidates = JsonFixtureAdapter().ingest(FIXTURE, retrieved_at=REF)
    by_case = {c.metadata["case"]: extractor.extract(c) for c in candidates}
    assert by_case["tomorrow"].start_time.date().isoformat() == "2026-09-18"
    assert by_case["missing_end"].end_time is None
    assert by_case["missing_org"].organization is None
    assert by_case["ambiguous_location"].location.ambiguous
    assert by_case["cancelled"].status.value == "cancelled"
    assert "conflicting times" in by_case["conflicting_times"].conflicts
    assert by_case["explicit_dietary"].food.dietary.vegan is TriState.YES
    assert by_case["open_all"].attendance.open_to_all is TriState.YES
    assert by_case["members_only"].attendance.open_to_all is TriState.NO
    assert by_case["no_food"].food.description is None
    assert by_case["leftover_alert"].event_name == "Leftover food alert"
    assert by_case["low_info"].start_time is None
