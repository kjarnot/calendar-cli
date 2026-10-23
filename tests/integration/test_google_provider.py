# ABOUTME: Integration tests for the Google provider against mocked Calendar v3 HTTP responses.
# ABOUTME: Uses respx to intercept httpx; checks URLs, query params, paging and error handling.
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from calendar_cli.config import load_config
from calendar_cli.providers.base import ProviderError
from calendar_cli.providers.google import CALENDAR_URL, GoogleProvider
from tests.fixtures import GOOGLE_ALL_DAY, GOOGLE_CANCELLED, GOOGLE_MEETING

TZ = ZoneInfo("America/New_York")
START = datetime(2026, 10, 22, tzinfo=TZ)
END = datetime(2026, 10, 29, tzinfo=TZ)


@pytest.fixture
def provider(write_config) -> GoogleProvider:
    return GoogleProvider("gmail", load_config(write_config()), token_provider=lambda: "test-token")


@respx.mock
def test_list_calendars_follows_pages_and_maps_roles(provider):
    route = respx.get(f"{CALENDAR_URL}/users/me/calendarList")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "me@example.org",
                        "summary": "me@example.org",
                        "primary": True,
                        "accessRole": "owner",
                    }
                ],
                "nextPageToken": "page-2",
            },
        ),
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "abc@group.calendar.google.com",
                        "summary": "calendar-cli e2e",
                        "accessRole": "writer",
                    },
                    {
                        "id": "en.usa#holiday@group.v.calendar.google.com",
                        "summary": "Holidays",
                        "accessRole": "reader",
                    },
                ]
            },
        ),
    ]

    calendars = provider.list_calendars()

    assert [(c.name, c.is_default, c.can_edit) for c in calendars] == [
        ("me@example.org", True, True),
        ("calendar-cli e2e", False, True),
        ("Holidays", False, False),
    ]
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"
    assert route.calls[1].request.url.params["pageToken"] == "page-2"


@respx.mock
def test_list_events_encodes_calendar_id_and_skips_cancelled(provider):
    route = respx.get(f"{CALENDAR_URL}/calendars/abc%40group.calendar.google.com/events").respond(
        json={"items": [GOOGLE_MEETING, GOOGLE_CANCELLED, GOOGLE_ALL_DAY]}
    )

    events = provider.list_events("personal", "abc@group.calendar.google.com", START, END)

    assert [e.provider_id for e in events] == ["g-meeting_20261022T130000Z", "g-allday"]
    params = route.calls.last.request.url.params
    assert params["timeMin"] == "2026-10-22T00:00:00-04:00"
    assert params["timeMax"] == "2026-10-29T00:00:00-04:00"
    assert params["singleEvents"] == "true"
    assert params["orderBy"] == "startTime"
    assert params["timeZone"] == "America/New_York"


@respx.mock
def test_list_events_follows_pages_keeping_query(provider):
    route = respx.get(f"{CALENDAR_URL}/calendars/primary/events")
    route.side_effect = [
        httpx.Response(200, json={"items": [GOOGLE_MEETING], "nextPageToken": "p2"}),
        httpx.Response(200, json={"items": [GOOGLE_ALL_DAY]}),
    ]

    events = provider.list_events("personal", "primary", START, END)

    assert len(events) == 2
    second = route.calls[1].request.url.params
    assert second["pageToken"] == "p2"
    assert second["timeMin"] == "2026-10-22T00:00:00-04:00"


@respx.mock
def test_api_error_becomes_provider_error(provider):
    respx.get(f"{CALENDAR_URL}/calendars/primary/events").respond(
        403,
        json={
            "error": {"code": 403, "status": "PERMISSION_DENIED", "message": "Calendar API has not been used"}
        },
    )

    with pytest.raises(ProviderError, match="HTTP 403: PERMISSION_DENIED: Calendar API has not been used"):
        provider.list_events("personal", "primary", START, END)


@respx.mock
def test_network_error_becomes_provider_error(provider):
    respx.get(f"{CALENDAR_URL}/calendars/primary/events").mock(side_effect=httpx.ConnectError("offline"))

    with pytest.raises(ProviderError, match="Google request failed: offline"):
        provider.list_events("personal", "primary", START, END)
