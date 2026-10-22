# ABOUTME: Parses the date and date-range expressions the CLI accepts (ISO, today, +3d, friday...).
# ABOUTME: All results are timezone-aware datetimes in the configured default timezone.
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
OFFSET_PATTERN = re.compile(r"^([+-])(\d+)([dw])$")
DURATION_PATTERN = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$")
DEFAULT_TIMED_LENGTH = timedelta(hours=1)
DEFAULT_RANGE = timedelta(days=7)


class DateParseError(ValueError):
    """Raised when a date expression cannot be understood."""


def parse_date(text: str, tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime, bool]:
    """Parse a date expression.

    Returns (moment, has_time). has_time is False for whole-day expressions such as
    "today" or "2026-10-24", in which case moment is midnight at the start of that day.
    """
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date()
    value = text.strip().lower()

    if value == "today":
        return _midnight(today, tz), False
    if value == "tomorrow":
        return _midnight(today + timedelta(days=1), tz), False
    if value == "yesterday":
        return _midnight(today - timedelta(days=1), tz), False
    if value in WEEKDAYS:
        days_ahead = (WEEKDAYS.index(value) - today.weekday()) % 7 or 7
        return _midnight(today + timedelta(days=days_ahead), tz), False
    if match := OFFSET_PATTERN.match(value):
        sign, amount, unit = match.groups()
        delta = timedelta(days=int(amount) * (7 if unit == "w" else 1))
        return _midnight(today + delta if sign == "+" else today - delta, tz), False

    try:
        parsed = dateutil_parser.isoparse(text.strip())
    except ValueError:
        raise DateParseError(
            f"cannot understand date {text!r}; use ISO (2026-10-24 or 2026-10-24 14:00), "
            "today, tomorrow, yesterday, a weekday name, or an offset like +3d / -1w"
        ) from None

    has_time = bool(re.search(r"\d[T ]\d", text.strip()))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz), has_time


def parse_range(
    start_text: str | None, end_text: str | None, tz: ZoneInfo, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Resolve --from/--to into a half-open [start, end) range.

    A whole-day --to includes that entire day. Without --to the range is 7 days.
    """
    start, _ = parse_date(start_text, tz, now) if start_text else parse_date("today", tz, now)
    if end_text is None:
        end = start + DEFAULT_RANGE
    else:
        end, has_time = parse_date(end_text, tz, now)
        if not has_time:
            end = _midnight(end.date() + timedelta(days=1), tz)
    if end <= start:
        raise DateParseError(f"--to ({end:%Y-%m-%d %H:%M}) must be after --from ({start:%Y-%m-%d %H:%M})")
    return start, end


def parse_duration(text: str) -> timedelta:
    """Parse durations like 30m, 1h, 1h30m, 2d."""
    match = DURATION_PATTERN.match(text.strip().lower())
    if not text.strip() or match is None or not any(match.groups()):
        raise DateParseError(f"cannot understand duration {text!r}; use forms like 30m, 1h, 1h30m, 2d")
    days, hours, minutes = (int(part or 0) for part in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def event_times(
    start_text: str,
    end_text: str | None,
    duration_text: str | None,
    all_day: bool,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve --start/--end/--duration for a new event.

    Timed events need a start with a time and default to 1 hour. All-day events use whole
    days: a whole-day --end includes that day, and the default is one day.
    """
    if end_text and duration_text:
        raise DateParseError("give --end or --duration, not both")
    start, has_time = parse_date(start_text, tz, now)

    if all_day:
        start = _midnight(start.date(), tz)
        if end_text:
            end = _midnight(parse_date(end_text, tz, now)[0].date() + timedelta(days=1), tz)
        elif duration_text:
            length = parse_duration(duration_text)
            if length % timedelta(days=1):
                raise DateParseError("an all-day event's --duration must be whole days, like 1d or 3d")
            end = start + length
        else:
            end = start + timedelta(days=1)
    else:
        if not has_time:
            raise DateParseError(f"--start {start_text!r} has no time; add one (e.g. 14:00) or use --all-day")
        if end_text:
            end, end_has_time = parse_date(end_text, tz, now)
            if not end_has_time:
                raise DateParseError(f"--end {end_text!r} has no time")
        else:
            end = start + (parse_duration(duration_text) if duration_text else DEFAULT_TIMED_LENGTH)

    if end <= start:
        raise DateParseError("the event must end after it starts")
    return start, end


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)
