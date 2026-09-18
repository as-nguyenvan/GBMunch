from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from typing import Any

from gatorgrub.domain.models import RawEventCandidate, SourceType
from gatorgrub.ingestion.adapters import SourceAdapter
from gatorgrub.registry.organizations import OrganizationRegistry

EVENT_URL = "https://gatorconnect.ufl.edu/event/{event_id}"


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _raw_text(payload: dict[str, Any]) -> str:
    start = payload.get("startsOn") or "unknown start"
    end = payload.get("endsOn") or "unknown end"
    location = payload.get("location") or "unknown location"
    org = payload.get("organizationName") or "Unknown organization"
    name = payload.get("name") or "Untitled event"
    description = _strip_html(payload.get("description"))
    status = payload.get("status") or ""
    return (
        f"{org} presents {name}. "
        f"Starts {start}. Ends {end}. Location: {location}. "
        f"{description} {status}"
    ).strip()


class GatorConnectEventAdapter(SourceAdapter):
    def __init__(self, registry: OrganizationRegistry | None = None):
        self.registry = registry

    def ingest(self, input_data: Any, *, retrieved_at: datetime | None = None) -> list[RawEventCandidate]:
        if isinstance(input_data, dict) and "value" in input_data:
            rows = input_data["value"]
        elif isinstance(input_data, list):
            rows = input_data
        else:
            raise ValueError("GatorConnect adapter expects a list of events or a search payload")
        now = retrieved_at or datetime.now(timezone.utc)
        return [self._candidate(row, now) for row in rows]

    def _candidate(self, row: dict[str, Any], retrieved_at: datetime) -> RawEventCandidate:
        event_id = str(row.get("id") or "")
        source_org_id = None if row.get("organizationId") is None else str(row.get("organizationId"))
        mapped = self.registry.lookup(source_org_id) if self.registry else None
        return RawEventCandidate(
            source_type=SourceType.GATORCONNECT,
            raw_text=_raw_text(row),
            retrieved_at=retrieved_at,
            source_url=EVENT_URL.format(event_id=event_id),
            posted_at=None,
            external_id=event_id,
            metadata={
                "event_name": row.get("name"),
                "organization_name": row.get("organizationName"),
                "source_organization_id": source_org_id,
                "canonical_organization_id": mapped.canonical_id if mapped else None,
                "organization_mapped": mapped is not None,
                "structured_start": _parse_datetime(row.get("startsOn")),
                "structured_end": _parse_datetime(row.get("endsOn")),
                "structured_location": row.get("location"),
                "gatorconnect_status": row.get("status"),
                "replay": json.loads(json.dumps(row, default=str)),
            },
        )
