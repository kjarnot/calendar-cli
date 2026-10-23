#!/usr/bin/env python3
# ABOUTME: Planning math over `calendar-cli list --json` output: free windows, conflicts and daily load.
# ABOUTME: Standard library only; decides which events count as the user's busy time.
"""Usage:
    calendar-cli list -p work -p personal --from monday --to friday --json > events.json
    python3 plan.py free events.json --day-start 08:30 --day-end 17:30 --min 60
    python3 plan.py conflicts events.json
    python3 plan.py load events.json

Busy rules (shared with the weekly-training-plan skill):
  * all-day events never block time (holidays, PTO, multi-day trips are context only);
  * "Canceled:" events don't block time;
  * a colleague's availability notice sent as an invite (their PTO / vacation /
    appointment / OOO, where the user is not the organizer) doesn't block time;
  * events whose titles match --ignore-title (for example other family members'
    names on a shared family calendar) are their plans, not the user's busy time.
    No titles are ignored unless --ignore-title is given.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CANCELED = re.compile(r"^cancel+ed:", re.IGNORECASE)
COLLEAGUE_NOTICE = re.compile(r"appointment|vacation|\bpto\b|\booo\b|out of (the )?office", re.IGNORECASE)


@dataclass
class Event:
    calendar: str
    ref: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    is_organizer: bool
    attendees: int


def load_events(payload: dict) -> tuple[list[Event], datetime, datetime]:
    """Accept either list shape (by calendar, or --by-date) and return events plus the range."""
    raw: list[tuple[str, dict]] = []
    if "calendars" in payload:
        for cal in payload["calendars"]:
            raw.extend((cal["alias"], e) for e in cal["events"])
    else:
        for day in payload.get("days", []):
            raw.extend((e["calendar_alias"], e) for e in day["events"])
    events = [
        Event(
            calendar=alias,
            ref=e.get("ref", ""),
            title=e["title"],
            start=datetime.fromisoformat(e["start"]),
            end=datetime.fromisoformat(e["end"]),
            all_day=e.get("all_day", False),
            is_organizer=e.get("is_organizer", True),
            attendees=len(e.get("attendees", [])),
        )
        for alias, e in raw
    ]
    events.sort(key=lambda e: (e.start, e.end))
    rng = payload["range"]
    return events, datetime.fromisoformat(rng["from"]), datetime.fromisoformat(rng["to"])


def not_busy_reason(event: Event, ignore: re.Pattern) -> str | None:
    """Why an event does not block the user's time, or None if it does."""
    if event.all_day:
        return "all-day"
    if CANCELED.search(event.title):
        return "canceled"
    if not event.is_organizer and COLLEAGUE_NOTICE.search(event.title):
        return "colleague notice"
    if ignore.search(event.title):
        return "family member's event"
    return None


def busy_events(events: list[Event], ignore: re.Pattern) -> list[Event]:
    return [e for e in events if not_busy_reason(e, ignore) is None]


def days_in_range(start: datetime, end: datetime, tz: ZoneInfo) -> list[date]:
    first, last = start.astimezone(tz).date(), (end.astimezone(tz) - timedelta(microseconds=1)).date()
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def merged_intervals(events: list[Event]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for e in sorted(events, key=lambda e: e.start):
        if merged and e.start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e.end))
        else:
            merged.append((e.start, e.end))
    return merged


def free_windows(
    busy: list[Event], day: date, day_start: time, day_end: time, min_minutes: int, tz: ZoneInfo
):
    """Free [start, end) windows inside the working day that last at least min_minutes."""
    window_start = datetime.combine(day, day_start, tzinfo=tz)
    window_end = datetime.combine(day, day_end, tzinfo=tz)
    cursor, windows = window_start, []
    for b0, b1 in merged_intervals([e for e in busy if e.end > window_start and e.start < window_end]):
        if b0 > cursor:
            windows.append((cursor, min(b0, window_end)))
        cursor = max(cursor, b1)
    if cursor < window_end:
        windows.append((cursor, window_end))
    return [(s, e) for s, e in windows if (e - s) >= timedelta(minutes=min_minutes)]


def conflicts(busy: list[Event]) -> list[tuple[Event, Event]]:
    """Every pair of busy events that overlap in time."""
    pairs = []
    for i, a in enumerate(busy):
        for b in busy[i + 1 :]:
            if b.start >= a.end:
                break
            pairs.append((a, b))
    return pairs


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def fmt(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def label(e: Event) -> str:
    return f"{e.title} ({e.calendar}{', ' + e.ref if e.ref else ''})"


def cmd_free(args, events, start, end, tz, ignore) -> dict:
    busy = busy_events(events, ignore)
    out = []
    for day in days_in_range(start, end, tz):
        if args.weekdays and day.weekday() >= 5:
            continue
        wins = free_windows(busy, day, args.day_start, args.day_end, args.min, tz)
        out.append(
            {
                "date": day.isoformat(),
                "free": [
                    {"start": fmt(s, tz), "end": fmt(e, tz), "minutes": minutes(e - s)} for s, e in wins
                ],
            }
        )
    return {"window": f"{args.day_start:%H:%M}-{args.day_end:%H:%M}", "min_minutes": args.min, "days": out}


def cmd_conflicts(args, events, start, end, tz, ignore) -> dict:
    found = []
    for a, b in conflicts(busy_events(events, ignore)):
        kind = "work/personal clash" if (a.calendar == "work") != (b.calendar == "work") else "double-booked"
        found.append(
            {
                "date": a.start.astimezone(tz).date().isoformat(),
                "kind": kind,
                "overlap_minutes": minutes(min(a.end, b.end) - max(a.start, b.start)),
                "a": {
                    "title": a.title,
                    "calendar": a.calendar,
                    "ref": a.ref,
                    "time": f"{fmt(a.start, tz)}-{fmt(a.end, tz)}",
                },
                "b": {
                    "title": b.title,
                    "calendar": b.calendar,
                    "ref": b.ref,
                    "time": f"{fmt(b.start, tz)}-{fmt(b.end, tz)}",
                },
            }
        )
    return {"conflicts": found}


def cmd_load(args, events, start, end, tz, ignore) -> dict:
    busy = busy_events(events, ignore)
    out = []
    for day in days_in_range(start, end, tz):
        lo = datetime.combine(day, time.min, tzinfo=tz)
        hi = lo + timedelta(days=1)
        todays = [e for e in busy if e.start < hi and e.end > lo]
        intervals = merged_intervals(todays)
        booked = sum((min(b1, hi) - max(b0, lo) for b0, b1 in intervals), timedelta())
        longest = max((min(b1, hi) - max(b0, lo) for b0, b1 in intervals), default=timedelta())
        context = [
            {"title": e.title, "calendar": e.calendar, "why": not_busy_reason(e, ignore)}
            for e in events
            if e.start < hi and e.end > lo and not_busy_reason(e, ignore)
        ]
        out.append(
            {
                "date": day.isoformat(),
                "busy_events": len(todays),
                "booked_minutes": minutes(booked),
                "first": fmt(todays[0].start, tz) if todays else None,
                "last_end": fmt(max(e.end for e in todays), tz) if todays else None,
                "longest_unbroken_minutes": minutes(longest),
                "context": context,
            }
        )
    return {"days": out}


def render_text(command: str, result: dict) -> str:
    lines: list[str] = []
    if command == "free":
        lines.append(f"Free windows {result['window']}, at least {result['min_minutes']} min:")
        for d in result["days"]:
            day = date.fromisoformat(d["date"])
            spans = ", ".join(f"{w['start']}–{w['end']} ({w['minutes']}m)" for w in d["free"]) or "none"
            lines.append(f"  {day:%a %Y-%m-%d}  {spans}")
    elif command == "conflicts":
        if not result["conflicts"]:
            lines.append("No conflicts.")
        for c in result["conflicts"]:
            lines.append(
                f"  {c['date']}  {c['kind']}, {c['overlap_minutes']}m overlap: "
                f"{c['a']['time']} {c['a']['title']} [{c['a']['calendar']}] × "
                f"{c['b']['time']} {c['b']['title']} [{c['b']['calendar']}]"
            )
    else:
        for d in result["days"]:
            day = date.fromisoformat(d["date"])
            hours = d["booked_minutes"] / 60
            span = f"{d['first']}–{d['last_end']}" if d["first"] else "nothing booked"
            lines.append(
                f"  {day:%a %Y-%m-%d}  {d['busy_events']} events, {hours:.1f}h booked, {span}, "
                f"longest unbroken {d['longest_unbroken_minutes']}m"
            )
            lines.extend(f"      context: {c['title']} [{c['calendar']}] ({c['why']})" for c in d["context"])
    return "\n".join(lines)


def parse_hhmm(text: str) -> time:
    return datetime.strptime(text, "%H:%M").time()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning math over calendar-cli list --json output.")
    parser.add_argument("command", choices=["free", "conflicts", "load"])
    parser.add_argument("input", help="calendar-cli list --json output file, or - for stdin")
    parser.add_argument("--tz", default="America/New_York")
    parser.add_argument("--ignore-title", default="", help="regex; matching titles are not busy")
    parser.add_argument("--day-start", type=parse_hhmm, default=time(8, 0))
    parser.add_argument("--day-end", type=parse_hhmm, default=time(18, 0))
    parser.add_argument("--min", type=int, default=30, help="shortest free window to report, in minutes")
    parser.add_argument("--weekdays", action="store_true", help="free: skip Saturday and Sunday")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.input == "-":
        payload = json.load(sys.stdin)
    else:
        with open(args.input) as handle:
            payload = json.load(handle)
    tz = ZoneInfo(args.tz)
    ignore = re.compile(args.ignore_title, re.IGNORECASE) if args.ignore_title else re.compile(r"(?!)")
    events, start, end = load_events(payload)
    handler = {"free": cmd_free, "conflicts": cmd_conflicts, "load": cmd_load}[args.command]
    result = handler(args, events, start, end, tz, ignore)
    print(json.dumps(result, indent=2) if args.json else render_text(args.command, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
