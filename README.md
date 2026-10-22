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

## Usage

```zsh
calendar-cli calendars                       # calendar IDs each account can see
calendar-cli list                            # all calendars, today + 7 days
calendar-cli list -c work --from today --to friday
calendar-cli list --json
```

## Tests

```zsh
uv run pytest                 # unit, integration and end-to-end (temp configs only)
CALENDAR_CLI_E2E=1 uv run pytest tests/e2e   # adds live tests against the "calendar-cli e2e" calendars
                                             # (config: ~/.config/calendar-cli/e2e.toml)
```
