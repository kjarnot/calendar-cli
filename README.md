# calendar-cli

Read and write your M365 (work) and Google (personal) calendars from one command line.
Every write is recorded in a journal and can be undone. The full design is in
[docs/SPEC.md](docs/SPEC.md).

| Command | What it does |
|---|---|
| `config` | Validate the config file and show accounts and calendars (secrets hidden) |
| `auth ACCOUNT` | One-time browser sign-in for a Google account |
| `calendars` | List the calendars each account can see, with their IDs |
| `categories` | List the category names `--category` accepts, with their colors |
| `list` | List events in a date range, grouped by calendar |
| `add` | Create an event |
| `update REF` | Change an event's title, time, location, description or category |
| `delete REF` | Delete an event, or a whole recurring series |
| `history` | Show the operation journal, newest first |
| `undo [OP_ID]` | Undo the latest write, or a named one |

Every command accepts `--config PATH`. Add `-v` before the command for a debug-level app
log. `calendar-cli COMMAND --help` shows a command's options.

## JSON output

Put `--json` **after** the command name:

```zsh
calendar-cli list --json
calendar-cli list -c work --from today --to friday --json
calendar-cli categories --json
calendar-cli add "Dentist" -c personal -s "2026-10-24 14:00" --json
```

`--json` works with `list`, `calendars`, `categories`, `add`, `update`, `delete`, `history`
and `undo`. It goes to stdout; errors still go to stderr as text, so the exit code tells you
whether the JSON is a result (`0`) or partial (`2`, with an `error` field per calendar).

| Command | JSON shape |
|---|---|
| `list` | `{"range": {"from", "to"}, "calendars": [{"alias", "provider", "error", "events": [...]}]}` |
| `calendars`, `categories` | `{"<account>": {"calendars" or "categories": [...]}}`, or `{"<account>": {"error": "..."}}` |
| `add`, `update`, `delete`, `undo` | `{"op_id": "...", "event": {...}}` |
| `history` | A list of journal entries, each with `undone_by` |

A quick filter with `jq`:

```zsh
calendar-cli list -c work --json | jq -r '.calendars[0].events[] | "\(.start) \(.title)"'
```

## Setup

1. Install the dependencies (Python 3.13, managed by `uv`):
   ```zsh
   cd ~/Development/Personal/calendar-cli
   uv sync
   ```
2. Optional: put `calendar-cli` on your `PATH` so you can drop `uv run`:
   ```zsh
   uv tool install --editable .
   ```
3. Create the config (see [Configuration](#configuration)) and lock it down:
   ```zsh
   mkdir -p ~/.config/calendar-cli
   $EDITOR ~/.config/calendar-cli/config.toml
   chmod 600 ~/.config/calendar-cli/config.toml
   ```
4. Check it:
   ```zsh
   calendar-cli config
   ```
5. Sign in to each Google account once. A browser window opens; approve access.
   ```zsh
   calendar-cli auth gmail
   ```
   M365 needs no sign-in; it uses the app credentials in the config.
6. Find the IDs of any extra calendars you want, and add them to the config:
   ```zsh
   calendar-cli calendars
   ```

## Configuration

`~/.config/calendar-cli/config.toml` (or `--config PATH`, or `$CALENDAR_CLI_CONFIG`).
It holds secrets, so the CLI refuses to run if its mode is wider than `600`.

```toml
default_timezone = "America/New_York"

# M365: an Azure app registration with the Calendars.ReadWrite application permission.
[accounts.office]
provider = "m365"
tenant_id = "..."
client_id = "..."
client_secret = "..."
user = "me@example.com"

# Google: a Desktop-app OAuth client from Google Cloud Console (Calendar API enabled).
[accounts.gmail]
provider = "google"
client_id = "....apps.googleusercontent.com"
client_secret = "..."

# One entry per calendar. Use "primary" for an account's default calendar,
# or an ID from `calendar-cli calendars`.
[[calendars]]
alias = "work"
account = "office"
calendar_id = "primary"

[[calendars]]
alias = "personal"
account = "gmail"
calendar_id = "primary"

# Google has no categories. These map category names to Google's event colors:
# lavender, sage, grape, flamingo, banana, tangerine, peacock, graphite, blueberry, basil, tomato.
[category_colors]
Exercise = "basil"
```

## Reading calendars

```zsh
calendar-cli list                                   # all calendars, today + 7 days
calendar-cli list -c work                           # one calendar
calendar-cli list -c work -c personal --from tomorrow --to friday
calendar-cli list --from 2026-11-01 --to 2026-11-30 --json
```

Output is grouped by calendar, then by day. Each event gets a short **ref** such as
`work:3`, which `update` and `delete` accept:

```
work (M365 · me@example.com)
  Thu 2026-10-22
    work:1       09:30–10:00    Monthly follow-up
    work:2       12:00–13:30    Workout — Strength  [Exercise]
  Fri 2026-10-23
    work:3       thru Mon 10-26 PTO
```

- Refs come from the most recent `list` and expire after 24 hours. Each `list` replaces them.
- You can always use a full ref instead: `ALIAS:<event id>`, taking the ID from `list --json`.
- If one calendar fails (for example, an expired sign-in), the others still print. The
  error shows under that calendar, and the command exits with code 2.

### Dates

| Form | Example | Meaning |
|---|---|---|
| ISO date | `2026-10-24` | That whole day |
| ISO date and time | `"2026-10-24 14:00"` | That moment |
| Keyword | `today`, `tomorrow`, `yesterday` | That whole day |
| Weekday | `friday` | The next Friday (a week ahead if today is Friday) |
| Offset | `+3d`, `-1w` | Days or weeks from today |

- `--from` defaults to today. `--to` defaults to 7 days after `--from`.
- A whole-day `--to` includes that day: `--from today --to friday` covers through Friday.
- Times without a zone use `default_timezone`.

## Writing events

### Add

```zsh
calendar-cli add "Dentist" -c personal -s "2026-10-24 14:00" -d 45m
calendar-cli add "Workout" -c work -s "2026-10-23 12:00" --category Exercise
calendar-cli add "Trip" -c family -s 2026-11-26 --all-day -d 3d
calendar-cli add "Planning" -c work -s "2026-10-27 10:00" -e "2026-10-27 11:30" \
    -l "Room 4" --description "Q1 roadmap" -a dan@example.com
```

- A timed event needs a start with a time. It lasts 1 hour unless you give `--end` or
  `--duration` (`30m`, `1h30m`, `2d`).
- An all-day event (`--all-day`) lasts 1 day by default. A whole-day `--end` includes that day.
- `--attendee` / `-a` (repeatable) sends real invitations, on both M365 and Google.

### Categories

See which names are valid:

```zsh
calendar-cli categories
```

```
office (m365, from Outlook)
  VIP         dark yellow
  Exercise    orange
  ...
gmail (google, from [category_colors] in config)
  Alex     basil
  Sam     flamingo
  Exercise  sage
```

- **M365:** `--category` must be one of your Outlook categories. An unknown name is
  rejected before anything is written, and the error lists the valid names. The list is read
  live from Outlook, so a category you add in Outlook works right away; nothing to copy into
  the config.
- **Google:** `--category` must be listed under `[category_colors]`. It sets the event's
  color, and `list` shows the color's category name.

### Update

```zsh
calendar-cli update work:3 -s "2026-10-24 15:00"        # moves it, keeping its length
calendar-cli update work:3 -d 90m                         # changes the length
calendar-cli update personal:2 --title "Dentist (moved)" -l "New office"
calendar-cli update work:5 --no-category
```

### Delete

```zsh
calendar-cli delete personal:2
calendar-cli delete work:4 --series        # the whole recurring series
```

- On a recurring event, `delete` removes only that occurrence unless you add `--series`.
- Deleting a meeting someone else organizes is refused. Decline it in Outlook or Google
  Calendar instead.

### Confirmation

`update`, `delete` and `undo` show what will change and ask `Proceed?`. Add `-y` / `--yes`
to skip the question. If the event has attendees, the prompt says they will be emailed.

## History and undo

```zsh
calendar-cli history               # newest first; -n 50 for more, --json for scripts
calendar-cli undo                  # undo the latest write that is not already undone
calendar-cli undo 20261022T184042-f9b9
```

| Undoing a… | Does |
|---|---|
| create | Deletes the event |
| update | Puts back the fields that update changed, and nothing else |
| delete | Restores the event. Google undeletes it with the same ID; M365 recreates it with a new ID |

- Undos are journaled too, and `history` marks which operations were undone.
- An undo cannot itself be undone, and a `--series` delete cannot be undone.
- After an M365 restore, later undos follow the event's new ID automatically.
- Failed writes are journaled with their error and are never undone.
- On M365, undoing a description change puts back plain text, not the original formatting.

## Files

| Path | Holds |
|---|---|
| `~/.config/calendar-cli/config.toml` | Accounts, secrets, calendars (mode `600`) |
| macOS Keychain, service `calendar-cli` | Google sign-in tokens, one per account |
| `~/.local/state/calendar-cli/journal.jsonl` | Every write, with before/after event copies (mode `600`) |
| `~/.local/state/calendar-cli/app.log` | Diagnostic log, rotated at 1 MB (mode `600`) |
| `~/.local/state/calendar-cli/refs.json` | Short refs from the last `list` |

Set `$CALENDAR_CLI_STATE_DIR` to keep state somewhere else.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Your input was wrong, a confirmation was declined, or something was not found |
| 2 | A provider or sign-in error |

## Troubleshooting

| Message | Fix |
|---|---|
| `config file ... has mode 644` | `chmod 600 ~/.config/calendar-cli/config.toml` |
| `Google account 'gmail' is not signed in` | `calendar-cli auth gmail` |
| `Google sign-in ... has expired or was revoked` | `calendar-cli auth gmail`. In Testing mode Google expires tokens after 7 days; publish the OAuth app to stop this |
| `M365 sign-in failed: invalid_client` | The Azure client secret changed or expired; update `client_secret` in the config |
| `unknown M365 category` | Use a name from the list in the error, or create it in Outlook |
| `category ... has no Google color` | Add it under `[category_colors]` |
| `the saved listing is older than 24 hours` | Run `calendar-cli list` again |

## Development

```zsh
uv run pytest                       # unit, integration and offline end-to-end tests
uv run ruff check . && uv run ruff format --check .
```

Live end-to-end tests run the real binary against dedicated test calendars named
"calendar-cli e2e" (one on each account). They create and delete events only there.

```zsh
CALENDAR_CLI_E2E=1 uv run pytest    # everything, including live tests
```

The live tests read `~/.config/calendar-cli/e2e.toml` (or `$CALENDAR_CLI_E2E_CONFIG`). It
holds the same accounts as the main config, the test calendars as `e2e-work` and
`e2e-personal`, and `Exercise = "basil"` under `[category_colors]`.

Code layout:

| Path | Role |
|---|---|
| `src/calendar_cli/cli.py` | Typer commands, prompts and output |
| `src/calendar_cli/operations.py` | Journaled create/update/delete and undo |
| `src/calendar_cli/journal.py` | The append-only operation journal |
| `src/calendar_cli/providers/` | `m365.py` (Graph) and `google.py` (Calendar v3) behind one interface |
| `src/calendar_cli/config.py`, `dates.py`, `models.py`, `output.py`, `state.py`, `tokens.py` | Config, date parsing, data models, rendering, local state, Keychain |
