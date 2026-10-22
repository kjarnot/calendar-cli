# ABOUTME: Integration tests for the M365 provider against mocked Microsoft Graph HTTP responses.
# ABOUTME: Uses respx to intercept httpx; checks URLs, headers, paging and error handling.
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from calendar_cli.providers.base import ProviderError
from calendar_cli.providers.m365 import GRAPH_URL, M365Provider
from tests.fixtures import GRAPH_ALL_DAY, GRAPH_MEETING, M365_ACCOUNT

TZ = ZoneInfo("America/New_York")
START = datetime(2026, 10, 22, tzinfo=TZ)
END = datetime(2026, 10, 29, tzinfo=TZ)
USER_URL = f"{GRAPH_URL}/users/me@example.com"


@pytest.fixture
def provider() -> M365Provider:
    return M365Provider(M365_ACCOUNT, "America/New_York", token_provider=lambda: "test-token")


@respx.mock
def test_list_calendars(provider):
    respx.get(f"{USER_URL}/calendars").respond(
        json={"value": [{"id": "cal-1", "name": "Calendar", "isDefaultCalendar": True, "canEdit": True}]}
    )

    calendars = provider.list_calendars()

    assert [(c.calendar_id, c.name, c.is_default, c.can_edit) for c in calendars] == [
        ("cal-1", "Calendar", True, True)
    ]


@respx.mock
def test_list_events_primary_uses_default_calendar_and_sends_headers(provider):
    route = respx.get(f"{USER_URL}/calendar/calendarView").respond(json={"value": [GRAPH_MEETING]})

    events = provider.list_events("work", "primary", START, END)

    assert [e.title for e in events] == ["Leadership sync"]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Prefer"] == 'outlook.timezone="America/New_York"'
    assert request.url.params["startDateTime"] == "2026-10-22T00:00:00-04:00"
    assert request.url.params["endDateTime"] == "2026-10-29T00:00:00-04:00"


@respx.mock
def test_list_events_named_calendar_and_follows_next_link(provider):
    next_url = f"{USER_URL}/calendars/cal-9/calendarView?$skip=100"
    route = respx.get(f"{USER_URL}/calendars/cal-9/calendarView")
    route.side_effect = [
        httpx.Response(200, json={"value": [GRAPH_MEETING], "@odata.nextLink": next_url}),
        httpx.Response(200, json={"value": [GRAPH_ALL_DAY]}),
    ]

    events = provider.list_events("e2e", "cal-9", START, END)

    assert [e.provider_id for e in events] == ["AAMk-meeting", "AAMk-allday"]
    assert route.calls[1].request.url.params["$skip"] == "100"
    assert "startDateTime" not in route.calls[1].request.url.params


@respx.mock
def test_graph_error_becomes_provider_error(provider):
    respx.get(f"{USER_URL}/calendar/calendarView").respond(
        403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}}
    )

    with pytest.raises(ProviderError, match="HTTP 403: ErrorAccessDenied: Access is denied."):
        provider.list_events("work", "primary", START, END)


@respx.mock
def test_network_error_becomes_provider_error(provider):
    respx.get(f"{USER_URL}/calendar/calendarView").mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(ProviderError, match="M365 request failed: no route"):
        provider.list_events("work", "primary", START, END)
