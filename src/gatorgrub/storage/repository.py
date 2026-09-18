from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol

from gatorgrub.deduplication.matcher import EventDeduplicator
from gatorgrub.domain.models import EventStatus, FoodEvent, SearchPreferences, VerificationStatus
from gatorgrub.recommendation.ranker import RankedEvent, rank_events
from gatorgrub.verification.verifier import EventVerifier


class Repository(Protocol):
    def add(self, event: FoodEvent) -> FoodEvent: ...
    def update(self, event: FoodEvent) -> FoodEvent: ...
    def list(self) -> list[FoodEvent]: ...
    def get(self, event_id: str) -> FoodEvent | None: ...
    def search(self, preferences: SearchPreferences) -> list[RankedEvent]: ...
    def merge(self, left_id: str, right_id: str) -> FoodEvent: ...


class InMemoryEventRepository:
    def __init__(self, deduplicator: EventDeduplicator | None = None,
                 clock: Callable[[], datetime] | None = None):
        self._events: dict[str, FoodEvent] = {}
        self._deduplicator = deduplicator or EventDeduplicator()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._verifier = EventVerifier()

    def add(self, event: FoodEvent) -> FoodEvent:
        if event.event_id in self._events:
            raise ValueError(f"event {event.event_id} already exists")
        self._events[event.event_id] = event.model_copy(deep=True)
        return self.get(event.event_id)  # type: ignore[return-value]

    def update(self, event: FoodEvent) -> FoodEvent:
        if event.event_id not in self._events:
            raise KeyError(event.event_id)
        stored = event.model_copy(deep=True)
        canonical = self._events[event.event_id]
        if (stored.verification_status is VerificationStatus.EXPIRED
                and canonical.status is EventStatus.SCHEDULED):
            stored.status = canonical.status
            stored.verification_status = canonical.verification_status
            stored.confidence = canonical.confidence.model_copy(deep=True)
        self._events[event.event_id] = stored
        return self.get(event.event_id)  # type: ignore[return-value]

    def _effective(self, event: FoodEvent, *, now: datetime) -> FoodEvent:
        return self._verifier.verify(event.model_copy(deep=True), now=now)

    def list(self) -> list[FoodEvent]:
        now = self._clock()
        effective = [self._effective(event, now=now) for event in self._events.values()]

        def key(event: FoodEvent):
            return (event.start_time is None, event.start_time.isoformat() if event.start_time else "", event.event_id)
        return sorted(effective, key=key)

    def get(self, event_id: str) -> FoodEvent | None:
        event = self._events.get(event_id)
        return self._effective(event, now=self._clock()) if event else None

    def search(self, preferences: SearchPreferences) -> list[RankedEvent]:
        return rank_events(self.list(), preferences)

    def merge(self, left_id: str, right_id: str) -> FoodEvent:
        left = self._events.get(left_id)
        right = self._events.get(right_id)
        if left is None or right is None:
            raise KeyError(left_id if left is None else right_id)
        merged = self._deduplicator.merge(
            left.model_copy(deep=True), right.model_copy(deep=True),
        )
        del self._events[left_id]
        del self._events[right_id]
        self._events[merged.event_id] = merged.model_copy(deep=True)
        return self.get(merged.event_id)  # type: ignore[return-value]
