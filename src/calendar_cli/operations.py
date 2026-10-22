# ABOUTME: Journaled write operations (create, update, delete) and their undo.
# ABOUTME: Every write, successful or failed, is recorded in the journal before returning.
import logging

from calendar_cli import journal
from calendar_cli.config import CalendarEntry
from calendar_cli.journal import JournalEntry
from calendar_cli.models import Event, EventChanges, EventDraft
from calendar_cli.output import time_span
from calendar_cli.providers.base import CalendarProvider, ProviderError

# Fields an undo of an update puts back, when they differ between the before and after snapshots.
RESTORABLE_FIELDS = ("title", "start", "end", "all_day", "location", "description", "categories")

logger = logging.getLogger("calendar_cli.operations")


class UndoError(Exception):
    """Raised when an operation cannot be undone."""


def describe(event: Event) -> str:
    """One line for prompts and confirmations, e.g. 'Dentist — Fri 2026-10-23 14:00–15:00 (personal)'."""
    tags = f" [{', '.join(event.categories)}]" if event.categories else ""
    return f"{event.title} — {event.start:%a %Y-%m-%d} {time_span(event)} ({event.calendar_alias}){tags}"


def create(
    provider: CalendarProvider, cal: CalendarEntry, draft: EventDraft, tz: str
) -> tuple[Event, JournalEntry]:
    try:
        event = provider.create_event(cal.alias, cal.calendar_id, draft)
    except ProviderError as exc:
        journal.record("create", cal.alias, "", draft.title, tz, error=str(exc))
        raise
    entry = journal.record("create", cal.alias, event.provider_id, event.title, tz, after=event)
    logger.info("create %s %s: %s", entry.op_id, cal.alias, event.provider_id)
    return event, entry


def update(
    provider: CalendarProvider, cal: CalendarEntry, before: Event, changes: EventChanges, tz: str
) -> tuple[Event, JournalEntry]:
    try:
        after = provider.update_event(cal.alias, cal.calendar_id, before.provider_id, changes)
    except ProviderError as exc:
        journal.record(
            "update", cal.alias, before.provider_id, before.title, tz, before=before, error=str(exc)
        )
        raise
    entry = journal.record(
        "update", cal.alias, after.provider_id, after.title, tz, before=before, after=after
    )
    logger.info("update %s %s: %s %s", entry.op_id, cal.alias, after.provider_id, sorted(changes.changed()))
    return after, entry


def delete(
    provider: CalendarProvider, cal: CalendarEntry, before: Event, series: bool, tz: str
) -> JournalEntry:
    try:
        provider.delete_event(cal.calendar_id, before.provider_id)
    except ProviderError as exc:
        journal.record(
            "delete",
            cal.alias,
            before.provider_id,
            before.title,
            tz,
            before=before,
            series=series,
            error=str(exc),
        )
        raise
    entry = journal.record(
        "delete", cal.alias, before.provider_id, before.title, tz, before=before, series=series
    )
    logger.info("delete %s %s: %s series=%s", entry.op_id, cal.alias, before.provider_id, series)
    return entry


def undo_plan(target: JournalEntry) -> str:
    """Say in one line what undoing `target` will do."""
    if target.action == "create":
        return f"delete the event created by {target.op_id}: {describe(target.after_event())}"
    if target.action == "update":
        return f"put back the earlier version of: {describe(target.before_event())}"
    if target.series:
        raise UndoError(
            f"{target.op_id} deleted a whole recurring series; undoing a series delete is not supported"
        )
    return f"restore the deleted event: {describe(target.before_event())}"


def undo(
    provider: CalendarProvider, cal: CalendarEntry, target: JournalEntry, tz: str, current_id: str
) -> tuple[Event | None, JournalEntry]:
    """Reverse `target` and journal the undo. Returns the resulting event (None when undoing a create).

    current_id is the event's ID now, which differs from the journaled one if a restore recreated it.
    """
    undo_plan(target)  # raises UndoError for unsupported cases
    try:
        result = _reverse(provider, cal, target, current_id)
    except ProviderError as exc:
        journal.record(
            "undo", cal.alias, target.event_id, target.title, tz, undoes=target.op_id, error=str(exc)
        )
        raise
    before = target.after_event()
    entry = journal.record(
        "undo",
        cal.alias,
        result.provider_id if result else target.event_id,
        target.title,
        tz,
        before=before,
        after=result,
        undoes=target.op_id,
    )
    logger.info("undo %s of %s %s", entry.op_id, target.action, target.op_id)
    return result, entry


def _reverse(
    provider: CalendarProvider, cal: CalendarEntry, target: JournalEntry, current_id: str
) -> Event | None:
    if target.action == "create":
        provider.delete_event(cal.calendar_id, current_id)
        return None
    if target.action == "update":
        before, after = target.before_event(), target.after_event()
        restore = {
            name: getattr(before, name)
            for name in RESTORABLE_FIELDS
            if getattr(before, name) != getattr(after, name)
        }
        if not restore:
            return after
        return provider.update_event(cal.alias, cal.calendar_id, current_id, EventChanges(**restore))
    return provider.restore_event(cal.alias, cal.calendar_id, target.before_event())
