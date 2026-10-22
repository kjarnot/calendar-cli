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
