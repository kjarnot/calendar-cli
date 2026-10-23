---
name: calendar-planning
description: Plan the user's time across his work (M365) and personal/family (Google) calendars with calendar-cli — day or week overviews, finding free time, time-blocking a to-do list (typed in or pulled from Todoist), and spotting work/personal conflicts and double-bookings — then create only the calendar blocks he approves. Use this whenever the user asks things like "what does my week look like", "plan my day", "when am I free Thursday", "find me 90 minutes for X", "block time for these tasks", "schedule my Todoist tasks", "do I have any conflicts", "am I double-booked", "can I fit a dentist appointment in next week", or anything that means looking at his calendars to decide when to do something, even if he doesn't say "calendar" or "plan". Workout blocks belong to the weekly-training-plan skill.
---

# Calendar planning

Help the user decide **when** things happen, using his real calendars. The calendar is the
durable result; the conversation is where the plan is worked out. Nothing goes on a
calendar until he approves it.

## Tools

- `calendar-cli` (on PATH) reads and writes both calendars. Run `calendar-cli list --help`
  or read `~/Development/Personal/calendar-cli/README.md` for anything not covered here.
- `scripts/plan.py` (next to this file) does the planning math on `calendar-cli list --json`
  output: free windows, conflicts, and daily load. Use it instead of working out overlaps
  by hand — interval math over dozens of events is exactly where by-eye reasoning slips,
  and a wrong "you're free at 2" costs the user a double-booking.
- Todoist MCP (`find-tasks-by-date`, `find-tasks`) when he wants his tasks scheduled.

Calendars (aliases from `~/.config/calendar-cli/config.toml`):

| Alias | What it is | Profile |
|---|---|---|
| `work` | M365 calendar | `work` |
| `personal` | the user's own Google calendar ("K") | `personal` |
| `family` | Shared family calendar (Family) | `personal` |

## Step 1 — Pull the events

Always pull every calendar for the period, even when the question is only about work: a
family appointment at 3 pm matters when picking a work block. Save the JSON to a temp
file, then run the script on it (`plan.py` sits in this skill's `scripts/` folder).

```zsh
EV=$(mktemp -t calendar-planning).json
calendar-cli list --from 2026-10-26 --to 2026-10-30 --json > $EV
P=~/.claude-personal/skills/calendar-planning/scripts/plan.py   # work setup: ~/.claude/skills/...
python3 $P load $EV                      # busy hours per day, plus what was ignored and why
python3 $P free $EV --day-start 08:30 --day-end 17:30 --min 60 --weekdays
python3 $P conflicts $EV
```

- Dates: ISO, `today`, `tomorrow`, weekday names, `+3d`. A weekday can't take a time.
  "This week" means today through Friday; "next week" means next Monday–Friday (or
  through Sunday if he's asking about personal plans).
- If `list` exits 2, one calendar failed (its `error` is in the JSON). Say which, and
  plan with what you have only if he's fine with that — never present a gap in a failed
  calendar as free time. A Google sign-in error means the user must run
  `calendar-cli auth gmail` himself.
- Add `--json` to every script call when you need to compute on the result.

### What counts as busy

`plan.py` applies these rules (shared with the weekly-training-plan skill), so trust its
output rather than re-deciding per event:

- **All-day events don't block time.** Holidays, trips and "thru Mon" PTO are context to
  mention, not obstacles. If the all-day event is *the user's own* vacation or day off,
  treat the whole day as unavailable and say so.
- **Colleagues' notices don't block time** — someone else's PTO, vacation or appointment
  that reached him as an invite.
- **Family members' events on the family calendar aren't his busy time.** Titles starting
  with Alex, Sam or Jordan are their plans. They still matter as context (e.g. Alex
  working late may mean the user handles dinner), so mention relevant ones. Events titled
  "K - ..." or with no name are treated as his.
- `load` lists everything it ignored under `context:` so you can mention it.

## Step 2 — Do what he asked

### Overview ("what does my week look like", "plan my day")

Lead with the shape of the period, then the details that need attention:

1. One line per day: how full it is, first/last commitment, best open window.
2. Conflicts and double-bookings (from `conflicts`).
3. Heavy days: more than ~5 h booked, or 2 h+ without a break. Suggest protecting a gap.
4. Family/personal context that changes the day (appointments, Alex's late shifts,
   trips, holidays).
5. Optionally, one or two suggestions ("Tuesday afternoon is your only long free block —
   want me to hold it for focus time?").

Keep event lists short; he can run `calendar-cli list --by-date --simple` for everything.

### Find free time ("when am I free", "find me 90 minutes")

Run `free` with the right window and minimum. Defaults when he doesn't say:

| Kind of time | Window | Days |
|---|---|---|
| Work task / focus block | 08:30–17:30 | Mon–Fri (`--weekdays`) |
| Personal errand / appointment | 08:00–20:00 | any day |

Offer the **two or three best** slots, not every gap, and say why each is good (longest
gap, not right after a long meeting run, morning for deep work). If nothing fits, say
so and offer the nearest alternative (a shorter slot, a different day, or the meeting
that could move).

### Time-block a to-do list ("block time for these", "schedule my Todoist tasks")

1. Get the tasks. Typed in: use them. Todoist: `find-tasks-by-date` for the day/period
   he named (default today), or `find-tasks` with his filter. Skip tasks already done.
2. Durations: use the task's own duration if it has one; otherwise estimate sensibly
   (30 min default) and **say which ones you estimated** so he can correct them.
3. Place them with `free`: priority and due dates first, deep work in the morning,
   short tasks in short gaps, a 10–15 min buffer after long meeting runs, nothing over
   lunch (12:00–13:00) unless that's the only option. Don't fill every gap; leave
   breathing room.
4. Calendar and category: work tasks on `work` with category `Focus time`; personal
   tasks on `personal` with no category. Check `calendar-cli categories` if he names a
   different category.

### Conflict check ("am I double-booked", "any clashes")

Report each `conflicts` entry with both events and refs, the overlap, and the kind:
- **work/personal clash** — a work event over his own personal or family commitment;
  these matter most, list them first.
- **double-booked** — two work events at once; often one is optional or recurring, so
  say which looks easier to drop (larger group meeting vs a 1:1, recurring vs one-off).

Suggest what to do, but don't change or decline anything. Changing an event with
attendees emails them, so that is the user's call in Outlook or Google Calendar.

## Step 3 — Propose, then write only what he approves

Show proposed blocks as a table before touching any calendar:

| # | Day | Time | Block | Calendar | Category |
|---|---|---|---|---|---|
| 1 | Tue 10/27 | 13:30–15:00 | Q4 budget review prep | work | Focus time |
| 2 | Wed 10/28 | 08:30–09:30 | Renew passport | personal | — |

Then ask which to create (all, some by number, or changes). This keeps him in control:
a planning skill that silently fills his calendar is worse than none. When he approves:

```zsh
calendar-cli add "Q4 budget review prep" -c work -s "2026-10-27 13:30" -e "2026-10-27 15:00" \
    --category "Focus time" --json
```

- One `add` per approved block; never add `--attendee`. Read each result: confirm the
  returned event's time and title, and collect the `op_id`.
- If an `add` fails, report it and carry on with the rest; don't retry blindly.
- Moving an existing block he owns: `calendar-cli list ... --json` to get its `ref`, then
  `calendar-cli update <ref> -s "..." -y` — only after he approved that move, and never for
  an event with attendees without asking first.
- Finish with what was created, and that `calendar-cli undo` reverses the latest one
  (`calendar-cli history` lists op ids; `calendar-cli undo <op_id>` reverses a specific one).

## Output

Chat only. Lead with the answer (the free slots, the conflicts, the shape of the week),
then details. Use tables for slots and proposals. Times are Eastern unless he asks
otherwise; for another zone add `--tz NAME` to the `calendar-cli` call **and** the same
`--tz` to `plan.py`.

## Testing this skill

Never test against his real calendars. Use the dedicated test calendars:
`calendar-cli ... --config ~/.config/calendar-cli/e2e.toml -p e2e` (aliases `e2e-work`,
`e2e-personal`), and remove anything you create there afterwards.
