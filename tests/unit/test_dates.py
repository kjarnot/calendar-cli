# ABOUTME: Unit tests for date expression and date range parsing.
# ABOUTME: Uses a fixed "now" (Thursday 2026-10-22 15:00 New York) so results are deterministic.
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from calendar_cli.dates import DateParseError, event_times, parse_date, parse_duration, parse_range

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=TZ)


def day(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=TZ)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", day(2026, 10, 22)),
        ("tomorrow", day(2026, 10, 23)),
        ("yesterday", day(2026, 10, 21)),
        ("+3d", day(2026, 10, 25)),
        ("-1w", day(2026, 10, 15)),
        ("+2w", day(2026, 11, 5)),
        ("friday", day(2026, 10, 23)),
        ("Monday", day(2026, 10, 26)),
        ("thursday", day(2026, 10, 29)),  # today's weekday means next week
        ("2026-10-24", day(2026, 10, 24)),
    ],
)
def test_whole_day_expressions(text, expected):
    assert parse_date(text, TZ, NOW) == (expected, False)


def test_iso_datetime_has_time():
    assert parse_date("2026-10-24 14:30", TZ, NOW) == (day(2026, 10, 24, 14, 30), True)
    assert parse_date("2026-10-24T14:30", TZ, NOW) == (day(2026, 10, 24, 14, 30), True)


def test_iso_with_offset_converts_to_config_timezone():
    moment, has_time = parse_date("2026-10-24T18:30:00+00:00", TZ, NOW)

    assert moment == day(2026, 10, 24, 14, 30)
    assert moment.tzinfo == TZ
    assert has_time


def test_bad_date_raises():
    with pytest.raises(DateParseError, match="cannot understand date 'someday'"):
        parse_date("someday", TZ, NOW)


def test_default_range_is_today_plus_seven_days():
    assert parse_range(None, None, TZ, NOW) == (day(2026, 10, 22), day(2026, 10, 29))


def test_whole_day_to_includes_that_day():
    assert parse_range("today", "friday", TZ, NOW) == (day(2026, 10, 22), day(2026, 10, 24))


def test_to_with_time_is_exact():
    assert parse_range("2026-10-22 09:00", "2026-10-22 12:00", TZ, NOW) == (
        day(2026, 10, 22, 9),
        day(2026, 10, 22, 12),
    )


def test_from_only_gives_seven_days():
    assert parse_range("2026-11-01", None, TZ, NOW) == (day(2026, 11, 1), day(2026, 11, 8))


def test_end_before_start_raises():
    with pytest.raises(DateParseError, match="must be after"):
        parse_range("2026-10-22 12:00", "2026-10-22 09:00", TZ, NOW)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("30m", 30), ("1h", 60), ("1h30m", 90), ("2d", 2880), ("1d2h", 1560)],
)
def test_parse_duration(text, minutes):
    assert parse_duration(text).total_seconds() == minutes * 60


@pytest.mark.parametrize("text", ["", "abc", "1x", "h"])
def test_bad_duration(text):
    with pytest.raises(DateParseError, match="cannot understand duration"):
        parse_duration(text)


def test_event_times_timed_defaults_to_one_hour():
    assert event_times("2026-10-24 14:00", None, None, False, TZ, NOW) == (
        day(2026, 10, 24, 14),
        day(2026, 10, 24, 15),
    )


def test_event_times_with_duration_and_end():
    assert event_times("2026-10-24 14:00", None, "45m", False, TZ, NOW)[1] == day(2026, 10, 24, 14, 45)
    assert event_times("2026-10-24 14:00", "2026-10-24 16:30", None, False, TZ, NOW)[1] == day(
        2026, 10, 24, 16, 30
    )


def test_event_times_all_day():
    assert event_times("friday", None, None, True, TZ, NOW) == (day(2026, 10, 23), day(2026, 10, 24))
    assert event_times("2026-10-24", "2026-10-26", None, True, TZ, NOW) == (
        day(2026, 10, 24),
        day(2026, 10, 27),
    )
    assert event_times("2026-10-24", None, "3d", True, TZ, NOW) == (day(2026, 10, 24), day(2026, 10, 27))


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("2026-10-24", None, None, False), "has no time"),
        (("2026-10-24 14:00", "2026-10-24 15:00", "1h", False), "not both"),
        (("2026-10-24 14:00", "2026-10-24", None, False), "--end '2026-10-24' has no time"),
        (("2026-10-24 14:00", "2026-10-24 13:00", None, False), "must end after it starts"),
        (("2026-10-24", None, "36h", True), "whole days"),
    ],
)
def test_event_times_errors(args, message):
    with pytest.raises(DateParseError, match=message):
        event_times(*args, TZ, NOW)
