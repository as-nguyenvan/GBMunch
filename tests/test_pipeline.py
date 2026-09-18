from datetime import datetime
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import (
    EvidenceLevel, EventStatus, RawEventCandidate, SourceType, VerificationStatus,
)
from gatorgrub.pipeline import ProcessingPipeline
from gatorgrub.storage.repository import InMemoryEventRepository

TZ = ZoneInfo("America/New_York")


class FutureSourceAdapter:
    def ingest(self, input_data, *, retrieved_at=None):
        return RawEventCandidate(source_type=SourceType.OTHER, raw_text=input_data,
                                 retrieved_at=retrieved_at or datetime(2026, 9, 17, 12, tzinfo=TZ))


def test_pipeline_reverifies_a_merged_cancellation_before_updating_repository():
    repo = InMemoryEventRepository()
    pipeline = ProcessingPipeline(repo, reference_time=datetime(2026, 9, 17, 12, tzinfo=TZ))
    first = FutureSourceAdapter().ingest(
        "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.")
    cancellation = FutureSourceAdapter().ingest(
        "UPDATE: Gator AI GBM September 18, 2026 at 6 PM in Little 101 is cancelled. Free pizza.")

    original = pipeline.process(first)
    merged = pipeline.process(cancellation)

    assert merged.event_id == original.event_id
    assert merged.verification_status is VerificationStatus.CANCELLED
    assert repo.get(original.event_id).verification_status is VerificationStatus.CANCELLED


def test_status_merge_uses_explicit_evidence_recency_and_is_order_independent():
    now = datetime(2026, 9, 17, 12, tzinfo=TZ)
    old = datetime(2026, 8, 1, 12, tzinfo=TZ)
    recent = datetime(2026, 9, 17, 11, tzinfo=TZ)

    def candidate(text: str, observed: datetime):
        return RawEventCandidate(
            source_type=SourceType.OTHER,
            raw_text=text,
            retrieved_at=now,
            posted_at=observed,
            external_id="gator-ai-gbm-2",
        )

    cancelled = candidate(
        "UPDATE: Gator AI GBM September 18, 2026 at 6 PM in Little 101 is cancelled. Free pizza.",
        old,
    )
    reinstated = candidate(
        "UPDATE 2: Gator AI GBM September 18, 2026 at 6 PM is back on in Little 109. Free pizza.",
        recent,
    )

    normalized = []
    for first, second in ((cancelled, reinstated), (reinstated, cancelled)):
        repo = InMemoryEventRepository(clock=lambda: now)
        merged = ProcessingPipeline(repo, reference_time=now).process(first)
        merged = ProcessingPipeline(repo, reference_time=now).process(second)
        assert merged.status is EventStatus.SCHEDULED
        assert merged.status_evidence is EvidenceLevel.EXPLICIT
        assert merged.verification_status is not VerificationStatus.CANCELLED
        assert len(merged.sources) == 2
        normalized.append(merged.model_copy(update={"event_id": "canonical"}).model_dump())

    assert normalized[0] == normalized[1]


def test_newer_cancellation_overrides_older_active_evidence():
    now = datetime(2026, 9, 17, 12, tzinfo=TZ)
    active = RawEventCandidate(
        source_type=SourceType.OTHER,
        raw_text="Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.",
        retrieved_at=now,
        posted_at=datetime(2026, 9, 16, 12, tzinfo=TZ),
        external_id="gator-ai-gbm-2",
    )
    cancellation = active.model_copy(update={
        "raw_text": "UPDATE: Gator AI GBM September 18, 2026 at 6 PM in Little 101 is cancelled. Free pizza.",
        "posted_at": datetime(2026, 9, 17, 11, tzinfo=TZ),
    })
    repo = InMemoryEventRepository(clock=lambda: now)
    pipeline = ProcessingPipeline(repo, reference_time=now)

    pipeline.process(active)
    merged = pipeline.process(cancellation)

    assert merged.status is EventStatus.CANCELLED
    assert merged.verification_status is VerificationStatus.CANCELLED


def test_equal_timestamp_status_disagreement_requires_review():
    now = datetime(2026, 9, 17, 12, tzinfo=TZ)
    observed = datetime(2026, 9, 17, 11, tzinfo=TZ)
    texts = (
        "UPDATE: Gator AI GBM September 18, 2026 at 6 PM in Little 101 is cancelled. Free pizza.",
        "UPDATE 2: Gator AI GBM September 18, 2026 at 6 PM in Little 101 is back on. Free pizza.",
    )
    candidates = [RawEventCandidate(
        source_type=SourceType.OTHER,
        raw_text=text,
        retrieved_at=now,
        posted_at=observed,
        external_id="gator-ai-gbm-2",
    ) for text in texts]

    outcomes = []
    for first, second in (candidates, tuple(reversed(candidates))):
        repo = InMemoryEventRepository(clock=lambda: now)
        pipeline = ProcessingPipeline(repo, reference_time=now)
        pipeline.process(first)
        outcomes.append(pipeline.process(second))

    assert all(event.status is EventStatus.SCHEDULED for event in outcomes)
    assert all(event.verification_status is VerificationStatus.REVIEW_NEEDED for event in outcomes)
    assert all("conflicting event status" in event.conflicts for event in outcomes)


def test_future_adapter_only_needs_to_emit_raw_candidate_for_existing_pipeline():
    repo = InMemoryEventRepository()
    candidate = FutureSourceAdapter().ingest(
        "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.")
    event = ProcessingPipeline(repo, reference_time=datetime(2026, 9, 17, 12, tzinfo=TZ)).process(candidate)
    assert event.sources[0].type is SourceType.OTHER
    assert repo.get(event.event_id) is not None


def test_pipeline_merge_is_order_independent_and_reverifies_disagreements():
    now = datetime(2026, 9, 17, 12, tzinfo=TZ)
    pizza = FutureSourceAdapter().ingest(
        "Gator AI GBM September 18, 2026 at 6 PM in Little 101. Free pizza.",
        retrieved_at=now,
    )
    tacos = FutureSourceAdapter().ingest(
        "Gator AI GBM September 18, 2026 at 6:10 PM in Little 101. Free tacos.",
        retrieved_at=now,
    )

    results = []
    for first, second in ((pizza, tacos), (tacos, pizza)):
        repo = InMemoryEventRepository(clock=lambda: now)
        pipeline = ProcessingPipeline(repo, reference_time=now)
        original = pipeline.process(first)
        merged = pipeline.process(second)
        assert merged.event_id == original.event_id
        results.append(merged.model_copy(update={"event_id": "canonical"}).model_dump())

    assert results[0] == results[1]
    assert results[0]["verification_status"] is VerificationStatus.REVIEW_NEEDED
    assert results[0]["conflicts"] >= ["conflicting food descriptions", "conflicting start times"]


def test_pipeline_clock_advances_between_ingests_for_relative_dates_and_retrieval():
    current = [datetime(2026, 9, 17, 12, tzinfo=TZ)]
    repo = InMemoryEventRepository(clock=lambda: current[0])
    pipeline = ProcessingPipeline(repo, clock=lambda: current[0])

    first = pipeline.ingest_text(
        "Gator AI GBM tomorrow at 6 PM in Little 101. Free pizza."
    )
    current[0] = datetime(2026, 9, 18, 12, tzinfo=TZ)
    second = pipeline.ingest_text(
        "ACM GBM tomorrow at 7 PM in CSE E221. Free tacos."
    )

    assert first.start_time.date().isoformat() == "2026-09-18"
    assert first.sources[0].retrieved_at.date().isoformat() == "2026-09-17"
    assert second.start_time.date().isoformat() == "2026-09-19"
    assert second.sources[0].retrieved_at.date().isoformat() == "2026-09-18"
