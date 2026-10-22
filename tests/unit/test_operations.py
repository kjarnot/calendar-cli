# ABOUTME: Unit tests for journaled writes and undo, using the in-memory MemoryProvider.
# ABOUTME: Checks journal contents, failure recording, undo of each action, and M365-style ID changes.
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from calendar_cli import journal, operations
from calendar_cli.config import CalendarEntry
from calendar_cli.models import EventChanges, EventDraft
from calendar_cli.providers.base import InputError, ProviderError
from tests.fakes import MemoryProvider

TZ = "America/New_York"
CAL = CalendarEntry(alias="work", account="office")
START = datetime(2026, 12, 1, 10, tzinfo=ZoneInfo(TZ))


def draft(**kwargs) -> EventDraft:
    return EventDraft(**{"title": "Dentist", "start": START, "end": START + timedelta(hours=1), **kwargs})


def undo_latest(provider: MemoryProvider):
    entries = journal.read_all()
    target = journal.find_undo_target(entries, None)
    return operations.undo(provider, CAL, target, TZ, journal.current_event_id(entries, target.event_id))


def test_create_is_journaled_and_undo_deletes_it():
    provider = MemoryProvider()
    event, entry = operations.create(provider, CAL, draft(categories=["Exercise"]), TZ)

    assert (entry.action, entry.event_id, entry.after["title"]) == ("create", event.provider_id, "Dentist")
    assert operations.undo_plan(entry).startswith(f"delete the event created by {entry.op_id}")

    result, undo_entry = undo_latest(provider)
    assert result is None
    assert provider.events == {}
    assert undo_entry.undoes == entry.op_id


def test_failed_create_is_journaled_and_reraised():
    provider = MemoryProvider()
    provider.fail_next = "HTTP 500"

    with pytest.raises(ProviderError, match="HTTP 500"):
        operations.create(provider, CAL, draft(), TZ)
    [entry] = journal.read_all()
    assert (entry.status, entry.error, entry.title) == ("failed", "HTTP 500", "Dentist")


def test_invalid_category_is_journaled_as_failed():
    with pytest.raises(InputError):
        operations.create(MemoryProvider(), CAL, draft(categories=["Nope"]), TZ)
    assert journal.read_all()[0].status == "failed"


def test_update_undo_restores_only_changed_fields():
    provider = MemoryProvider()
    event, _ = operations.create(provider, CAL, draft(location="Office", categories=["Exercise"]), TZ)
    later = START + timedelta(hours=2)
    operations.update(
        provider,
        CAL,
        event,
        EventChanges(title="Dentist (moved)", start=later, end=later + timedelta(hours=1), categories=None),
        TZ,
    )
    provider.events[event.provider_id] = provider.events[event.provider_id].model_copy(
        update={"location": "Changed elsewhere"}
    )

    restored, entry = undo_latest(provider)

    assert restored.title == "Dentist"
    assert restored.start == START
    assert restored.categories == ["Exercise"]
    assert (
        restored.location == "Changed elsewhere"
    )  # location was not part of the update, so it is left alone
    assert entry.action == "undo"


def test_delete_undo_restores_and_follows_new_id():
    provider = MemoryProvider(restore_keeps_id=False)
    event, _ = operations.create(provider, CAL, draft(), TZ)
    operations.delete(provider, CAL, event, series=False, tz=TZ)
    assert provider.events == {}

    restored, _ = undo_latest(provider)
    assert restored.provider_id != event.provider_id
    assert restored.title == "Dentist"

    result, _ = undo_latest(provider)  # now undo the original create, which must target the new ID
    assert result is None
    assert provider.events == {}


def test_delete_undo_keeps_id_when_provider_undeletes():
    provider = MemoryProvider(restore_keeps_id=True)
    event, _ = operations.create(provider, CAL, draft(), TZ)
    operations.delete(provider, CAL, event, series=False, tz=TZ)

    restored, _ = undo_latest(provider)
    assert restored.provider_id == event.provider_id


def test_series_delete_cannot_be_undone():
    provider = MemoryProvider()
    event, _ = operations.create(provider, CAL, draft(), TZ)
    entry = operations.delete(provider, CAL, event, series=True, tz=TZ)

    with pytest.raises(operations.UndoError, match="series delete is not supported"):
        operations.undo_plan(entry)


def test_failed_undo_is_journaled():
    provider = MemoryProvider()
    operations.create(provider, CAL, draft(), TZ)
    provider.fail_next = "HTTP 503"

    with pytest.raises(ProviderError):
        undo_latest(provider)
    last = journal.read_all()[-1]
    assert (last.action, last.status, last.error) == ("undo", "failed", "HTTP 503")


def test_describe():
    provider = MemoryProvider()
    event, _ = operations.create(provider, CAL, draft(categories=["Exercise"]), TZ)

    assert operations.describe(event) == "Dentist — Tue 2026-12-01 10:00–11:00 (work) [Exercise]"
