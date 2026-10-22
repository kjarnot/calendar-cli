# calendar-cli — Specification

A Python command-line tool to read and write the user's work (M365) and personal
(Google) calendars from one place, with a full operation journal and undo.

## 1. Goals

- List events across all configured calendars for a date range, grouped by calendar.
- Output plain text by default; JSON with `--json`.
- Create, update and delete events.
- Support categories: native on M365, mapped to event colors on Google.
- Log every operation, and undo any write.

Out of scope for v1: other providers (iCloud, CalDAV), RSVP/respond, free/busy search,
attachments.

## 2. Commands

The command is `calendar-cli`.

```
calendar-cli auth <account>                 # one-time Google OAuth login (M365 needs none)
calendar-cli calendars [--account NAME]     # list calendars each account can see, with IDs
calendar-cli list [--from DATE] [--to DATE] [--calendar ALIAS ...] [--json]
calendar-cli add TITLE --start DATETIME (--end DATETIME | --duration DUR)
                 --calendar ALIAS [--all-day] [--location TEXT] [--description TEXT]
                 [--category NAME] [--attendee EMAIL ...] [--json]
calendar-cli update REF [--title ...] [--start ...] [--end | --duration ...]
                 [--location ...] [--description ...] [--category NAME | --no-category]
                 [--yes] [--json]
calendar-cli delete REF [--series] [--yes]
calendar-cli history [--limit N] [--json]   # the operation journal, newest first
calendar-cli undo [OP_ID] [--yes]           # undo the latest not-yet-undone op, or a named one
```

### 2.1 Dates and durations

- `--from` defaults to today 00:00; `--to` defaults to `--from` + 7 days.
- Accepted date forms: ISO (`2026-10-24`, `2026-10-24 14:00`), `today`, `tomorrow`,
  relative offsets (`+3d`, `-1w`), weekday names (`friday` = the next Friday).
- Durations: `30m`, `1h`, `1h30m`, `2d`.
- Times without a zone use `default_timezone` from config.

### 2.2 Event references (REF)

Provider event IDs are long. `list` assigns a short ref to each event it prints:
calendar alias prefix + index (for example `work:3`, `personal:7`) and saves the mapping
in the state directory. `update`, `delete` and `get` accept either a short ref or a full
`ALIAS:PROVIDER_ID`. A short ref from a stale listing (older than 24 hours) is rejected
with a message telling the user to run `list` again.

## 3. Configuration

Location: `~/.config/calendar-cli/config.toml` (override with `--config` or
`CALENDAR_CLI_CONFIG`). The file holds secrets, so the CLI refuses to start if its mode
is wider than `600`, and says how to fix it.

```toml
default_timezone = "America/New_York"

[accounts.office]
provider = "m365"
tenant_id = "..."
client_id = "..."
client_secret = "..."
user = "me@example.com"

[accounts.gmail]
provider = "google"
client_secrets_file = "~/.config/calendar-cli/google_client_secret.json"

[[calendars]]
alias = "work"
account = "office"
calendar_id = "primary"

[[calendars]]
alias = "personal"
account = "gmail"
calendar_id = "primary"

# Google has no categories; map category names to Google's 11 event colors.
[category_colors]
Exercise = "basil"
Family = "tangerine"
```

Google color names: lavender, sage, grape, flamingo, banana, tangerine, peacock,
graphite, blueberry, basil, tomato (colorId 1–11).

## 4. Providers

All providers implement one interface:

```python
class CalendarProvider(Protocol):
    def list_calendars(self) -> list[CalendarInfo]: ...
    def list_events(self, calendar_id, start, end) -> list[Event]: ...
    def get_event(self, calendar_id, event_id) -> Event: ...
    def create_event(self, calendar_id, draft: EventDraft) -> Event: ...
    def update_event(self, calendar_id, event_id, changes: EventChanges) -> Event: ...
    def delete_event(self, calendar_id, event_id, series: bool = False) -> None: ...
    def restore_event(self, calendar_id, snapshot: Event) -> Event: ...
```

### 4.1 M365 (Microsoft Graph)

- Auth: reuses the existing Azure app registration (the one behind the office365 MCP
  server). OAuth client-credentials flow via `msal`, scope
  `https://graph.microsoft.com/.default`, **application** permission
  `Calendars.ReadWrite`. No interactive login.
- All calls go to `/users/{user}/...`.
- Listing uses `calendarView` so recurring events expand into occurrences.
- Categories: validated against the mailbox's master category list
  (`/users/{user}/outlook/masterCategories`). An unknown category is rejected with the list
  of valid names.
- Restore: recreate the event from the snapshot. The event gets a new ID.

### 4.2 Google Calendar

- Auth: installed-app OAuth (`google-auth-oauthlib`), scope
  `https://www.googleapis.com/auth/calendar`. Refresh token stored in macOS Keychain via
  `keyring`.
- Listing uses `singleEvents=true` so recurring events expand into occurrences.
- Categories: `--category NAME` sets `colorId` from `[category_colors]`. On read, the
  category is reverse-mapped from `colorId` when a mapping exists. An unmapped category
  is rejected.
- Restore: first try to undelete in place by setting `status` back to `confirmed`
  (keeps the original ID). If that fails, recreate from the snapshot. *To verify during
  implementation that in-place undelete still works.*

## 5. Event model

```
Event: calendar_alias, provider_id, title, start, end, all_day, timezone, location,
       description, categories, attendees, organizer, is_organizer, recurrence
       (series id + whether this is an occurrence), web_link, raw (provider payload)
```

`raw` is kept in snapshots so restore loses as little as possible.

## 6. Output

### 6.1 Text (default)

Grouped by calendar, in config order; events sorted by start; date headers within each
group.

```
work (M365 · me@example.com)
  Thu 2026-10-22
    work:1  09:00–09:30  Leadership sync            [Meetings]
    work:2  12:00–13:00  Workout                    [Exercise]
personal (Google · primary)
  Sat 2026-10-24
    personal:1  all day  Soccer tournament
```

### 6.2 JSON (`--json`)

```json
{
  "range": {"from": "...", "to": "..."},
  "calendars": [
    {"alias": "work", "provider": "m365", "events": [ { ...Event without raw... } ]}
  ]
}
```

Errors go to stderr. Exit codes: 0 success, 1 user error, 2 provider/auth error.

## 7. Logging and undo

Two separate files in `~/.local/state/calendar-cli/` (mode `600`):

- `app.log` — diagnostic log, rotating, INFO by default, DEBUG with `--verbose`. Never
  contains secrets or tokens.
- `journal.jsonl` — append-only operation journal; the source of truth for undo.

### 7.1 Journal entry

```json
{
  "op_id": "20261022T143012-a1b2",
  "timestamp": "2026-10-22T14:30:12-04:00",
  "action": "create | update | delete | undo",
  "calendar": "work",
  "event_id": "...",
  "before": { ...full Event snapshot or null... },
  "after":  { ...full Event snapshot or null... },
  "undoes": "op_id or null",
  "undone_by": null,
  "status": "ok | failed",
  "error": null
}
```

Reads (`list`, `calendars`) are logged to `app.log` only, not to the journal.

### 7.2 Undo rules

| Original action | Undo does | Notes |
|---|---|---|
| create | delete the created event | |
| update | patch the event back to the `before` snapshot fields | Fails safely if the event was deleted since |
| delete | restore from the `before` snapshot | Google: undelete in place; M365: recreate (new ID) |

- `undo` with no argument undoes the newest op that is not already undone.
- An undo is itself journaled (`action: "undo"`, `undoes: <op_id>`) and marks the original
  `undone_by`. An undo cannot itself be undone in v1.
- Undo shows what it will do and asks for confirmation unless `--yes`.
- Undo of a **series** delete is refused in v1 with a clear message.
- When the journal's event ID is stale (for example, an M365 restore produced a new ID),
  the undo entry records the new ID so later operations follow it.

## 8. Safety

- `delete`, `update` and `undo` show the event and ask for confirmation unless `--yes`.
- If the event has attendees, the prompt says invitations/cancellations will be sent.
- Deleting a meeting the user does not organize: M365 declines it with no response message;
  Google removes it from the user's calendar only. Both are stated in the prompt.
- `delete` without `--series` on a recurring occurrence removes only that occurrence.

## 9. Tech stack

- Python ≥ 3.12, managed with `uv`; package `calendar_cli`, src layout.
- Typer (CLI), rich (text output), Pydantic v2 (models), `tomllib` (config),
  `msal` + `httpx` (Graph), `google-api-python-client` + `google-auth-oauthlib` (Google),
  `keyring`, `python-dateutil`.
- pytest, `respx` (mock httpx), ruff.

## 10. Testing

- **Unit** (`tests/unit`): config loading and validation, date/duration parsing, event
  model, text and JSON formatting, journal read/write, undo planning.
- **Integration** (`tests/integration`): each provider against mocked HTTP; the CLI
  wired to a fake in-memory provider, covering list/add/update/delete/undo end to end
  within the process.
- **End-to-end** (`tests/e2e`): the installed `calendar-cli` binary against dedicated
  **test calendars** on both accounts. Skipped unless `CALENDAR_CLI_E2E=1` and an e2e
  config file are present, so real calendars are never touched by accident.

## 11. Open items

1. Google: a Google Cloud OAuth client (Desktop app) must be created, and its JSON saved
   as `client_secrets_file`.
2. Create test calendars ("calendar-cli e2e") on both accounts for end-to-end tests.
3. Confirm the Azure app's application permission is `Calendars.ReadWrite` (setup docs
   say granted).
