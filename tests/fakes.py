# ABOUTME: An in-memory CalendarProvider for testing write operations and undo without any HTTP.
# ABOUTME: Can mimic M365 (restore gets a new ID) or Google (restore keeps the ID).
import itertools
from datetime import datetime

from calendar_cli.models import Attendee, CalendarInfo, Event, EventChanges, EventDraft
from calendar_cli.providers.base import InputError, ProviderError


class MemoryProvider:
    def __init__(
        self, restore_keeps_id: bool = False, valid_categories: tuple[str, ...] = ("Exercise", "Staff")
    ):
        self.events: dict[str, Event] = {}
        self.restore_keeps_id = restore_keeps_id
        self.valid_categories = valid_categories
        self.fail_next: str | None = None
        self._ids = itertools.count(1)

    def _maybe_fail(self) -> None:
        if self.fail_next:
            message, self.fail_next = self.fail_next, None
            raise ProviderError(message)

    def _check(self, categories: list[str]) -> None:
        unknown = [c for c in categories if c not in self.valid_categories]
        if unknown:
            raise InputError(f"unknown category {unknown[0]!r}")

    def add(self, alias: str, title: str, start: datetime, end: datetime, **kwargs) -> Event:
        event = Event(
            calendar_alias=alias,
            provider_id=f"id-{next(self._ids)}",
            title=title,
            start=start,
            end=end,
            **kwargs,
        )
        event.raw = {"id": event.provider_id, "subject": title}
        self.events[event.provider_id] = event
        return event

    def list_calendars(self) -> list[CalendarInfo]:
        return [CalendarInfo(calendar_id="primary", name="Calendar", is_default=True, can_edit=True)]

    def list_events(self, calendar_alias, calendar_id, start, end) -> list[Event]:
        return [e for e in self.events.values() if e.start < end and e.end > start]

    def get_event(self, calendar_alias, calendar_id, event_id) -> Event:
        self._maybe_fail()
        if event_id not in self.events:
            raise InputError(f"event {event_id} not found")
        return self.events[event_id]

    def create_event(self, calendar_alias, calendar_id, draft: EventDraft) -> Event:
        self._maybe_fail()
        self._check(draft.categories)
        return self.add(
            calendar_alias,
            draft.title,
            draft.start,
            draft.end,
            all_day=draft.all_day,
            location=draft.location,
            description=draft.description,
            categories=draft.categories,
            attendees=[Attendee(email=a) for a in draft.attendees],
        )

    def update_event(self, calendar_alias, calendar_id, event_id, changes: EventChanges) -> Event:
        self._maybe_fail()
        current = self.get_event(calendar_alias, calendar_id, event_id)
        changed = changes.changed()
        if "categories" in changed:
            changed["categories"] = changed["categories"] or []
            self._check(changed["categories"])
        updated = current.model_copy(update=changed)
        updated.raw = current.raw
        self.events[event_id] = updated
        return updated

    def delete_event(self, calendar_id, event_id) -> None:
        self._maybe_fail()
        if self.events.pop(event_id, None) is None:
            raise InputError(f"event {event_id} not found")

    def restore_event(self, calendar_alias, calendar_id, snapshot: Event) -> Event:
        self._maybe_fail()
        new_id = snapshot.provider_id if self.restore_keeps_id else f"id-{next(self._ids)}"
        restored = snapshot.model_copy(update={"provider_id": new_id})
        restored.raw = snapshot.raw
        self.events[new_id] = restored
        return restored
