# ABOUTME: Unit tests for converting Google Calendar event payloads into Event objects.
# ABOUTME: Covers timed and all-day events, color-to-category mapping, and organizer detection.
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calendar_cli.config import load_config
from calendar_cli.providers.google import GoogleProvider
from tests.fixtures import GOOGLE_ALL_DAY, GOOGLE_MEETING

TZ = ZoneInfo("America/New_York")


@pytest.fixture
def provider(write_config) -> GoogleProvider:
    return GoogleProvider("gmail", load_config(write_config()), token_provider=lambda: "unused")


def test_timed_event_maps_all_fields(provider):
    event = provider._to_event("personal", GOOGLE_MEETING)

    assert event.calendar_alias == "personal"
    assert event.provider_id == "g-meeting_20261022T130000Z"
    assert event.title == "Dinner with family"
    assert event.start == datetime(2026, 10, 22, 9, 0, tzinfo=TZ)
    assert event.start.tzinfo == TZ
    assert event.end == datetime(2026, 10, 22, 10, 0, tzinfo=TZ)
    assert event.all_day is False
    assert event.location == "Home"
    assert event.description == "Bring dessert"
    assert event.categories == ["Family"]  # colorId 6 = tangerine = Family in the test config
    assert [a.email for a in event.attendees] == ["me@example.org", "kid@example.org"]
    assert event.attendees[1].name == "Kid"
    assert event.attendees[1].response == "needsAction"
    assert event.organizer == "kid@example.org"
    assert event.is_organizer is False
    assert event.series_id == "g-meeting"
    assert event.is_occurrence is True
    assert event.raw == GOOGLE_MEETING


def test_all_day_event(provider):
    event = provider._to_event("personal", GOOGLE_ALL_DAY)

    assert event.all_day is True
    assert event.start == datetime(2026, 10, 24, tzinfo=TZ)
    assert event.end == datetime(2026, 10, 25, tzinfo=TZ)
    assert event.title == "(no title)"
    assert event.categories == []
    assert event.is_organizer is True
    assert event.is_occurrence is False


def test_unmapped_color_has_no_category(provider):
    event = provider._to_event("personal", {**GOOGLE_MEETING, "colorId": "1"})

    assert event.categories == []


def test_event_without_organizer_is_ours(provider):
    payload = {key: value for key, value in GOOGLE_ALL_DAY.items() if key != "organizer"}

    assert provider._to_event("personal", payload).is_organizer is True
