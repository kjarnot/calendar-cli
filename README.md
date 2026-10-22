# calendar-cli

Read and write M365 (work) and Google (personal) calendars from the command line, with an
operation journal and undo. See [docs/SPEC.md](docs/SPEC.md) for the full design.

## Setup

```zsh
uv sync
mkdir -p ~/.config/calendar-cli
$EDITOR ~/.config/calendar-cli/config.toml   # see docs/SPEC.md §3
chmod 600 ~/.config/calendar-cli/config.toml
uv run calendar-cli config                   # validates the config
```

## Tests

```zsh
uv run pytest                 # unit, integration and end-to-end (temp configs only)
CALENDAR_CLI_E2E=1 uv run pytest tests/e2e   # adds tests against the real test calendars
```
