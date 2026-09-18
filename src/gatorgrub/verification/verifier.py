from __future__ import annotations

from datetime import datetime, timedelta

from gatorgrub.domain.models import (
    EffectiveEventInterval, EndTimeBasis, EventConfidence, EventStatus, FieldConfidence,
    FoodEvent, TriState, VerificationStatus,
)


PUBLICATION_STATUSES = frozenset({VerificationStatus.TRUSTED, VerificationStatus.LIKELY})


def is_publishable(event: FoodEvent) -> bool:
    return event.verification_status in PUBLICATION_STATUSES


def event_interval(event: FoodEvent, *, default_duration=None) -> EffectiveEventInterval | None:
    if event.start_time is None:
        return None
    duration = default_duration or EventVerifier.DEFAULT_EVENT_DURATION
    if event.end_time is not None:
        return EffectiveEventInterval(
            start_time=event.start_time,
            effective_end_time=event.end_time,
            end_time_basis=EndTimeBasis.EXPLICIT,
        )
    return EffectiveEventInterval(
        start_time=event.start_time,
        effective_end_time=event.start_time + duration,
        end_time_basis=EndTimeBasis.HEURISTIC_DEFAULT,
    )


class EventVerifier:
    """Deterministic publication checks with inspectable field reasons."""

    DEFAULT_EVENT_DURATION = timedelta(hours=2)

    def verify(self, event: FoodEvent, *, now: datetime) -> FoodEvent:
        fields: dict[str, FieldConfidence] = {}
        reasons: list[str] = []
        fields["date"] = FieldConfidence(value=1.0 if event.start_time else 0.0,
                                           reason="resolved event date" if event.start_time else "unresolved event date")
        fields["time"] = FieldConfidence(value=1.0 if event.start_time else 0.0,
                                           reason="resolved start time" if event.start_time else "unresolved start time")
        if event.location.ambiguous:
            fields["location"] = FieldConfidence(value=0.35, reason="ambiguous location")
            reasons.append("ambiguous location")
        elif event.location.raw_text:
            fields["location"] = FieldConfidence(value=1.0, reason="specific location")
        else:
            fields["location"] = FieldConfidence(value=0.0, reason="missing location")
        explicit_free = event.food.free_food is TriState.YES
        fields["food"] = FieldConfidence(value=1.0 if explicit_free else 0.0,
                                           reason="explicit free-food evidence" if explicit_free else "no explicit free-food evidence")
        fields["attendance"] = FieldConfidence(value=1.0 if event.attendance.open_to_all is not TriState.UNKNOWN else 0.2,
                                                 reason="explicit attendance terms" if event.attendance.open_to_all is not TriState.UNKNOWN else "attendance unknown")
        source_times = [source.posted_at or source.retrieved_at for source in event.sources]
        stale_source = bool(source_times) and all((now - source_time).days > 14 for source_time in source_times)
        fields["source_freshness"] = FieldConfidence(value=0.2 if stale_source else 1.0,
                                                      reason="stale source" if stale_source else "recent source")
        if stale_source:
            reasons.append("stale source")
        overall = sum(f.value for f in fields.values()) / len(fields)
        if event.status is EventStatus.CANCELLED:
            status = VerificationStatus.CANCELLED
            reasons.append("source says event is cancelled")
        elif (interval := event_interval(event)) and interval.effective_end_time <= now:
            if interval.end_time_basis is EndTimeBasis.EXPLICIT:
                status = VerificationStatus.EXPIRED
                event.status = EventStatus.EXPIRED
                reasons.append("event has ended")
            else:
                status = VerificationStatus.REVIEW_NEEDED
                reasons.append("unknown end time; assumed window elapsed")
        elif not event.start_time:
            status = VerificationStatus.REJECTED
            reasons.append("date/time unresolved")
        elif event.food.offer_restrictions:
            status = VerificationStatus.REVIEW_NEEDED
            reasons.append("restricted free-food offer")
        elif not explicit_free:
            status = VerificationStatus.REJECTED
            reasons.append("no evidence of free food")
        elif event.conflicts:
            status = VerificationStatus.REVIEW_NEEDED
            reasons.extend(event.conflicts)
        elif stale_source:
            status = VerificationStatus.REVIEW_NEEDED
        elif event.location.ambiguous or not event.location.raw_text:
            status = VerificationStatus.REVIEW_NEEDED
        elif overall >= 0.9:
            status = VerificationStatus.TRUSTED
        elif overall >= 0.65:
            status = VerificationStatus.LIKELY
        else:
            status = VerificationStatus.REVIEW_NEEDED
        event.confidence = EventConfidence(
            overall=round(overall, 3), date=fields["date"].value, time=fields["time"].value,
            location=fields["location"].value, food=fields["food"].value,
            attendance=fields["attendance"].value, fields=fields, reasons=reasons,
        )
        event.verification_status = status
        return event
