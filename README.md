# GBMunch

UF free-food event discovery prototype (**pre-acquisition baseline**).

This freeze includes:
- validated offline backend (Hermes repair pass)
- canonical GatorConnect organization registry (emails redacted)
- public event-source registry seed

Not production-ready. No live event scraping in this baseline.

## Backend prototype


GatorGrub turns heterogeneous campus announcements into a conservative, searchable free-food event feed. This prototype is fully offline: it uses synthetic UF-style fixtures, deterministic extraction/verification/deduplication/ranking, in-memory persistence, and a thin FastAPI boundary.

## Setup

Requires Python 3.11+.

```bash
cd GBMunch
python3 -m venv .venv
.venv/bin/pip install -e '.[test,api]'
.venv/bin/pytest -q
.venv/bin/python demo/offline_demo.py
.venv/bin/uvicorn gatorgrub.api.app:app --reload
```

Interactive API documentation is then at `http://127.0.0.1:8000/docs`.

## Architecture

```text
future/manual source -> SourceAdapter -> RawEventCandidate
                                      -> Extractor protocol
                                      -> EventVerifier
                                      -> EventDeduplicator
                                      -> Repository protocol
                                      -> deterministic rank_events
                                      -> FastAPI
```

Dependencies point inward. `gatorgrub.domain` imports no FastAPI, storage, source, or provider code. Core processing has no FastAPI dependency. The deterministic extractor has no model/provider dependency and can be replaced through the `Extractor` protocol. Unknown food cost, diet, eligibility, allergens, and location facts remain unknown.

Key modules:

- `domain/models.py`: Pydantic contracts, enums, explicit evidence and confidence
- `ingestion/adapters.py`: source adapter boundary and pasted text/JSON adapters
- `extraction/extractor.py`: provider-neutral protocol and conservative fixture parser
- `verification/verifier.py`: expiry, cancellation, conflicts, staleness, confidence, publication state
- `deduplication/matcher.py`: explainable matching and provenance-preserving merge
- `recommendation/ranker.py`: deterministic filters, score components, explanations
- `storage/repository.py`: repository protocol and in-memory implementation
- `pipeline.py`: source-neutral end-to-end processing service
- `api/app.py`: HTTP boundary only

## Add a future acquisition source

Do not modify extraction, verification, deduplication, storage, or ranking. Implement only the adapter and emit `RawEventCandidate`:

```python
from datetime import datetime, timezone
from gatorgrub.domain.models import RawEventCandidate, SourceType
from gatorgrub.ingestion.adapters import SourceAdapter

class UfCalendarAdapter(SourceAdapter):
    def ingest(self, input_data, *, retrieved_at=None):
        # Acquisition/parsing of the source envelope belongs here.
        return RawEventCandidate(
            source_type=SourceType.OTHER,
            source_url=input_data["url"],
            raw_text=input_data["announcement"],
            retrieved_at=retrieved_at or datetime.now(timezone.utc),
            external_id=input_data.get("id"),
            metadata={"source_name": "uf_calendar"},
        )
```

Pass the result to the unchanged pipeline:

```python
candidate = UfCalendarAdapter().ingest(payload)
event = ProcessingPipeline(repository).process(candidate)
```

The adapter must not return a source-specific downstream model. The extractor boundary is similarly replaceable: implement `extract(candidate: RawEventCandidate) -> FoodEvent` and inject it into `ProcessingPipeline`. For live operation, pass a callable such as `ProcessingPipeline(repository, clock=clock)`; it is evaluated for every `process` or `ingest_text` call. The optional `reference_time` takes precedence over `clock` and intentionally freezes extraction and verification for deterministic tests and the offline demo.

## API examples

Health and feed:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/events
curl http://127.0.0.1:8000/events/evt_abc123
```

`GET /events` is the public feed and returns only `trusted` and `likely` events. Other verification states remain stored and can still be inspected by ID. List, detail, search, ingest/update responses, and availability confirmations all apply verification against the repository's current clock, so an ended event cannot retain a stale trusted response.

Ingest pasted text:

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H 'content-type: application/json' \
  -d '{"text":"Gator AI GBM September 18, 2026 at 6 PM in Little 101. FREE PIZZA. Open to all!"}'
```

Representative response (IDs are deterministic from source type and raw text):

```json
{
  "event_id": "evt_...",
  "organization": "Gator AI",
  "event_name": "General Body Meeting",
  "start_time": "2026-09-18T18:00:00-04:00",
  "end_time": null,
  "food": {
    "free_food": "yes",
    "free_food_evidence": "explicit",
    "description": "pizza",
    "description_evidence": "explicit",
    "meal_level": "meal",
    "dietary": {"vegetarian":"unknown","vegan":"unknown","halal":"unknown","kosher":"unknown","allergens":null}
  },
  "verification_status": "trusted"
}
```

Search:

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{
    "available_start":"2026-09-18T17:10:00-04:00",
    "available_end":"2026-09-18T18:45:00-04:00",
    "require_free":true,
    "dietary_preferences":["vegetarian"],
    "meal_preference":"meal",
    "origin":"Marston Science Library",
    "max_walk_minutes":15
  }'
```

Search responses are arrays of `{event, score, components, explanation}`. An unknown dietary field receives a penalty and the explanation says it is unknown; it is never described as suitable.
Supported `dietary_preferences` values are `vegetarian`, `vegan`, `halal`, and `kosher`; other names receive a `422` response.

Availability confirmation:

```bash
curl -X POST http://127.0.0.1:8000/confirm \
  -H 'content-type: application/json' \
  -d '{"event_id":"evt_abc123","availability":"plenty"}'
```

## Fixture corpus and demo

`tests/fixtures/announcements.json` and `demo/sample_events.json` contain 20 synthetic announcements covering explicit free pizza, food without a free claim, emoji ambiguity, generic food, tomorrow, missing end/organization, ambiguous location, cancellation, past events, conflicting times, dietary evidence/absence, open/members-only attendance, duplicates, no food, leftovers, and low-information text.

The demo fixes the reference time at noon on September 17, 2026, so it remains stable. It runs JSON ingestion → extraction → verification → deduplication → in-memory storage → the requested 5:10–6:45 PM vegetarian-preferred meal search from Marston with a 15-minute proximity placeholder.

## Verification states and uncertainty

- `trusted`, `likely`, `review_needed`, `rejected`, `expired`, `cancelled`
- Field confidence values include inspectable reasons.
- Events expire only at an **explicit** end time. Unknown `end_time` remains canonical `null`. Verification and ranking may use a labeled two-hour heuristic interval (`EndTimeBasis.HEURISTIC_DEFAULT`) without writing that guess into the event. After the assumed window elapses, unknown-end events become `review_needed`, not confidently `expired`.
- Search uses interval overlap and requires at least `min_useful_minutes` of overlap (default 15). Set `0` to restore raw overlap.
- Hedged, historical, paid, or restricted free-food language stays unknown; restricted offers require review rather than an unconditional `free_food=yes`.
- Event status is recency- and evidence-aware: a newer explicit reinstatement overrides a stale cancellation; equal-timestamp status disagreement requires review.
- Contradictory explicit rooms/buildings block automatic merge unless a shared source identity is present.
- Unresolved dates and missing free-food evidence reject; conflicts, ambiguous locations, and sources older than 14 days require review.
- Naive event/search datetimes are interpreted as UF local time (`America/New_York`). Explicit aware offsets are preserved. Acquisition timestamps must be aware.
- JSON fixture `posted_at` accepts an ISO timestamp or timezone-aware `datetime`; it is retained as source provenance and used for staleness checks.

## Non-goals

No live scraping/acquisition, frontend, authentication, Docker, Redis, queues, microservices, cloud deployment, push notifications, database/ORM, geocoding, maps, recommendation ML, or LLM provider integration. Proximity is deliberately a labeled fixed scoring placeholder, not a distance claim. The fixture extractor is intentionally narrow and not a general natural-language date parser. In-memory state is lost on process restart.
