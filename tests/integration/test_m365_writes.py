# ABOUTME: Integration tests for M365 write calls (create, update, delete, restore) against mocked Graph.
# ABOUTME: Checks request paths, JSON bodies, category validation and not-found handling.
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import respx

from calendar_cli.models import Event, EventChanges, EventDraft
from calendar_cli.providers.base import InputError
from calendar_cli.providers.m365 import GRAPH_URL, M365Provider
from tests.fixtures import GRAPH_MEETING, M365_ACCOUNT

TZ = ZoneInfo("America/New_York")
START = datetime(2026, 12, 1, 10, tzinfo=TZ)
USER_URL = f"{GRAPH_URL}/users/me@example.com"
CATEGORIES = {"value": [{"displayName": "Exercise"}, {"displayName": "Staff"}]}


@pytest.fixture
def provider() -> M365Provider:
    return M365Provider(M365_ACCOUNT, "America/New_York", token_provider=lambda: "test-token")


def body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_create_posts_full_body_to_named_calendar(provider):
    respx.get(f"{USER_URL}/outlook/masterCategories").respond(json=CATEGORIES)
    route = respx.post(f"{USER_URL}/calendars/cal-9/events").respond(201, json=GRAPH_MEETING)
    draft = EventDraft(
        title="Workout",
        start=START,
        end=START + timedelta(hours=1),
        location="Home",
        description="Row",
        categories=["Exercise"],
        attendees=["dan@example.com"],
    )

    event = provider.create_event("work", "cal-9", draft)

    assert event.provider_id == "AAMk-meeting"
    assert body(route) == {
        "subject": "Workout",
        "start": {"dateTime": "2026-12-01T10:00:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-12-01T11:00:00", "timeZone": "America/New_York"},
        "isAllDay": False,
        "location": {"displayName": "Home"},
        "body": {"contentType": "text", "content": "Row"},
        "categories": ["Exercise"],
        "attendees": [{"emailAddress": {"address": "dan@example.com"}, "type": "required"}],
    }


@respx.mock
def test_unknown_category_is_rejected_before_writing(provider):
    categories = respx.get(f"{USER_URL}/outlook/masterCategories").respond(json=CATEGORIES)
    create = respx.post(f"{USER_URL}/calendar/events").respond(201, json=GRAPH_MEETING)
    draft = EventDraft(title="X", start=START, end=START + timedelta(hours=1), categories=["Nope"])

    with pytest.raises(InputError, match="unknown M365 category 'Nope'; valid: Exercise, Staff"):
        provider.create_event("work", "primary", draft)
    with pytest.raises(InputError):
        provider.create_event("work", "primary", draft)
    assert not create.called
    assert categories.call_count == 1  # the category list is fetched once per provider


@respx.mock
def test_update_patches_only_changed_fields_and_clears(provider):
    route = respx.patch(f"{USER_URL}/events/AAMk-meeting").respond(json=GRAPH_MEETING)

    provider.update_event(
        "work", "primary", "AAMk-meeting", EventChanges(title="Renamed", location=None, categories=None)
    )

    assert body(route) == {"subject": "Renamed", "location": {"displayName": ""}, "categories": []}


@respx.mock
def test_get_event_fetches_full_payload(provider):
    route = respx.get(f"{USER_URL}/events/AAMk-meeting").respond(json=GRAPH_MEETING)

    assert provider.get_event("work", "primary", "AAMk-meeting").title == "Leadership sync"
    assert "$select" not in route.calls.last.request.url.params


@respx.mock
def test_delete_and_not_found(provider):
    respx.delete(f"{USER_URL}/events/gone").respond(
        404, json={"error": {"code": "ErrorItemNotFound", "message": "x"}}
    )
    ok = respx.delete(f"{USER_URL}/events/AAMk-meeting").respond(204)

    provider.delete_event("primary", "AAMk-meeting")
    assert ok.called
    with pytest.raises(InputError, match="not found: ErrorItemNotFound"):
        provider.delete_event("primary", "gone")


@respx.mock
def test_restore_recreates_from_raw_snapshot(provider):
    raw = {**GRAPH_MEETING, "body": {"contentType": "html", "content": "<p>Agenda</p>"}, "showAs": "busy"}
    raw["attendees"] = [{**raw["attendees"][0], "type": "optional"}]
    snapshot = provider._to_event("work", raw)
    route = respx.post(f"{USER_URL}/calendar/events").respond(201, json={**GRAPH_MEETING, "id": "AAMk-new"})

    restored = provider.restore_event("work", "primary", snapshot)

    assert restored.provider_id == "AAMk-new"
    sent = body(route)
    assert sent["body"] == {"contentType": "html", "content": "<p>Agenda</p>"}
    assert sent["showAs"] == "busy"
    assert sent["attendees"] == [
        {"emailAddress": {"address": "dan@example.com", "name": "Dan"}, "type": "optional"}
    ]
    assert "id" not in sent and "seriesMasterId" not in sent


def test_restore_without_raw_is_refused(provider):
    snapshot = Event(calendar_alias="work", provider_id="x", title="X", start=START, end=START)

    with pytest.raises(InputError, match="no Graph payload"):
        provider.restore_event("work", "primary", snapshot)


@respx.mock
def test_list_categories_maps_colors_and_is_cached(provider):
    route = respx.get(f"{USER_URL}/outlook/masterCategories").respond(
        json={
            "value": [{"displayName": "VIP", "color": "preset18"}, {"displayName": "Plain", "color": "none"}]
        }
    )

    first = provider.list_categories()
    provider._check_categories(["VIP"])

    assert [(c.name, c.color) for c in first] == [("VIP", "dark yellow"), ("Plain", None)]
    assert route.call_count == 1
