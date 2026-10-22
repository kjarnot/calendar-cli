# ABOUTME: Unit tests for converting Microsoft Graph event payloads into Event objects.
# ABOUTME: Exercises the M365 provider's parsing only; no HTTP calls are made.
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calendar_cli.providers.m365 import M365Provider, _graph_time, _outlook_color
from tests.fixtures import GRAPH_ALL_DAY, GRAPH_MEETING, M365_ACCOUNT

TZ_NAME = "America/New_York"


def provider() -> M365Provider:
    return M365Provider(M365_ACCOUNT, TZ_NAME, token_provider=lambda: "unused")


def test_graph_time_trims_seven_digit_fraction():
    value = {"dateTime": "2026-10-22T09:00:00.1234567", "timeZone": TZ_NAME}

    assert _graph_time(value, TZ_NAME) == datetime(2026, 10, 22, 9, 0, 0, 123456, tzinfo=ZoneInfo(TZ_NAME))


def test_graph_time_falls_back_on_windows_zone_name():
    value = {"dateTime": "2026-10-22T09:00:00", "timeZone": "Eastern Standard Time"}

    assert _graph_time(value, TZ_NAME).tzinfo == ZoneInfo(TZ_NAME)


def test_meeting_payload_maps_all_fields():
    event = provider()._to_event("work", GRAPH_MEETING)

    assert event.calendar_alias == "work"
    assert event.provider_id == "AAMk-meeting"
    assert event.title == "Leadership sync"
    assert event.start == datetime(2026, 10, 22, 9, 0, tzinfo=ZoneInfo(TZ_NAME))
    assert event.location == "Teams"
    assert event.description == "Agenda: budget"
    assert event.categories == ["Meetings"]
    assert event.attendees[0].email == "dan@example.com"
    assert event.attendees[0].response == "accepted"
    assert event.organizer == "me@example.com"
    assert event.is_organizer is True
    assert event.series_id == "AAMk-series"
    assert event.is_occurrence is True
    assert event.raw == GRAPH_MEETING


def test_all_day_payload_keeps_its_date_and_blanks_become_none():
    event = provider()._to_event("work", GRAPH_ALL_DAY)

    assert event.all_day is True
    assert event.start.date().isoformat() == "2026-10-24"
    assert event.title == "(no title)"
    assert event.location is None
    assert event.description is None
    assert event.is_organizer is False
    assert event.is_occurrence is False


@pytest.mark.parametrize(
    ("preset", "name"),
    [
        ("preset0", "red"),
        ("preset18", "dark yellow"),
        ("preset24", "dark cranberry"),
        ("none", None),
        (None, None),
        ("preset99", "preset99"),
    ],
)
def test_outlook_color_names(preset, name):
    assert _outlook_color(preset) == name
