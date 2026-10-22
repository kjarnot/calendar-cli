# ABOUTME: Parses the date and date-range expressions the CLI accepts (ISO, today, +3d, friday...).
# ABOUTME: All results are timezone-aware datetimes in the configured default timezone.
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
OFFSET_PATTERN = re.compile(r"^([+-])(\d+)([dw])$")
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


def _midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)
