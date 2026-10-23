# ABOUTME: Typer entry point for the calendar-cli command.
# ABOUTME: Defines global options and the subcommands that read and write calendars.
import json
import logging
from pathlib import Path
from typing import Annotated, NoReturn
from zoneinfo import ZoneInfo

import typer
from google.auth.exceptions import GoogleAuthError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from rich.console import Console
from rich.markup import escape

from calendar_cli import journal, operations
from calendar_cli.config import CalendarEntry, Config, ConfigError, M365Account, load_config
from calendar_cli.dates import DateParseError, event_times, parse_date, parse_duration, parse_range
from calendar_cli.journal import JournalEntry
from calendar_cli.models import Event, EventChanges, EventDraft
from calendar_cli.operations import describe
from calendar_cli.output import (
    CalendarListing,
    assign_refs,
    render_json,
    render_json_by_date,
    render_text,
    render_text_by_date,
    render_text_simple,
)
from calendar_cli.providers import CalendarProvider, ProviderError, build_provider
from calendar_cli.providers.base import InputError
from calendar_cli.providers.google import sign_in as google_sign_in
from calendar_cli.state import RefError, resolve_ref, save_refs, setup_logging

APP_HELP = """Read and write M365 and Google calendars.

JSON output: add --json after the command, e.g. `calendar-cli list --json`. It works with
list, calendars, categories, add, update, delete, history and undo.

Timezone: add --tz NAME after the command, e.g. `calendar-cli list --tz Europe/London`, to
override default_timezone for that run. It works with list, add, update, delete and undo.

Run `calendar-cli COMMAND --help` for a command's options.
"""
EPILOG = (
    "Examples: calendar-cli list -c work --from today --to friday | "
    "calendar-cli list --json | calendar-cli categories --json"
)

app = typer.Typer(no_args_is_help=True, help=APP_HELP, epilog=EPILOG)
err = Console(stderr=True, soft_wrap=True)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Path to config.toml (default: ~/.config/calendar-cli/config.toml)."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Output JSON instead of text.")]
TzOption = Annotated[
    str | None,
    typer.Option(
        "--tz",
        "--timezone",
        help="Timezone for this run, e.g. Europe/London or UTC; overrides default_timezone in config.",
    ),
]

logger = logging.getLogger("calendar_cli")


def fail(message: str, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit. Exit 1 is a user error, 2 a provider/auth error."""
    err.print(f"[red]error:[/red] {escape(message)}")
    raise typer.Exit(code)


def get_config(config_path: Path | None, timezone: str | None = None) -> Config:
    try:
        return load_config(config_path).with_timezone(timezone)
    except ConfigError as exc:
        fail(str(exc))


class ProviderCache:
    """Creates one provider per account, on first use."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._providers: dict[str, CalendarProvider] = {}

    def get(self, account_name: str) -> CalendarProvider:
        if account_name not in self._providers:
            self._providers[account_name] = build_provider(self.config, account_name)
        return self._providers[account_name]


def calendar_label(config: Config, account_name: str, calendar_id: str) -> str:
    account = config.accounts[account_name]
    if isinstance(account, M365Account):
        where = account.user if calendar_id == "primary" else f"{account.user} · {calendar_id[-12:]}"
        return f"M365 · {where}"
    return f"Google · {calendar_id}"


@app.callback()
def root(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug-level app log.")] = False,
) -> None:
    """Read and write M365 and Google calendars."""
    setup_logging(verbose)


@app.command("config")
def show_config(config_path: ConfigOption = None) -> None:
    """Validate the config file and show accounts and calendars (secrets hidden)."""
    config = get_config(config_path)

    typer.echo(f"default_timezone: {config.default_timezone}")
    typer.echo("accounts:")
    for name, account in config.accounts.items():
        detail = account.user if account.provider == "m365" else f"client {account.client_id}"
        typer.echo(f"  {name}  ({account.provider})  {detail}")
    typer.echo("calendars:")
    for entry in config.calendars:
        profile = f"  (profile: {entry.profile})" if entry.profile else ""
        typer.echo(f"  {entry.alias}  -> {entry.account}:{entry.calendar_id}{profile}")
    if config.category_colors:
        typer.echo("category_colors:")
        for category, color in config.category_colors.items():
            typer.echo(f"  {category} = {color}")


@app.command("auth")
def auth(
    account: Annotated[str, typer.Argument(help="Account name from config, e.g. gmail.")],
    config_path: ConfigOption = None,
) -> None:
    """Sign in to a Google account in the browser and store the token in the Keychain."""
    config = get_config(config_path)
    if account not in config.accounts:
        fail(f"unknown account {account!r}; configured: {', '.join(config.accounts)}")
    settings = config.accounts[account]
    if isinstance(settings, M365Account):
        typer.echo(f"{account} is an M365 account; it uses app credentials from config and needs no sign-in.")
        return

    typer.echo("Opening your browser to sign in to Google...")
    try:
        google_sign_in(account, settings)
        primary = [c for c in build_provider(config, account).list_calendars() if c.is_default]
    except ProviderError as exc:
        fail(str(exc), code=2)
    except (OAuth2Error, GoogleAuthError, OSError) as exc:
        logger.warning("auth %s failed: %s", account, exc)
        fail(f"Google sign-in failed: {exc}", code=2)
    logger.info("auth %s: signed in", account)
    who = primary[0].calendar_id if primary else "(no primary calendar found)"
    typer.echo(f"Signed in to {account} as {who}. Token saved in the macOS Keychain.")


@app.command("calendars")
def list_calendars(
    account: Annotated[str | None, typer.Option("--account", help="Only this account.")] = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """List the calendars each account can see, with the IDs to put in config."""
    config = get_config(config_path)
    if account is not None and account not in config.accounts:
        fail(f"unknown account {account!r}; configured: {', '.join(config.accounts)}")
    names = [account] if account else list(config.accounts)
    providers = ProviderCache(config)

    results: dict[str, list[dict] | str] = {}
    for name in names:
        try:
            results[name] = [c.model_dump() for c in providers.get(name).list_calendars()]
        except ProviderError as exc:
            results[name] = str(exc)
            logger.warning("calendars %s failed: %s", name, exc)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    name: ({"error": r} if isinstance(r, str) else {"calendars": r})
                    for name, r in results.items()
                },
                indent=2,
            )
        )
    else:
        for name, result in results.items():
            typer.echo(f"{name} ({config.accounts[name].provider})")
            if isinstance(result, str):
                typer.echo(f"  error: {result}")
                continue
            for cal in result:
                flags = ", ".join(
                    f for f, on in (("default", cal["is_default"]), ("read-only", not cal["can_edit"])) if on
                )
                typer.echo(f"  {cal['name']}{f'  ({flags})' if flags else ''}")
                typer.echo(f"    id: {cal['calendar_id']}")
    if any(isinstance(r, str) for r in results.values()):
        raise typer.Exit(2)


@app.command("categories")
def list_categories(
    account: Annotated[str | None, typer.Option("--account", help="Only this account.")] = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """List the category names --category accepts: live from Outlook for M365, from config for Google."""
    config = get_config(config_path)
    if account is not None and account not in config.accounts:
        fail(f"unknown account {account!r}; configured: {', '.join(config.accounts)}")
    names = [account] if account else list(config.accounts)
    providers = ProviderCache(config)

    results: dict[str, list[dict] | str] = {}
    for name in names:
        try:
            results[name] = [c.model_dump() for c in providers.get(name).list_categories()]
        except ProviderError as exc:
            results[name] = str(exc)
            logger.warning("categories %s failed: %s", name, exc)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    name: (
                        {"error": r}
                        if isinstance(r, str)
                        else {"provider": config.accounts[name].provider, "categories": r}
                    )
                    for name, r in results.items()
                },
                indent=2,
            )
        )
    else:
        for name, result in results.items():
            provider = config.accounts[name].provider
            source = "from Outlook" if provider == "m365" else "from [category_colors] in config"
            typer.echo(f"{name} ({provider}, {source})")
            if isinstance(result, str):
                typer.echo(f"  error: {result}")
            elif not result:
                typer.echo("  (none)")
            else:
                width = max(len(c["name"]) for c in result)
                for category in result:
                    typer.echo(f"  {category['name']:<{width}}  {category['color'] or ''}".rstrip())
    if any(isinstance(r, str) for r in results.values()):
        raise typer.Exit(2)


@app.command("list")
def list_events(
    from_: Annotated[
        str | None,
        typer.Option("--from", help="Start: ISO date/time, today, +3d, friday... (default today)."),
    ] = None,
    to: Annotated[
        str | None,
        typer.Option("--to", help="End; a whole-day value includes that day (default from + 7 days)."),
    ] = None,
    calendar: Annotated[
        list[str] | None,
        typer.Option("--calendar", "-c", help="Calendar alias; repeat for several (default all)."),
    ] = None,
    profile: Annotated[
        list[str] | None,
        typer.Option("--profile", "-p", help="Calendars with this profile in config; repeat for several."),
    ] = None,
    by_date: Annotated[
        bool, typer.Option("--by-date", help="Group by day across all calendars instead of by calendar.")
    ] = False,
    simple: Annotated[
        bool,
        typer.Option("--simple", help="Plain day-by-day list of times and titles only (implies --by-date)."),
    ] = False,
    timezone: TzOption = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """List events in a date range, grouped by calendar (or by day with --by-date)."""
    config = get_config(config_path, timezone)
    if simple and as_json:
        fail("--simple is a text format; use --simple or --json, not both")
    try:
        start, end = parse_range(from_, to, ZoneInfo(config.default_timezone))
        entries = config.select_calendars(calendar, profile)
    except (DateParseError, ConfigError) as exc:
        fail(str(exc))

    providers = ProviderCache(config)
    listings: list[CalendarListing] = []
    for entry in entries:
        listing = CalendarListing(
            alias=entry.alias,
            provider=config.accounts[entry.account].provider,
            label=calendar_label(config, entry.account, entry.calendar_id),
        )
        try:
            listing.events = providers.get(entry.account).list_events(
                entry.alias, entry.calendar_id, start, end
            )
            logger.info(
                "list %s %s..%s: %d events",
                entry.alias,
                start.isoformat(),
                end.isoformat(),
                len(listing.events),
            )
        except ProviderError as exc:
            listing.error = str(exc)
            logger.warning("list %s failed: %s", entry.alias, exc)
        listings.append(listing)

    save_refs(assign_refs(listings))
    if simple:
        typer.echo(render_text_simple(listings, start))
        for listing in listings:
            if listing.error:
                err.print(f"[red]error:[/red] {escape(listing.alias)}: {escape(listing.error)}")
    elif by_date:
        typer.echo(
            render_json_by_date(listings, start, end) if as_json else render_text_by_date(listings, start)
        )
    else:
        typer.echo(render_json(listings, start, end) if as_json else render_text(listings))
    if any(listing.error for listing in listings):
        raise typer.Exit(2)


def resolve_event(config: Config, ref: str) -> tuple[CalendarEntry, str]:
    """Turn a short ref (work:3) or full ref (work:<provider id>) into (calendar, event id)."""
    alias, sep, rest = ref.partition(":")
    if not sep or not rest:
        fail(f"event ref {ref!r} must look like work:3 (from `list`) or work:<event id>")
    try:
        if rest.isdigit():
            alias, event_id = resolve_ref(ref)
        else:
            event_id = rest
        return config.calendar(alias), event_id
    except (RefError, ConfigError) as exc:
        fail(str(exc))


def confirm(lines: list[str], yes: bool, as_json: bool) -> None:
    # With --json, the summary and prompt go to stderr so stdout stays valid JSON.
    for line in lines:
        typer.echo(line, err=as_json)
    if not yes and not typer.confirm("Proceed?", default=False, err=as_json):
        fail("cancelled; nothing was changed")


def attendee_warning(event: Event, what: str) -> list[str]:
    if not event.attendees:
        return []
    return [f"  note: {len(event.attendees)} attendee(s) will be sent {what}."]


def emit_write(as_json: bool, verb: str, entry: JournalEntry, event: Event | None) -> None:
    if as_json:
        typer.echo(
            json.dumps(
                {"op_id": entry.op_id, "event": event.model_dump(mode="json") if event else None}, indent=2
            )
        )
    else:
        typer.echo(f"{verb}: {describe(event) if event else entry.title}  (op {entry.op_id})")


@app.command("add")
def add_event(
    title: Annotated[str, typer.Argument(help="Event title.")],
    calendar: Annotated[str, typer.Option("--calendar", "-c", help="Calendar alias.")],
    start: Annotated[
        str, typer.Option("--start", "-s", help="Start, e.g. '2026-10-24 14:00' or friday with --all-day.")
    ],
    end: Annotated[
        str | None, typer.Option("--end", "-e", help="End (default: start + 1h, or 1 day if --all-day).")
    ] = None,
    duration: Annotated[
        str | None, typer.Option("--duration", "-d", help="Length instead of --end: 30m, 1h30m, 2d.")
    ] = None,
    all_day: Annotated[bool, typer.Option("--all-day", help="Whole-day event.")] = False,
    location: Annotated[str | None, typer.Option("--location", "-l")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    category: Annotated[
        str | None, typer.Option("--category", help="M365 category, or a [category_colors] name on Google.")
    ] = None,
    attendee: Annotated[
        list[str] | None, typer.Option("--attendee", "-a", help="Invitee email; repeat for several.")
    ] = None,
    timezone: TzOption = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """Create an event."""
    config = get_config(config_path, timezone)
    try:
        cal = config.calendar(calendar)
        start_at, end_at = event_times(start, end, duration, all_day, ZoneInfo(config.default_timezone))
    except (ConfigError, DateParseError) as exc:
        fail(str(exc))
    draft = EventDraft(
        title=title,
        start=start_at,
        end=end_at,
        all_day=all_day,
        location=location,
        description=description,
        categories=[category] if category else [],
        attendees=attendee or [],
    )
    try:
        event, entry = operations.create(
            ProviderCache(config).get(cal.account), cal, draft, config.default_timezone
        )
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)
    emit_write(as_json, "Created", entry, event)


@app.command("update")
def update_event(
    ref: Annotated[str, typer.Argument(help="Event ref from `list` (work:3) or alias:<event id>.")],
    title: Annotated[str | None, typer.Option("--title", "-t")] = None,
    start: Annotated[
        str | None, typer.Option("--start", "-s", help="New start; keeps the length unless --end/--duration.")
    ] = None,
    end: Annotated[str | None, typer.Option("--end", "-e")] = None,
    duration: Annotated[str | None, typer.Option("--duration", "-d")] = None,
    location: Annotated[str | None, typer.Option("--location", "-l")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    category: Annotated[str | None, typer.Option("--category")] = None,
    no_category: Annotated[bool, typer.Option("--no-category", help="Remove the category.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    timezone: TzOption = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """Change an event's title, time, location, description or category."""
    config = get_config(config_path, timezone)
    if category and no_category:
        fail("give --category or --no-category, not both")
    if end and duration:
        fail("give --end or --duration, not both")
    cal, event_id = resolve_event(config, ref)
    provider = ProviderCache(config).get(cal.account)
    try:
        current = provider.get_event(cal.alias, cal.calendar_id, event_id)
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)

    fields: dict = {}
    tz = ZoneInfo(config.default_timezone)
    try:
        new_start = parse_date(start, tz)[0] if start else current.start
        if start or end or duration:
            if end:
                new_end = parse_date(end, tz)[0]
            elif duration:
                new_end = new_start + parse_duration(duration)
            else:
                new_end = new_start + (current.end - current.start)
            if new_end <= new_start:
                raise DateParseError("the event must end after it starts")
            fields.update(start=new_start, end=new_end)
    except DateParseError as exc:
        fail(str(exc))
    if title is not None:
        fields["title"] = title
    if location is not None:
        fields["location"] = location
    if description is not None:
        fields["description"] = description
    if category or no_category:
        fields["categories"] = [category] if category else []
    if not fields:
        fail(
            "nothing to change; give at least one of --title, --start, --end, --duration, --location, --description, --category, --no-category"
        )

    changes = EventChanges(**fields)
    lines = [f"Update {describe(current)}"]
    lines += [f"  {name}: {getattr(current, name)!s} -> {value!s}" for name, value in fields.items()]
    confirm(lines + attendee_warning(current, "an update"), yes, as_json)
    try:
        event, entry = operations.update(provider, cal, current, changes, config.default_timezone)
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)
    emit_write(as_json, "Updated", entry, event)


@app.command("delete")
def delete_event(
    ref: Annotated[str, typer.Argument(help="Event ref from `list` (work:3) or alias:<event id>.")],
    series: Annotated[
        bool, typer.Option("--series", help="Delete the whole recurring series, not just this occurrence.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    timezone: TzOption = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """Delete an event (or, with --series, its whole recurring series)."""
    config = get_config(config_path, timezone)
    cal, event_id = resolve_event(config, ref)
    provider = ProviderCache(config).get(cal.account)
    try:
        target = provider.get_event(cal.alias, cal.calendar_id, event_id)
        if series:
            if not target.series_id:
                fail(f"{describe(target)} is not part of a recurring series")
            target = provider.get_event(cal.alias, cal.calendar_id, target.series_id)
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)

    if not target.is_organizer:
        fail(
            f"you are not the organizer of {describe(target)} ({target.organizer}); "
            "decline it in Outlook or Google Calendar instead"
        )
    lines = [f"Delete {'the whole series of ' if series else ''}{describe(target)}"]
    if series:
        lines.append("  note: undo cannot restore a deleted series.")
    elif target.is_occurrence:
        lines.append("  note: only this occurrence is deleted; use --series for the whole series.")
    confirm(lines + attendee_warning(target, "a cancellation"), yes, as_json)
    try:
        entry = operations.delete(provider, cal, target, series, config.default_timezone)
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)
    emit_write(as_json, "Deleted", entry, target)


@app.command("history")
def show_history(
    limit: Annotated[int, typer.Option("--limit", "-n", help="How many entries to show.")] = 20,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show the operation journal, newest first."""
    # The journal does not depend on config; --config is accepted so every command takes it.
    del config_path
    entries = journal.read_all()
    done = journal.undone_ops(entries)
    recent = list(reversed(entries))[:limit]
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {**e.model_dump(mode="json", exclude={"before", "after"}), "undone_by": done.get(e.op_id)}
                    for e in recent
                ],
                indent=2,
            )
        )
        return
    if not recent:
        typer.echo("(no operations yet)")
        return
    for e in recent:
        note = f"undone by {done[e.op_id]}" if e.op_id in done else ""
        if e.action == "undo":
            note = f"undoes {e.undoes}"
        if e.status == "failed":
            note = f"FAILED: {e.error}"
        typer.echo(
            f"{e.op_id}  {e.timestamp:%Y-%m-%d %H:%M}  {e.action:<6}  {e.calendar:<10}  {e.title}  {note}".rstrip()
        )


@app.command("undo")
def undo_operation(
    op_id: Annotated[
        str | None, typer.Argument(help="Operation to undo (default: the latest not yet undone).")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    timezone: TzOption = None,
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """Undo a create, update or delete from the journal."""
    config = get_config(config_path, timezone)
    entries = journal.read_all()
    try:
        target = journal.find_undo_target(entries, op_id)
        plan = operations.undo_plan(target)
        cal = config.calendar(target.calendar)
    except (LookupError, operations.UndoError, ConfigError) as exc:
        fail(str(exc))
    snapshot = target.after_event() or target.before_event()
    what = "a new invitation" if target.action == "delete" else "an update"
    confirm([f"Undo {target.action} {target.op_id}: {plan}"] + attendee_warning(snapshot, what), yes, as_json)
    try:
        event, entry = operations.undo(
            ProviderCache(config).get(cal.account),
            cal,
            target,
            config.default_timezone,
            journal.current_event_id(entries, target.event_id),
        )
    except InputError as exc:
        fail(str(exc))
    except ProviderError as exc:
        fail(str(exc), code=2)
    emit_write(as_json, "Undone", entry, event)
