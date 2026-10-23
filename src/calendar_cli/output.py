# ABOUTME: Renders event listings as text or JSON, grouped by calendar or by date.
# ABOUTME: Also assigns the short refs (work:1, work:2...) shown next to each event.
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import groupby

from calendar_cli.models import Event


@dataclass
class CalendarListing:
    """One calendar's slice of a `list` result."""

    alias: str
    provider: str
    label: str
    events: list[Event] = field(default_factory=list)
    error: str | None = None


def assign_refs(listings: list[CalendarListing]) -> dict[str, tuple[str, str]]:
    """Sort each calendar's events and number them; return {ref: (alias, provider_id)}."""
    refs: dict[str, tuple[str, str]] = {}
    for listing in listings:
        listing.events.sort(key=lambda e: (e.start, e.end, e.title))
        for index, event in enumerate(listing.events, start=1):
            refs[f"{listing.alias}:{index}"] = (listing.alias, event.provider_id)
    return refs


def render_text(listings: list[CalendarListing]) -> str:
    lines: list[str] = []
    for listing in listings:
        lines.append(f"{listing.alias} ({listing.label})")
        if listing.error:
            lines.append(f"  error: {listing.error}")
            continue
        if not listing.events:
            lines.append("  (no events)")
            continue
        ref_width = max(12, len(f"{listing.alias}:{len(listing.events)}"))
        time_width = max(12, *(len(time_span(e)) for e in listing.events))
        index = 1
        for day, day_events in groupby(listing.events, key=lambda e: e.start.date()):
            lines.append(f"  {day:%a %Y-%m-%d}")
            for event in day_events:
                ref = f"{listing.alias}:{index}"
                index += 1
                tags = f"  [{', '.join(event.categories)}]" if event.categories else ""
                lines.append(f"    {ref:<{ref_width}} {time_span(event):<{time_width}} {event.title}{tags}")
    return "\n".join(lines)


def render_json(listings: list[CalendarListing], start: datetime, end: datetime) -> str:
    payload = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "calendars": [
            {
                "alias": listing.alias,
                "provider": listing.provider,
                "error": listing.error,
                "events": [
                    {"ref": f"{listing.alias}:{i}", **event.model_dump(mode="json")}
                    for i, event in enumerate(listing.events, start=1)
                ],
            }
            for listing in listings
        ],
    }
    return json.dumps(payload, indent=2)


def _dated_rows(listings: list[CalendarListing]) -> list[tuple[str, Event]]:
    """Every event from every calendar as (ref, event), in time order; call after assign_refs."""
    order = {listing.alias: position for position, listing in enumerate(listings)}
    rows = [
        (f"{listing.alias}:{index}", event)
        for listing in listings
        for index, event in enumerate(listing.events, start=1)
    ]
    return sorted(
        rows, key=lambda row: (row[1].start, row[1].end, order[row[1].calendar_alias], row[1].title)
    )


def _day(event: Event, range_start: datetime) -> date:
    """The day an event is listed under: its start, or the range's first day if it began earlier."""
    return max(event.start.date(), range_start.date())


def render_text_by_date(listings: list[CalendarListing], start: datetime) -> str:
    """One section per day, mixing all calendars; failed calendars are listed at the end."""
    rows = _dated_rows(listings)
    lines: list[str] = []
    if rows:
        ref_width = max(12, *(len(ref) for ref, _ in rows))
        time_width = max(12, *(len(time_span(e)) for _, e in rows))
        alias_width = max(len(e.calendar_alias) for _, e in rows)
        for day, day_rows in groupby(rows, key=lambda row: _day(row[1], start)):
            lines.append(f"{day:%a %Y-%m-%d}")
            for ref, event in day_rows:
                tags = f"  [{', '.join(event.categories)}]" if event.categories else ""
                lines.append(
                    f"  {ref:<{ref_width}} {time_span(event):<{time_width}} "
                    f"{event.calendar_alias:<{alias_width}}  {event.title}{tags}"
                )
    else:
        lines.append("(no events)")
    failed = [listing for listing in listings if listing.error]
    if failed:
        lines.append("errors:")
        lines.extend(f"  {listing.alias} ({listing.label}): {listing.error}" for listing in failed)
    return "\n".join(lines)


def render_text_simple(listings: list[CalendarListing], start: datetime) -> str:
    """Day headers and "start–end  title" lines only: no refs, calendar names or categories."""
    rows = _dated_rows(listings)
    if not rows:
        return "(no events)"
    width = max(12, *(len(time_span(e)) for _, e in rows))
    lines: list[str] = []
    for day, day_rows in groupby(rows, key=lambda row: _day(row[1], start)):
        lines.append(f"{day:%a %Y-%m-%d}")
        lines.extend(f"  {time_span(event):<{width}} {event.title}" for _, event in day_rows)
    return "\n".join(lines)


def render_json_by_date(listings: list[CalendarListing], start: datetime, end: datetime) -> str:
    days = [
        {
            "date": day.isoformat(),
            "events": [{"ref": ref, **event.model_dump(mode="json")} for ref, event in day_rows],
        }
        for day, day_rows in groupby(_dated_rows(listings), key=lambda row: _day(row[1], start))
    ]
    payload = {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "days": days,
        "errors": [{"alias": listing.alias, "error": listing.error} for listing in listings if listing.error],
    }
    return json.dumps(payload, indent=2)


def time_span(event: Event) -> str:
    if event.all_day:
        # All-day ends are exclusive midnights, so the last day is the day before `end`.
        last_day = (event.end - timedelta(days=1)).date()
        return "all day" if last_day <= event.start.date() else f"thru {last_day:%a %m-%d}"
    return f"{event.start:%H:%M}–{event.end:%H:%M}"
