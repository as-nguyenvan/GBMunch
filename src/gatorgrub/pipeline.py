from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from gatorgrub.deduplication.matcher import EventDeduplicator
from gatorgrub.domain.models import FoodEvent, RawEventCandidate
from gatorgrub.extraction.extractor import DeterministicExtractor, Extractor
from gatorgrub.ingestion.adapters import PastedTextAdapter
from gatorgrub.storage.repository import Repository
from gatorgrub.verification.verifier import EventVerifier


class ProcessingPipeline:
    """Source-neutral raw candidate to canonical repository workflow."""

    def __init__(self, repository: Repository, extractor: Extractor | None = None,
                 reference_time: datetime | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.repository = repository
        self.reference_time = reference_time
        self._clock = ((lambda: reference_time) if reference_time is not None
                       else clock or (lambda: datetime.now(timezone.utc)))
        self.extractor = extractor or DeterministicExtractor(reference_time=reference_time)
        self.verifier = EventVerifier()
        self.deduplicator = EventDeduplicator()

    def process(self, candidate: RawEventCandidate) -> FoodEvent:
        return self._process(candidate, now=self._clock())

    def _process(self, candidate: RawEventCandidate, *, now: datetime) -> FoodEvent:
        event = self.verifier.verify(self.extractor.extract(candidate), now=now)
        for existing in self.repository.list():
            if existing.event_id == event.event_id:
                return existing
            if self.deduplicator.compare(existing, event).is_duplicate:
                merged = self.deduplicator.merge(existing, event)
                merged.event_id = existing.event_id
                merged = self.verifier.verify(merged, now=now)
                return self.repository.update(merged)
        return self.repository.add(event)

    def ingest_text(self, text: str, source_url: str | None = None) -> FoodEvent:
        now = self._clock()
        candidate = PastedTextAdapter().ingest(text, retrieved_at=now)
        candidate.source_url = source_url
        return self._process(candidate, now=now)
