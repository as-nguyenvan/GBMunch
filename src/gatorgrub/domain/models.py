from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UF_TZ = ZoneInfo("America/New_York")


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class VerificationStatus(StrEnum):
    TRUSTED = "trusted"
    LIKELY = "likely"
    REVIEW_NEEDED = "review_needed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class MealLevel(StrEnum):
    MEAL = "meal"
    SNACK = "snack"
    UNKNOWN = "unknown"


class AvailabilityStatus(StrEnum):
    PLENTY = "plenty"
    RUNNING_LOW = "running_low"
    GONE = "gone"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    PASTED_TEXT = "pasted_text"
    JSON_FIXTURE = "json_fixture"
    USER_SUBMISSION = "user_submission"
    GATORCONNECT = "gatorconnect"
    INSTAGRAM = "instagram"
    OTHER = "other"


class TriState(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class EvidenceLevel(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


def _localize_naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UF_TZ)
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class EventLocation(StrictModel):
    building: str | None = None
    room: str | None = None
    raw_text: str | None = None
    ambiguous: bool = False


class DietaryInfo(StrictModel):
    vegetarian: TriState = TriState.UNKNOWN
    vegan: TriState = TriState.UNKNOWN
    halal: TriState = TriState.UNKNOWN
    kosher: TriState = TriState.UNKNOWN
    allergens: list[str] | None = None


class EndTimeBasis(StrEnum):
    EXPLICIT = "explicit"
    HEURISTIC_DEFAULT = "heuristic_default"


class EffectiveEventInterval(StrictModel):
    start_time: datetime
    effective_end_time: datetime
    end_time_basis: EndTimeBasis


class FoodInfo(StrictModel):
    free_food: TriState = TriState.UNKNOWN
    free_food_evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    description: str | None = None
    description_evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    meal_level: MealLevel = MealLevel.UNKNOWN
    dietary: DietaryInfo = Field(default_factory=DietaryInfo)
    offer_restrictions: str | None = None


class AttendanceInfo(StrictModel):
    open_to_all: TriState = TriState.UNKNOWN
    evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    requirements: str | None = None


class EventSource(StrictModel):
    type: SourceType
    url: str | None = None
    posted_at: datetime | None = None
    retrieved_at: datetime
    raw_text: str
    external_id: str | None = None

    _posted_aware = field_validator("posted_at", mode="after")(_localize_naive)

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value


class RawEventCandidate(StrictModel):
    source_type: SourceType
    raw_text: str = Field(min_length=1)
    retrieved_at: datetime
    source_url: str | None = None
    posted_at: datetime | None = None
    external_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    _posted_aware = field_validator("posted_at", mode="after")(_localize_naive)

    def to_source(self) -> EventSource:
        return EventSource(type=self.source_type, url=self.source_url, posted_at=self.posted_at,
                           retrieved_at=self.retrieved_at, raw_text=self.raw_text, external_id=self.external_id)


class FieldConfidence(StrictModel):
    value: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = "unknown"


class EventConfidence(StrictModel):
    overall: float = Field(default=0.0, ge=0.0, le=1.0)
    date: float = Field(default=0.0, ge=0.0, le=1.0)
    time: float = Field(default=0.0, ge=0.0, le=1.0)
    location: float = Field(default=0.0, ge=0.0, le=1.0)
    food: float = Field(default=0.0, ge=0.0, le=1.0)
    attendance: float = Field(default=0.0, ge=0.0, le=1.0)
    fields: dict[str, FieldConfidence] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class FoodEvent(StrictModel):
    event_id: str
    organization: str | None = None
    event_name: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: EventLocation = Field(default_factory=EventLocation)
    food: FoodInfo = Field(default_factory=FoodInfo)
    attendance: AttendanceInfo = Field(default_factory=AttendanceInfo)
    sources: list[EventSource] = Field(default_factory=list)
    confidence: EventConfidence = Field(default_factory=EventConfidence)
    status: EventStatus = EventStatus.SCHEDULED
    status_evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    verification_status: VerificationStatus = VerificationStatus.REVIEW_NEEDED
    availability: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    availability_confirmed_at: datetime | None = None
    conflicts: list[str] = Field(default_factory=list)
    canonical_organization_id: str | None = None
    source_organization_id: str | None = None

    _times_local = field_validator("start_time", "end_time", "availability_confirmed_at", mode="after")(_localize_naive)

    @model_validator(mode="after")
    def end_not_before_start(self) -> FoodEvent:
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time cannot be before start_time")
        return self


class SearchPreferences(StrictModel):
    available_start: datetime
    available_end: datetime
    require_free: bool = True
    dietary_preferences: list[Literal["vegetarian", "vegan", "halal", "kosher"]] = Field(default_factory=list)
    meal_preference: MealLevel | None = None
    origin: str | None = None
    max_walk_minutes: int | None = Field(default=None, ge=0)
    min_useful_minutes: int = Field(default=15, ge=0)

    _times_local = field_validator("available_start", "available_end", mode="after")(_localize_naive)

    @model_validator(mode="after")
    def valid_window(self) -> SearchPreferences:
        if self.available_end <= self.available_start:
            raise ValueError("available_end must be after available_start")
        return self
