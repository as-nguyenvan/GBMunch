from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints

from gatorgrub.domain.models import AvailabilityStatus, FoodEvent, SearchPreferences
from gatorgrub.pipeline import ProcessingPipeline
from gatorgrub.recommendation.ranker import RankedEvent
from gatorgrub.storage.repository import InMemoryEventRepository, Repository
from gatorgrub.verification.verifier import is_publishable


class IngestRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"text": "Gator AI GBM September 18, 2026 at 6 PM in Little 101. FREE PIZZA"}})
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_url: str | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"event_id": "evt_abc123", "availability": "plenty"}})
    event_id: str
    availability: AvailabilityStatus


def create_app(repository: Repository | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    repo = repository or InMemoryEventRepository(clock=clock)
    pipeline = ProcessingPipeline(repo, clock=clock)
    app = FastAPI(title="GatorGrub API", version="0.1.0",
                  description="Offline, source-agnostic free-food event prototype")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/events", response_model=list[FoodEvent])
    def events() -> list[FoodEvent]:
        return [event for event in repo.list() if is_publishable(event)]

    @app.get("/events/{event_id}", response_model=FoodEvent)
    def event(event_id: str) -> FoodEvent:
        found = repo.get(event_id)
        if found is None:
            raise HTTPException(status_code=404, detail="event not found")
        return found

    @app.post("/ingest", response_model=FoodEvent, status_code=status.HTTP_201_CREATED)
    def ingest(request: IngestRequest) -> FoodEvent:
        return pipeline.ingest_text(request.text, request.source_url)

    @app.post("/search", response_model=list[RankedEvent])
    def search(preferences: SearchPreferences) -> list[RankedEvent]:
        return repo.search(preferences)

    @app.post("/confirm", response_model=FoodEvent)
    def confirm(request: ConfirmRequest) -> FoodEvent:
        found = repo.get(request.event_id)
        if found is None:
            raise HTTPException(status_code=404, detail="event not found")
        found.availability = request.availability
        found.availability_confirmed_at = clock()
        return repo.update(found)

    return app


app = create_app()
