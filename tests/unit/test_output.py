# ABOUTME: Unit tests for listing output: ref assignment, grouped text, and JSON rendering.
# ABOUTME: Builds Event objects directly; no provider is involved.
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from calendar_cli.models import Event
from calendar_cli.output import CalendarListing, assign_refs, render_json, render_text

TZ = ZoneInfo("America/New_York")


def event(alias: str, pid: str, title: str, start: datetime, end: datetime, **kwargs) -> Event:
    return Event(calendar_alias=alias, provider_id=pid, title=title, start=start, end=end, **kwargs)


def at(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, d, h, m, tzinfo=TZ)


def sample() -> list[CalendarListing]:
    work = CalendarListing(
        alias="work",
        provider="m365",
        label="M365 · me@example.com",
        events=[
            event("work", "id-b", "Standup", at(23, 10), at(23, 10, 30)),
            event("work", "id-a", "Workout", at(22, 12), at(22, 13), categories=["Exercise"]),
            event("work", "id-c", "PTO", at(21, 0), at(27, 0), all_day=True, raw={"secret": "x"}),
        ],
    )
    personal = CalendarListing(alias="personal", provider="google", label="Google · primary")
    broken = CalendarListing(alias="other", provider="google", label="Google · x", error="token expired")
    return [work, personal, broken]


def test_assign_refs_sorts_by_start_and_numbers_per_calendar():
    listings = sample()

    refs = assign_refs(listings)

    assert refs == {"work:1": ("work", "id-c"), "work:2": ("work", "id-a"), "work:3": ("work", "id-b")}
    assert [e.title for e in listings[0].events] == ["PTO", "Workout", "Standup"]


def test_render_text_groups_by_calendar_and_day():
    listings = sample()
    assign_refs(listings)

    assert render_text(listings).splitlines() == [
        "work (M365 · me@example.com)",
        "  Wed 2026-10-21",
        "    work:1       thru Mon 10-26 PTO",
        "  Thu 2026-10-22",
        "    work:2       12:00–13:00    Workout  [Exercise]",
        "  Fri 2026-10-23",
        "    work:3       10:00–10:30    Standup",
        "personal (Google · primary)",
        "  (no events)",
        "other (Google · x)",
        "  error: token expired",
    ]


def test_single_day_all_day_event_says_all_day():
    listing = CalendarListing(
        alias="p",
        provider="google",
        label="G",
        events=[event("p", "1", "Holiday", at(24, 0), at(25, 0), all_day=True)],
    )

    assert "p:1          all day      Holiday" in render_text([listing])


def test_render_json_has_refs_and_omits_raw():
    listings = sample()
    assign_refs(listings)

    payload = json.loads(render_json(listings, at(22, 0), at(29, 0)))

    assert payload["range"] == {"from": "2026-10-22T00:00:00-04:00", "to": "2026-10-29T00:00:00-04:00"}
    first = payload["calendars"][0]["events"][0]
    assert first["ref"] == "work:1"
    assert first["title"] == "PTO"
    assert "raw" not in first
    assert payload["calendars"][2] == {
        "alias": "other",
        "provider": "google",
        "error": "token expired",
        "events": [],
    }


def test_long_alias_widens_ref_column():
    listing = CalendarListing(
        alias="e2e-personal",
        provider="google",
        label="G",
        events=[event("e2e-personal", "1", "Lunch", at(22, 12), at(22, 13))],
    )

    assert "    e2e-personal:1 12:00–13:00  Lunch" in render_text([listing])
