# ABOUTME: calendar-cli package: read and write M365 and Google calendars from the command line.
# ABOUTME: Exposes main(), the console-script entry point.
from calendar_cli.cli import app


def main() -> None:
    app()
