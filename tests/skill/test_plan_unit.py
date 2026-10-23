# ABOUTME: Unit tests for plan.py: busy rules, free windows, conflicts and daily load.
# ABOUTME: Pure functions only; no subprocess or network.
import re
from datetime import date, time
from zoneinfo import ZoneInfo

from tests.skill.conftest import ev

TZ = ZoneInfo("America/New_York")


def test_busy_rules(plan, week_payload):
    events, _, _ = plan.load_events(week_payload)
    ignore = re.compile(plan.DEFAULT_IGNORE, re.IGNORECASE)
    reasons = {e.title: plan.not_busy_reason(e, ignore) for e in events}

    assert reasons == {
        "Standup": None,
        "Planning": None,
        "Dan: PTO": "all-day",
        "Robin appointment": "colleague notice",
        "Canceled: Vendor call": "canceled",
        "Alex - Work 9am-6pm": "family member's event",
        "K - dentist": None,
    }


def test_own_appointment_is_busy(plan):
    events, _, _ = plan.load_events(
        {
            "range": {"from": "2026-10-27T00:00:00-04:00", "to": "2026-10-28T00:00:00-04:00"},
            "calendars": [{"alias": "personal", "events": [ev("Doctor appointment", "10:00", "11:00")]}],
        }
    )

    assert plan.not_busy_reason(events[0], re.compile(plan.DEFAULT_IGNORE, re.IGNORECASE)) is None


def test_free_windows_merge_overlaps_and_respect_min(plan, week_payload):
    events, _, _ = plan.load_events(week_payload)
    busy = plan.busy_events(events, re.compile(plan.DEFAULT_IGNORE, re.IGNORECASE))

    windows = plan.free_windows(busy, date(2026, 10, 27), time(8, 30), time(17, 30), 30, TZ)

    assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in windows] == [
        ("08:30", "09:00"),
        ("10:00", "11:00"),
        ("12:00", "17:30"),
    ]
    longer = plan.free_windows(busy, date(2026, 10, 27), time(8, 30), time(17, 30), 61, TZ)
    assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in longer] == [("12:00", "17:30")]


def test_free_window_when_day_is_empty_or_full(plan):
    day = date(2026, 10, 27)
    assert len(plan.free_windows([], day, time(9), time(17), 30, TZ)) == 1
    events, _, _ = plan.load_events(
        {
            "range": {"from": "2026-10-27T00:00:00-04:00", "to": "2026-10-28T00:00:00-04:00"},
            "calendars": [{"alias": "work", "events": [ev("Offsite", "08:00", "18:00")]}],
        }
    )
    assert plan.free_windows(events, day, time(9), time(17), 30, TZ) == []


def test_conflicts_pairs_overlaps_only(plan, week_payload):
    events, _, _ = plan.load_events(week_payload)
    busy = plan.busy_events(events, re.compile(plan.DEFAULT_IGNORE, re.IGNORECASE))

    assert [(a.title, b.title) for a, b in plan.conflicts(busy)] == [("Standup", "Planning")]


def test_days_in_range(plan):
    from datetime import datetime

    start = datetime.fromisoformat("2026-10-26T00:00:00-04:00")
    end = datetime.fromisoformat("2026-10-31T00:00:00-04:00")
    assert [d.isoformat() for d in plan.days_in_range(start, end, TZ)] == [
        "2026-10-26",
        "2026-10-27",
        "2026-10-28",
        "2026-10-29",
        "2026-10-30",
    ]


def test_by_date_shape_is_accepted(plan, week_payload):
    days = {
        "range": week_payload["range"],
        "days": [
            {
                "date": "2026-10-27",
                "events": [
                    {**e, "calendar_alias": cal["alias"]}
                    for cal in week_payload["calendars"]
                    for e in cal["events"]
                ],
            }
        ],
        "errors": [],
    }

    events, _, _ = plan.load_events(days)

    assert {e.calendar for e in events} == {"work", "family"}
    assert len(events) == 7
