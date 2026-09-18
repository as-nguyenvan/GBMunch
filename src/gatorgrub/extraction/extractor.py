from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from gatorgrub.domain.models import (
    AttendanceInfo, DietaryInfo, EvidenceLevel, EventLocation, EventStatus, FoodEvent,
    FoodInfo, MealLevel, RawEventCandidate, TriState,
)

TZ = ZoneInfo("America/New_York")


class Extractor(Protocol):
    def extract(self, candidate: RawEventCandidate) -> FoodEvent: ...


class DeterministicExtractor:
    """Conservative fixture-grade parser; replace through the Extractor protocol."""

    _orgs = ["Gator AI", "ACM", "Women in CS", "SHPE", "Gator Robotics", "History Club",
             "Data Science", "Vegan Club", "ISA", "Astronomy", "Pre-Law", "Math Society"]
    _foods = ["Chick-fil-A", "sandwiches", "burritos", "bagels", "cookies", "snacks", "pizza", "tacos", "subs", "pasta",
              "breakfast", "lunch", "dinner"]

    def __init__(self, reference_time: datetime | None = None):
        self.reference_time = reference_time

    def extract(self, candidate: RawEventCandidate) -> FoodEvent:
        text = candidate.raw_text
        lower = text.lower()
        ref = self.reference_time or candidate.retrieved_at.astimezone(TZ)
        event_date = self._date(text, ref)
        times = self._times(text)
        conflicts = ["conflicting times"] if "correction:" in lower and len(times) > 1 else []
        start = datetime.combine(event_date, times[-1 if conflicts else 0], TZ) if event_date and times else None
        end = datetime.combine(event_date, times[1], TZ) if event_date and len(times) > 1 and not conflicts and ("-" in text or " to " in lower) else None
        organization = next((org for org in self._orgs if org.lower() in lower), None)
        description, evidence = self._food(text)
        free, free_evidence, restrictions = self._assess_free_food(lower)
        dietary = DietaryInfo(
            vegetarian=self._dietary_claim(lower, "vegetarian"),
            vegan=self._dietary_claim(lower, "vegan"),
        )
        open_all = TriState.YES if ("open to all" in lower or "everyone welcome" in lower) else (TriState.NO if "members only" in lower else TriState.UNKNOWN)
        location = self._location(text)
        status, status_evidence = self._status(lower)
        event_id = "evt_" + hashlib.sha1(f"{candidate.source_type}:{text}".encode()).hexdigest()[:12]
        return FoodEvent(
            event_id=event_id,
            organization=organization,
            event_name=self._name(text, organization),
            start_time=start,
            end_time=end,
            location=location,
            food=FoodInfo(free_food=free,
                          free_food_evidence=free_evidence,
                          description=description, description_evidence=evidence,
                          meal_level=self._meal_level(description), dietary=dietary,
                          offer_restrictions=restrictions),
            attendance=AttendanceInfo(open_to_all=open_all,
                                      evidence=EvidenceLevel.EXPLICIT if open_all is not TriState.UNKNOWN else EvidenceLevel.UNKNOWN,
                                      requirements="Membership required" if open_all is TriState.NO else None),
            sources=[candidate.to_source()], status=status, status_evidence=status_evidence,
            conflicts=conflicts,
        )

    @staticmethod
    def _status(text: str) -> tuple[EventStatus, EvidenceLevel]:
        reinstated = (
            r"\b(?:not|no longer)\s+cancelled\b",
            r"\b(?:not|no longer)\s+canceled\b",
            r"\b(?:we(?:'re| are)\s+)?back\s+on\b",
            r"\b(?:we(?:'re| are)\s+)?back\b",
            r"\breinstated\b",
            r"\buncancelled\b",
            r"\buncanceled\b",
            r"\bcancelled\?\s*(?:no|nope)\b",
            r"\bcanceled\?\s*(?:no|nope)\b",
        )
        if any(re.search(pattern, text) for pattern in reinstated):
            return EventStatus.SCHEDULED, EvidenceLevel.EXPLICIT

        cancelled = (
            r"\bcancelled\b",
            r"\bcanceled\b",
            r"\bcalled\s+off\b",
            r"\bwill\s+not\s+(?:take\s+place|occur)\b",
            r"\bcancellation\s+notice\b",
        )
        if any(re.search(pattern, text) for pattern in cancelled):
            return EventStatus.CANCELLED, EvidenceLevel.EXPLICIT
        return EventStatus.SCHEDULED, EvidenceLevel.UNKNOWN

    @classmethod
    def _assess_free_food(cls, text: str) -> tuple[TriState, EvidenceLevel, str | None]:
        restriction = cls._offer_restriction(text)
        if restriction:
            return TriState.UNKNOWN, EvidenceLevel.UNKNOWN, restriction
        if cls._has_explicit_free_food(text):
            return TriState.YES, EvidenceLevel.EXPLICIT, None
        return TriState.UNKNOWN, EvidenceLevel.UNKNOWN, None

    @staticmethod
    def _offer_restriction(text: str) -> str | None:
        if re.search(r"\bnon[- ]members?\s+pay\b", text) or re.search(r"\bmembers?\s+get\s+free\b", text):
            return "restricted to members or mixed paid/free offer"
        if re.search(r"\bfree\b.{0,40}\bfor the first\b", text):
            return "limited-quantity or first-N offer"
        return None

    @staticmethod
    def _has_explicit_free_food(text: str) -> bool:
        food = r"(?:pizza|food|snacks?|sandwiches?|tacos?|subs?|burritos?|pasta|chick-fil-a|bagels?|cookies?|breakfast|lunch|dinner)"
        claim = re.compile(
            rf"(?<![-\w])(?:free|complimentary)\s+(?:(?:vegan|vegetarian)\s+(?:and\s+)?){{0,2}}(?P<food>{food})\b"
        )
        hedge = re.compile(r"\b(?:maybe|might|may|could|hopefully|possibly)\b")
        historical = re.compile(
            r"\b(?:last\s+(?:semester|week|year|meeting)|yesterday|used to|had\s+free|was\s+awesome)\b"
        )
        paid = re.compile(r"(?:\$\s*\d|\d+\s*/\s*slice|\bbring\s+\$|\bfor\s+\$|\bfundraiser\b|\bcosts?\b|\bpriced?\b)")
        for match in claim.finditer(text):
            clause_start = max(text.rfind(mark, 0, match.start()) for mark in ".;!?") + 1
            clause_end_candidates = [text.find(mark, match.end()) for mark in ".;!"]
            clause_end = min((index for index in clause_end_candidates if index != -1), default=len(text))
            prefix = text[clause_start:match.start()]
            clause = text[clause_start:clause_end]
            remainder = text[match.end():clause_end]
            if re.search(r"\b(?:no|not)\s*$", prefix):
                continue
            if "?" in text[match.start():clause_end] or hedge.search(prefix) or hedge.search(remainder):
                continue
            if historical.search(clause) or paid.search(clause):
                continue
            named_food = re.escape(match.group("food"))
            contradicted = (
                re.match(r"\s*\?\s*(?:no|not\b)", remainder)
                or re.match(r"[^.;!?]*\b(?:but|however)\b[^.;!?]*\b(?:costs?|priced?|not free)\b", remainder)
                or re.match(
                    rf"\s*\?\s*no\b[^.;!?]*\b{named_food}\b[^.;!?]*(?:\$|\bcosts?\b|\bpriced?\b)",
                    remainder,
                )
            )
            if not contradicted:
                return True
        return False

    @staticmethod
    def _dietary_claim(text: str, dietary: str) -> TriState:
        clause = r"[^.;!?]*"
        if re.search(rf"\bno{clause}\b{dietary}\b{clause}\b(?:options?|food|meals?)\b", text):
            return TriState.NO
        foods = r"(?:pizza|food|snacks?|sandwiches?|tacos?|subs?|burritos?|pasta|bagels?|cookies?|options?|meals?)"
        if re.search(rf"\b{dietary}\b(?:\s+and\s+(?:vegan|vegetarian))?\s+{foods}\b", text):
            return TriState.YES
        return TriState.UNKNOWN

    @staticmethod
    def _date(text: str, ref: datetime):
        lower = text.lower()
        if "tomorrow" in lower:
            return (ref + timedelta(days=1)).date()
        explicit = re.search(r"(?:September|Sept)\s+(\d{1,2}),?\s+(\d{4})", text, re.I)
        if explicit:
            return datetime(int(explicit.group(2)), 9, int(explicit.group(1))).date()
        if "tonight" in lower:
            return ref.date()
        return None

    @staticmethod
    def _times(text: str):
        from datetime import time
        found = []
        for hour, minute, meridiem in re.findall(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", text, re.I):
            h = int(hour) % 12 + (12 if meridiem.lower() == "pm" else 0)
            found.append(time(h, int(minute or 0)))
        if re.search(r"\bat noon\b", text, re.I):
            found.append(time(12, 0))
        return found

    @classmethod
    def _food(cls, text: str):
        lower = text.lower()
        for food in cls._foods:
            if food.lower() in lower:
                return food.lower() if food != "Chick-fil-A" else food, EvidenceLevel.EXPLICIT
        if "food provided" in lower or "maybe food" in lower:
            return "food" if "provided" in lower else None, EvidenceLevel.EXPLICIT if "provided" in lower else EvidenceLevel.UNKNOWN
        if "🍕" in text:
            return "possible pizza", EvidenceLevel.INFERRED
        return None, EvidenceLevel.UNKNOWN

    @staticmethod
    def _meal_level(description: str | None):
        if not description:
            return MealLevel.UNKNOWN
        if any(x in description.lower() for x in ("snack", "cookie", "bagel")):
            return MealLevel.SNACK
        return MealLevel.MEAL

    @staticmethod
    def _location(text: str):
        patterns = [
            r"(Little(?: Hall)?(?: room)?\s+\w+)", r"(CSE\s+\w+)", r"(Turlington\s+\w+)",
            r"(Reitz(?: Union)?\s+\w+)", r"(Marston(?: lobby|\s+\w+))", r"(Weil\s+\w+)",
            r"(Library West)", r"(Flint\s+\w+)", r"(Pugh\s+\w+)", r"(Bryant Space Center)",
            r"(Matherly\s+\w+)", r"(LIT\s+\w+)",
        ]
        raw = next((m.group(1) for p in patterns if (m := re.search(p, text, re.I))), None)
        ambiguous = "near the reitz" in text.lower()
        if ambiguous:
            raw = "near the Reitz"
        if not raw:
            return EventLocation(ambiguous=ambiguous)
        room_match = re.search(r"(?:room\s+)?([A-Z]?\d{2,4})$", raw, re.I)
        room = room_match.group(1) if room_match else None
        building = re.sub(r"(?:\s+room)?\s+[A-Z]?\d{2,4}$", "", raw, flags=re.I)
        return EventLocation(building=building, room=room, raw_text=raw, ambiguous=ambiguous)

    @staticmethod
    def _name(text: str, organization: str | None):
        lower = text.lower()
        if "leftover alert" in lower:
            return "Leftover food alert"
        if "gbm" in lower or "general body meeting" in lower:
            return "General Body Meeting"
        for name in ("study night", "study break", "mixer", "demo", "lunch", "dinner", "social", "lecture", "astronomy night"):
            if name in lower:
                return name.title()
        return "Campus event" if organization else "Untitled event"
