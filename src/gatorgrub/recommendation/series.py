from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict

from gatorgrub.domain.models import FoodEvent
from gatorgrub.verification.verifier import is_publishable


class SeriesFeedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    series_key: str
    organization_id: str | None = None
    organization_name: str | None = None
    title: str
    food_summary: str | None = None
    next_event_id: str
    next_start_time: datetime
    location: str | None = None
    occurrence_count: int
    upcoming_dates: list[datetime]


def _normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _org_key(event: FoodEvent) -> str:
    if event.canonical_organization_id:
        return f"id:{event.canonical_organization_id}"
    return f"name:{_normalize(event.organization)}"


def _location_key(event: FoodEvent) -> str:
    if event.location.building and event.location.room:
        return _normalize(f"{event.location.building} {event.location.room}")
    return _normalize(event.location.raw_text or event.location.building)


def _locations_compatible(left: FoodEvent, right: FoodEvent) -> bool:
    a, b = _location_key(left), _location_key(right)
    if not a or not b:
        return True
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def _series_key(event: FoodEvent) -> tuple[str, str, str]:
    return (_org_key(event), _normalize(event.event_name), _location_key(event) or "*")


def collapse_event_series(events: list[FoodEvent], *, now: datetime) -> list[SeriesFeedItem]:
    upcoming = [event for event in events if event.start_time and event.start_time >= now and is_publishable(event)]
    upcoming.sort(key=lambda event: (event.start_time, event.event_id))
    buckets: dict[tuple[str, str, str], list[FoodEvent]] = {}
    for event in upcoming:
        key = _series_key(event)
        existing = buckets.get(key)
        if existing and not _locations_compatible(existing[0], event):
            buckets[(*key[:2], event.event_id)] = [event]
            continue
        buckets.setdefault(key, []).append(event)

    items: list[SeriesFeedItem] = []
    for key, group in buckets.items():
        group.sort(key=lambda event: (event.start_time, event.event_id))
        first = group[0]
        items.append(SeriesFeedItem(
            series_key="|".join(key),
            organization_id=first.canonical_organization_id,
            organization_name=first.organization,
            title=first.event_name,
            food_summary=first.food.description,
            next_event_id=first.event_id,
            next_start_time=first.start_time,
            location=first.location.raw_text,
            occurrence_count=len(group),
            upcoming_dates=[event.start_time for event in group],
        ))
    return sorted(items, key=lambda item: (item.next_start_time, item.series_key))
