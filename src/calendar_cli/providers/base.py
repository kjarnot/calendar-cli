# ABOUTME: The CalendarProvider interface every calendar backend implements, plus its error type.
# ABOUTME: The CLI talks only to this interface, never to a provider's API directly.
from datetime import datetime
from typing import Protocol

from calendar_cli.models import CalendarInfo, Event, EventChanges, EventDraft


class ProviderError(Exception):
    """Raised when a provider call fails (auth, permissions, network, or API error)."""


class CalendarProvider(Protocol):
    def list_calendars(self) -> list[CalendarInfo]: ...

    def list_events(
        self, calendar_alias: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Event]: ...

    def get_event(self, calendar_alias: str, calendar_id: str, event_id: str) -> Event: ...

    def create_event(self, calendar_alias: str, calendar_id: str, draft: EventDraft) -> Event: ...

    def update_event(
        self, calendar_alias: str, calendar_id: str, event_id: str, changes: EventChanges
    ) -> Event: ...

    def delete_event(self, calendar_id: str, event_id: str) -> None: ...

    def restore_event(self, calendar_alias: str, calendar_id: str, snapshot: Event) -> Event:
        """Bring back a deleted event from its snapshot. The returned event may have a new ID."""
        ...


class InputError(ProviderError):
    """Raised when a request is invalid for the provider (for example, an unknown category)."""
