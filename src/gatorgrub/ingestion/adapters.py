from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gatorgrub.domain.models import RawEventCandidate, SourceType


class SourceAdapter(ABC):
    @abstractmethod
    def ingest(self, input_data: Any, *, retrieved_at: datetime | None = None) -> RawEventCandidate | list[RawEventCandidate]:
        """Normalize source input; downstream code only consumes RawEventCandidate."""


class PastedTextAdapter(SourceAdapter):
    def ingest(self, input_data: Any, *, retrieved_at: datetime | None = None) -> RawEventCandidate:
        if not isinstance(input_data, str) or not input_data.strip():
            raise ValueError("pasted input must be non-empty text")
        return RawEventCandidate(source_type=SourceType.PASTED_TEXT, raw_text=input_data.strip(),
                                 retrieved_at=retrieved_at or datetime.now(timezone.utc))


class JsonFixtureAdapter(SourceAdapter):
    @staticmethod
    def _posted_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("posted_at must be an ISO datetime") from error
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("posted_at must be a timezone-aware datetime")
        return value

    def ingest(self, input_data: Any, *, retrieved_at: datetime | None = None) -> list[RawEventCandidate]:
        if isinstance(input_data, (str, Path)):
            records = json.loads(Path(input_data).read_text(encoding="utf-8"))
        elif isinstance(input_data, list):
            records = input_data
        else:
            raise ValueError("fixture input must be a JSON path or list")
        now = retrieved_at or datetime.now(timezone.utc)
        envelope_fields = {"text", "source_url", "id", "posted_at"}
        return [RawEventCandidate(source_type=SourceType.JSON_FIXTURE, raw_text=row["text"], retrieved_at=now,
                                  source_url=row.get("source_url"), posted_at=self._posted_at(row.get("posted_at")),
                                  external_id=row.get("id"),
                                  metadata={k: v for k, v in row.items() if k not in envelope_fields})
                for row in records]
