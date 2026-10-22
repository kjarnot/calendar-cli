# ABOUTME: Unit tests for the operation journal: recording, reading, undo target selection and ID following.
# ABOUTME: The autouse isolated_state fixture keeps the journal in a temp folder.
import stat
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calendar_cli import journal
from calendar_cli.models import Event

TZ = "America/New_York"


def event(pid: str, title: str = "Dentist") -> Event:
    start = datetime(2026, 12, 1, 10, tzinfo=ZoneInfo(TZ))
    return Event(calendar_alias="work", provider_id=pid, title=title, start=start, end=start, raw={"id": pid})


def test_record_and_read_round_trip(isolated_state):
    entry = journal.record("create", "work", "id-1", "Dentist", TZ, after=event("id-1"))

    [read] = journal.read_all()
    assert read == entry
    assert read.after_event().provider_id == "id-1"
    assert read.after_event().raw == {"id": "id-1"}
    assert read.before_event() is None
    assert stat.S_IMODE((isolated_state / "journal.jsonl").stat().st_mode) == 0o600


def test_failed_entry_has_status_and_error():
    entry = journal.record("create", "work", "", "Dentist", TZ, error="HTTP 500")

    assert (entry.status, entry.error) == ("failed", "HTTP 500")


def test_read_all_empty_without_file():
    assert journal.read_all() == []


def test_find_latest_skips_undone_failed_and_undo_entries():
    a = journal.record("create", "work", "id-1", "A", TZ, after=event("id-1"))
    b = journal.record("create", "work", "id-2", "B", TZ, after=event("id-2"))
    journal.record("undo", "work", "id-2", "B", TZ, undoes=b.op_id)
    journal.record("create", "work", "", "C", TZ, error="boom")

    assert journal.find_undo_target(journal.read_all(), None).op_id == a.op_id


def test_find_nothing_to_undo():
    with pytest.raises(LookupError, match="nothing to undo"):
        journal.find_undo_target([], None)


def test_find_named_entry_errors():
    a = journal.record("create", "work", "id-1", "A", TZ, after=event("id-1"))
    u = journal.record("undo", "work", "id-1", "A", TZ, undoes=a.op_id)
    f = journal.record("create", "work", "", "F", TZ, error="boom")
    entries = journal.read_all()

    with pytest.raises(LookupError, match="no journal entry 'nope'"):
        journal.find_undo_target(entries, "nope")
    with pytest.raises(LookupError, match=f"already undone by {u.op_id}"):
        journal.find_undo_target(entries, a.op_id)
    with pytest.raises(LookupError, match="is itself an undo"):
        journal.find_undo_target(entries, u.op_id)
    with pytest.raises(LookupError, match="failed, so there is nothing to undo"):
        journal.find_undo_target(entries, f.op_id)


def test_failed_undo_does_not_count_as_undone():
    a = journal.record("create", "work", "id-1", "A", TZ, after=event("id-1"))
    journal.record("undo", "work", "id-1", "A", TZ, undoes=a.op_id, error="HTTP 500")

    assert journal.find_undo_target(journal.read_all(), None).op_id == a.op_id


def test_current_event_id_follows_restores_that_changed_the_id():
    journal.record("create", "work", "id-1", "A", TZ, after=event("id-1"))
    d1 = journal.record("delete", "work", "id-1", "A", TZ, before=event("id-1"))
    journal.record("undo", "work", "id-2", "A", TZ, after=event("id-2"), undoes=d1.op_id)
    d2 = journal.record("delete", "work", "id-2", "A", TZ, before=event("id-2"))
    journal.record("undo", "work", "id-3", "A", TZ, after=event("id-3"), undoes=d2.op_id)
    entries = journal.read_all()

    assert journal.current_event_id(entries, "id-1") == "id-3"
    assert journal.current_event_id(entries, "id-9") == "id-9"
