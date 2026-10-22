# ABOUTME: Typer entry point for the calendar-cli command.
# ABOUTME: Defines global options and the subcommands that read and write calendars.
import json
import logging
from pathlib import Path
from typing import Annotated, NoReturn
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.markup import escape

from calendar_cli.config import Config, ConfigError, M365Account, load_config
from calendar_cli.dates import DateParseError, parse_range
from calendar_cli.output import CalendarListing, assign_refs, render_json, render_text
from calendar_cli.providers import CalendarProvider, ProviderError, build_provider
from calendar_cli.state import save_refs, setup_logging

app = typer.Typer(no_args_is_help=True, help="Read and write M365 and Google calendars.")
err = Console(stderr=True)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Path to config.toml (default: ~/.config/calendar-cli/config.toml)."),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Output JSON instead of text.")]

logger = logging.getLogger("calendar_cli")


def fail(message: str, code: int = 1) -> NoReturn:
    """Print an error to stderr and exit. Exit 1 is a user error, 2 a provider/auth error."""
    err.print(f"[red]error:[/red] {escape(message)}")
    raise typer.Exit(code)


def get_config(config_path: Path | None) -> Config:
    try:
        return load_config(config_path)
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
        typer.echo(f"  {entry.alias}  -> {entry.account}:{entry.calendar_id}")
    if config.category_colors:
        typer.echo("category_colors:")
        for category, color in config.category_colors.items():
            typer.echo(f"  {category} = {color}")


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
    config_path: ConfigOption = None,
    as_json: JsonOption = False,
) -> None:
    """List events in a date range, grouped by calendar."""
    config = get_config(config_path)
    try:
        start, end = parse_range(from_, to, ZoneInfo(config.default_timezone))
        entries = [config.calendar(alias) for alias in calendar] if calendar else config.calendars
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
    typer.echo(render_json(listings, start, end) if as_json else render_text(listings))
    if any(listing.error for listing in listings):
        raise typer.Exit(2)
