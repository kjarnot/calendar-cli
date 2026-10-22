# ABOUTME: Typer entry point for the calendar-cli command.
# ABOUTME: Defines global options and the subcommands that read and write calendars.
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from calendar_cli.config import ConfigError, load_config

app = typer.Typer(no_args_is_help=True, help="Read and write M365 and Google calendars.")
out = Console()
err = Console(stderr=True)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Path to config.toml (default: ~/.config/calendar-cli/config.toml)."),
]


@app.callback()
def root() -> None:
    """Read and write M365 and Google calendars."""


@app.command("config")
def show_config(config_path: ConfigOption = None) -> None:
    """Validate the config file and show accounts and calendars (secrets hidden)."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        err.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from None

    out.print(f"default_timezone: {config.default_timezone}")
    out.print("accounts:")
    for name, account in config.accounts.items():
        detail = account.user if account.provider == "m365" else f"client {account.client_id}"
        out.print(f"  {name}  ({account.provider})  {detail}")
    out.print("calendars:")
    for entry in config.calendars:
        out.print(f"  {entry.alias}  -> {entry.account}:{entry.calendar_id}")
    if config.category_colors:
        out.print("category_colors:")
        for category, color in config.category_colors.items():
            out.print(f"  {category} = {color}")
