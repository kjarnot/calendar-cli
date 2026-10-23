---
name: calendar-cli
description: Look up, add, move, change, delete and undo single events on the user's work (M365) and personal/family (Google) calendars with calendar-cli. Use this whenever the user asks things like "what's on my calendar tomorrow", "when is my dentist appointment", "add lunch with Dan Friday at noon", "put Sam's recital on the family calendar", "move my 3 pm to 4", "push the budget review to next week", "rename that block", "tag it Focus time", "cancel my haircut", "delete that block", "undo that", or "what did you change on my calendar" — any direct calendar edit or lookup, even if he doesn't say "calendar". Planning questions (free time, time-blocking a to-do list, conflicts, week overviews) belong to the calendar-planning skill; workout blocks belong to weekly-training-plan.
---

# calendar-cli

Do one calendar job for the user: find an event, or add, change, delete or undo one. Every
write is journaled and can be undone, but changes to events with attendees email real
people, so read before you write and confirm before anything that touches others.

If the request is really "when should this happen" (free time, fitting tasks in,
conflicts, the shape of the week), use the **calendar-planning** skill instead. Workout
blocks are the **weekly-training-plan** skill's job.

## Calendars

**First read `local.md` next to this file, if it exists.** It holds this user's real
details, kept out of the repo: how to address him, his actual calendar aliases (they
replace the generic ones below), family members' names, and his title conventions.
Without it, run `calendar-cli config` to see the configured calendars.

| Alias | What it is | Profile |
|---|---|---|
| `work` | Work M365 calendar | `work` |
| `personal` | The user's own Google calendar | `personal` |
| `family` | Shared family Google calendar | `personal` |

Which calendar to write to when he doesn't say:
- Work meetings, work tasks, focus time → `work`.
- His own appointments and errands (dentist, haircut, car service) → `personal`.
- Things the family shares or other family members do (trips, school events, family
  members' appointments) → `family`.
- Genuinely unclear → ask.

`calendar-cli COMMAND --help` and `~/Development/Personal/calendar-cli/README.md` cover
every option.

## Dates and times

- ISO (`2026-10-24`, `"2026-10-24 14:00"`), `today`, `tomorrow`, `yesterday`, weekday
  names (`friday` = the next Friday), offsets (`+3d`, `-1w`).
- A weekday or keyword cannot take a time. For a timed start, work out the ISO date
  yourself: "Friday at noon" → `-s "2026-10-30 12:00"`. Check the weekday against today's
  date before you write it.
- `--to` on a whole day includes that day. `--from` defaults to today, `--to` to 7 days
  later.
- Times are America/New_York. For another zone ("3 pm London time"), add `--tz
  Europe/London` to that command; it changes both the input and the output times.

## Find an event

```zsh
calendar-cli list -p work --from tomorrow --to tomorrow --json
calendar-cli list --from today --to +30d --json          # all calendars
calendar-cli list -c family --from 2026-11-01 --to 2026-11-30 --json
```

- Always use `--json` and read the events from it; don't parse the text view. Each event
  has `ref`, `title`, `start`, `end`, `all_day`, `location`, `categories`, `attendees`,
  `organizer`, `is_organizer`, `series_id` and `is_occurrence`.
- Searching by name ("when is my dentist appointment"): list a generous range (30–60
  days) across all calendars and match titles case-insensitively. If more than one
  matches, show them and ask which.
- To show the user a day, answer in chat with time and title; he can run
  `calendar-cli list --from X --to X --simple` himself for the plain view.
- Exit 2 means a calendar failed; its `error` is in the JSON. Say which one failed and
  never call a gap in that calendar "free". A Google sign-in error means the user must run
  `calendar-cli auth gmail` himself (it opens a browser).

## Add an event

```zsh
calendar-cli add "Dentist" -c personal -s "2026-10-30 14:00" -d 45m --json
calendar-cli add "Budget review prep" -c work -s "2026-10-27 13:30" -e "2026-10-27 15:00" \
    --category "Focus time" --json
calendar-cli add "Family trip" -c family -s 2026-11-26 --all-day -d 3d --json
```

- the user asking for it is approval for a plain add: run it, then confirm what was created.
  If you had to guess the calendar, the date or the length (default 1 h), say so in the
  confirmation so he can correct it.
- Optional: `-l LOCATION`, `--description TEXT`, `--category NAME`.
- Categories: M365 takes his Outlook categories, Google takes the names under
  `[category_colors]` in the config (event colors). Run `calendar-cli categories --json` if he names one you
  haven't seen. An unknown category is rejected before anything is written.
- **Never add `--attendee` without asking first.** It sends real invitations. If he
  wants to invite someone, show the exact emails and get a yes.
- Read the JSON result: check the returned `event` title and times, and keep its
  `op_id`.

## Change or delete an event

1. Get a fresh ref. Refs like `work:3` come from the **latest** `list` and expire after
   24 hours, and every `list` replaces them. List the range that holds the event with
   `--json`, find it, and take its `ref` from that output. Run this right before the
   write; don't reuse a ref from earlier in the conversation.
2. Check the event:
   - **`attendees` not empty** → changing it emails them. Tell the user who will be
     notified and wait for a yes before writing.
   - **`is_organizer` false** → someone else's meeting. `delete` refuses it by design;
     tell him to decline it in Outlook or Google Calendar. Don't try to update it either.
   - **`is_occurrence` true** → one instance of a recurring event. A change or delete
     affects only that instance. Delete the whole series with `--series` only when he
     says so; a series delete cannot be undone.
3. Write it with `-y` (without `-y` the command waits for a terminal prompt and exits 1):

```zsh
calendar-cli update work:3 -s "2026-10-30 16:00" -y --json     # move; keeps its length
calendar-cli update work:3 -d 90m -y --json                      # change the length
calendar-cli update personal:2 -t "Dentist (moved)" -l "New office" -y --json
calendar-cli update work:5 --category "Focus time" -y --json
calendar-cli update work:5 --no-category -y --json
calendar-cli delete personal:2 -y --json
calendar-cli delete work:4 --series -y --json                    # whole series, no undo
```

When `-y` is fine: his request named the event and the change ("move my 3 pm dentist to
4"), the match was unambiguous, and it has no attendees. Otherwise, show the event and
the change and ask first.

`update` changes title, time, location, description and category only. It cannot add or
remove attendees or change recurrence; say so and point him to Outlook or Google
Calendar.

## Undo and history

```zsh
calendar-cli history --json              # newest first; -n 50 for more
calendar-cli undo -y --json              # the latest write not yet undone
calendar-cli undo 20261022T184042-f9b9 -y --json
```

- "Undo that" right after your own write → undo that write's `op_id`, not just the
  latest, in case something else wrote since.
- Undoing a create deletes the event; an update puts back the changed fields; a delete
  restores the event (M365 gives it a new ID). An undo can't itself be undone, and a
  `--series` delete can't be undone.
- If the operation touched an event with attendees, undoing it emails them too. Ask first.
- "What did you change?" → `history --json`, and report each entry's `timestamp`,
  `action`, `calendar` and `title`, plus `status` (failed writes are listed too) and
  `undone_by` (set when it was undone).

## Report back

One or two lines per write: what changed, on which calendar, the final time, and that
`calendar-cli undo` reverses it. For example: "Added **Dentist** to personal, Fri 10/30
14:00–14:45. `calendar-cli undo` removes it." If a write fails, quote the error, don't
retry blindly, and say what he can do (the README's troubleshooting table covers the
common errors).

## Testing this skill

Never test against his real calendars. Use the test calendars:
`calendar-cli ... --config ~/.config/calendar-cli/e2e.toml` with `-c e2e-work`,
`-c e2e-personal` or `-p e2e`, and remove anything you create there afterwards.
