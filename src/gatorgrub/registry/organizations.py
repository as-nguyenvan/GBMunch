from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class OrganizationRecord:
    canonical_id: str
    canonical_name: str
    source_organization_id: str
    url: str | None = None


class OrganizationRegistry:
    def __init__(self, records: list[OrganizationRecord]):
        self._by_source_id = {record.source_organization_id: record for record in records}

    @classmethod
    def load(cls, path: str | Path) -> OrganizationRegistry:
        records: list[OrganizationRecord] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row: dict[str, Any] = json.loads(line)
            gc = row.get("gatorconnect") or {}
            source_id = str(gc.get("organization_id") or "")
            if not source_id:
                continue
            records.append(OrganizationRecord(
                canonical_id=row["canonical_id"],
                canonical_name=row["canonical_name"],
                source_organization_id=source_id,
                url=gc.get("url"),
            ))
        return cls(records)

    def lookup(self, source_organization_id: str | int | None) -> OrganizationRecord | None:
        if source_organization_id is None:
            return None
        return self._by_source_id.get(str(source_organization_id))
