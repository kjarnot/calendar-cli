# ABOUTME: Unit tests for the event models: snapshots and partial-update change tracking.
# ABOUTME: EventChanges must tell "not changing" apart from "clear this field".
from datetime import datetime
from zoneinfo import ZoneInfo

from calendar_cli.models import Event, EventChanges

START = datetime(2026, 12, 1, 10, tzinfo=ZoneInfo("America/New_York"))


def test_snapshot_round_trip_keeps_raw():
    event = Event(calendar_alias="work", provider_id="id-1", title="A", start=START, end=START, raw={"x": 1})

    restored = Event.from_snapshot(event.snapshot())

    assert restored == event
    assert restored.raw == {"x": 1}
    assert "raw" not in event.model_dump()


def test_changes_only_reports_fields_set():
    assert EventChanges(title="New").changed() == {"title": "New"}


def test_changes_setting_none_means_clear():
    assert EventChanges(location=None, categories=None).changed() == {"location": None, "categories": None}
