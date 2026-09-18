from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from gatorgrub.acquisition.gatorconnect import GatorConnectClient
from gatorgrub.ingestion.gatorconnect import GatorConnectEventAdapter
from gatorgrub.pipeline import ProcessingPipeline
from gatorgrub.registry.organizations import OrganizationRegistry
from gatorgrub.storage.repository import InMemoryEventRepository

# Repo-relative default: data/registry/organizations.jsonl (no machine-specific paths).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = _REPO_ROOT / "data" / "registry" / "organizations.jsonl"
FOOD_TERMS = (
    "free food", "free pizza", "food provided", "refreshments", "lunch", "dinner",
    "breakfast", "snacks", "pizza", "catered", "chick-fil-a", "publix", "coffee", "pastries",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch public GatorConnect events into GatorGrub")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--process", action="store_true")
    parser.add_argument("--from-fixture", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--save-raw", type=Path, default=None)
    args = parser.parse_args(argv)

    retrieved_at = datetime.now(timezone.utc)
    registry = OrganizationRegistry.load(args.registry) if args.registry.exists() else OrganizationRegistry([])
    adapter = GatorConnectEventAdapter(registry)

    if args.from_fixture:
        payload = json.loads(args.from_fixture.read_text(encoding="utf-8"))
        rows = payload["value"] if isinstance(payload, dict) and "value" in payload else payload
    else:
        rows = list(GatorConnectClient().iter_events(limit=args.limit))
    if args.save_raw:
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        args.save_raw.write_text(json.dumps({"@odata.count": len(rows), "value": rows}, indent=2), encoding="utf-8")

    candidates = adapter.ingest(rows, retrieved_at=retrieved_at)
    mapped = sum(1 for candidate in candidates if candidate.metadata.get("organization_mapped"))
    report = {
        "events_fetched": len(rows),
        "candidates_produced": len(candidates),
        "mapped_organizations": mapped,
        "unmapped_organizations": len(candidates) - mapped,
        "food_language_events": sum(
            1 for candidate in candidates
            if any(term in candidate.raw_text.lower() for term in FOOD_TERMS)
        ),
    }

    if args.process:
        repo = InMemoryEventRepository(clock=lambda: retrieved_at)
        pipeline = ProcessingPipeline(repo, clock=lambda: retrieved_at)
        for candidate in candidates:
            pipeline.process(candidate)
        statuses = Counter(event.verification_status.value for event in repo.list())
        explicit_events = [event for event in repo.list() if event.food.free_food.value == "yes"]
        report.update({
            "pipeline_canonical": len(repo.list()),
            "explicit_free_food": len(explicit_events),
            "verification": dict(statuses),
            "explicit_free_samples": [
                {
                    "event_id": event.event_id,
                    "external_id": event.sources[0].external_id if event.sources else None,
                    "organization": event.organization,
                    "event_name": event.event_name,
                    "verification_status": event.verification_status.value,
                }
                for event in explicit_events[:20]
            ],
        })

    print(json.dumps(report, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
