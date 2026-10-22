# ABOUTME: Integration tests for Google write calls (create, update, delete, restore) against mocked Calendar v3.
# ABOUTME: Checks bodies (dateTime vs date, colorId), sendUpdates, timing merges and undelete fallback.
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from calendar_cli.config import load_config
from calendar_cli.models import EventChanges, EventDraft
from calendar_cli.providers.base import InputError
from calendar_cli.providers.google import CALENDAR_URL, GoogleProvider
from tests.fixtures import GOOGLE_ALL_DAY, GOOGLE_MEETING

TZ = ZoneInfo("America/New_York")
START = datetime(2026, 12, 1, 10, tzinfo=TZ)
EVENTS = f"{CALENDAR_URL}/calendars/primary/events"


@pytest.fixture
def provider(write_config) -> GoogleProvider:
    return GoogleProvider("gmail", load_config(write_config()), token_provider=lambda: "test-token")


def body(call) -> dict:
    return json.loads(call.request.content)


@respx.mock
def test_create_timed_with_color_and_attendees(provider):
    route = respx.post(EVENTS).respond(json=GOOGLE_MEETING)
    draft = EventDraft(
        title="Run",
        start=START,
        end=START + timedelta(minutes=45),
        categories=["Exercise"],
        attendees=["kid@example.org"],
    )

    provider.create_event("personal", "primary", draft)

    sent = body(route.calls.last)
    assert sent["summary"] == "Run"
    assert sent["start"] == {
        "dateTime": "2026-12-01T10:00:00-05:00",
        "timeZone": "America/New_York",
        "date": None,
    }
    assert sent["colorId"] == "10"
    assert sent["attendees"] == [{"email": "kid@example.org"}]
    assert route.calls.last.request.url.params["sendUpdates"] == "all"


@respx.mock
def test_create_all_day_uses_dates(provider):
    route = respx.post(EVENTS).respond(json=GOOGLE_ALL_DAY)
    day = START.replace(hour=0)

    provider.create_event(
        "personal", "primary", EventDraft(title="Trip", start=day, end=day + timedelta(days=2), all_day=True)
    )

    sent = body(route.calls.last)
    assert sent["start"] == {"date": "2026-12-01", "dateTime": None, "timeZone": None}
    assert sent["end"]["date"] == "2026-12-03"


def test_unmapped_or_multiple_categories_are_rejected(provider):
    with pytest.raises(InputError, match="no Google color"):
        provider._payload({"categories": ["Meetings"]})
    with pytest.raises(InputError, match="one category"):
        provider._payload({"categories": ["Exercise", "Family"]})
    assert provider._payload({"categories": []}) == {"colorId": None}


@respx.mock
def test_update_title_only_is_a_single_patch(provider):
    route = respx.patch(f"{EVENTS}/g-allday").respond(json=GOOGLE_ALL_DAY)

    provider.update_event("personal", "primary", "g-allday", EventChanges(title="New"))

    assert body(route.calls.last) == {"summary": "New"}


@respx.mock
def test_update_start_of_all_day_event_keeps_dates(provider):
    respx.get(f"{EVENTS}/g-allday").respond(json=GOOGLE_ALL_DAY)
    route = respx.patch(f"{EVENTS}/g-allday").respond(json=GOOGLE_ALL_DAY)
    new_start = datetime(2026, 10, 26, tzinfo=TZ)

    provider.update_event(
        "personal", "primary", "g-allday", EventChanges(start=new_start, end=new_start + timedelta(days=1))
    )

    sent = body(route.calls.last)
    assert sent["start"]["date"] == "2026-10-26"
    assert sent["end"]["date"] == "2026-10-27"


@respx.mock
def test_event_ids_are_url_encoded(provider):
    route = respx.delete(f"{CALENDAR_URL}/calendars/a%40group.calendar.google.com/events/id%2Fx").respond(204)

    provider.delete_event("a@group.calendar.google.com", "id/x")

    assert route.calls.last.request.url.params["sendUpdates"] == "all"


@respx.mock
def test_restore_undeletes_in_place(provider):
    route = respx.patch(f"{EVENTS}/g-allday").respond(json=GOOGLE_ALL_DAY)
    snapshot = provider._to_event("personal", GOOGLE_ALL_DAY)

    restored = provider.restore_event("personal", "primary", snapshot)

    assert restored.provider_id == "g-allday"
    assert body(route.calls.last) == {"status": "confirmed"}


@respx.mock
def test_restore_recreates_when_purged(provider):
    respx.patch(f"{EVENTS}/g-allday").respond(
        410, json={"error": {"code": 410, "message": "Resource has been deleted"}}
    )
    create = respx.post(EVENTS).mock(return_value=httpx.Response(200, json={**GOOGLE_ALL_DAY, "id": "g-new"}))
    snapshot = provider._to_event("personal", GOOGLE_ALL_DAY)

    restored = provider.restore_event("personal", "primary", snapshot)

    assert restored.provider_id == "g-new"
    sent = body(create.calls.last)
    assert "id" not in sent and "organizer" not in sent and "status" not in sent
    assert sent["start"] == {"date": "2026-10-24"}
