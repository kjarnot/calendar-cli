# ABOUTME: Renders event listings as grouped plain text or as JSON.
# ABOUTME: Also assigns the short refs (work:1, work:2...) shown next to each event.
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
        index = 1
        for day, day_events in groupby(listing.events, key=lambda e: e.start.date()):
            lines.append(f"  {day:%a %Y-%m-%d}")
            for event in day_events:
                ref = f"{listing.alias}:{index}"
                index += 1
                tags = f"  [{', '.join(event.categories)}]" if event.categories else ""
                lines.append(f"    {ref:<12} {_time_span(event):<12} {event.title}{tags}")
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


def _time_span(event: Event) -> str:
    if event.all_day:
        # All-day ends are exclusive midnights, so the last day is the day before `end`.
        last_day = (event.end - timedelta(days=1)).date()
        return "all day" if last_day <= event.start.date() else f"thru {last_day:%a %m-%d}"
    return f"{event.start:%H:%M}–{event.end:%H:%M}"
