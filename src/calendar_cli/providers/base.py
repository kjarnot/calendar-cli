# ABOUTME: The CalendarProvider interface every calendar backend implements, plus its error type.
# ABOUTME: The CLI talks only to this interface, never to a provider's API directly.
from datetime import datetime
from typing import Protocol

from calendar_cli.models import CalendarInfo, Event


class ProviderError(Exception):
    """Raised when a provider call fails (auth, permissions, network, or API error)."""


class CalendarProvider(Protocol):
    def list_calendars(self) -> list[CalendarInfo]: ...

    def list_events(
        self, calendar_alias: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Event]: ...
