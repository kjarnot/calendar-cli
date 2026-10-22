# ABOUTME: Provider-neutral data models for calendars and events.
# ABOUTME: Every provider converts its API payloads into these types.
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CalendarInfo(BaseModel):
    """A calendar an account can see, as reported by the provider."""

    calendar_id: str
    name: str
    is_default: bool = False
    can_edit: bool = False


class Category(BaseModel):
    """A category an account accepts, with its color (an M365 preset or a Google color name)."""

    name: str
    color: str | None = None


class Attendee(BaseModel):
    email: str
    name: str | None = None
    response: str | None = None


class Event(BaseModel):
    calendar_alias: str
    provider_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    categories: list[str] = []
    attendees: list[Attendee] = []
    organizer: str | None = None
    is_organizer: bool = True
    series_id: str | None = None
    is_occurrence: bool = False
    web_link: str | None = None
    # The provider's original payload, kept so a restore loses as little as possible.
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    def snapshot(self) -> dict[str, Any]:
        """Full JSON-safe copy, including raw, for the journal."""
        return {**self.model_dump(mode="json"), "raw": self.raw}

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "Event":
        return cls.model_validate(data)


class EventDraft(BaseModel):
    """Everything needed to create an event."""

    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    categories: list[str] = []
    attendees: list[str] = []


class EventChanges(BaseModel):
    """A partial update. Only fields explicitly set are changed; setting one to None clears it."""

    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool | None = None
    location: str | None = None
    description: str | None = None
    categories: list[str] | None = None

    def changed(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.model_fields_set}
