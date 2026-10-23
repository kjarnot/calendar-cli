# Local details for the calendar skills (template)

Copy this file to `skills/calendar-cli/local.md` and `skills/calendar-planning/local.md`
and fill it in. Git ignores `skills/*/local.md`, so your real details stay on your machine.
Both skills read it before anything else.

- Address me as **<your name or nickname>**.
- My real calendar aliases (from `calendar-cli config`), which replace the generic ones in
  SKILL.md:

| Alias | What it is | Profile |
|---|---|---|
| `work` | <your work M365 calendar> | `work` |
| `personal` | <your own Google calendar> | `personal` |
| `<family alias>` | <your shared family calendar>; generic name `family` | `personal` |

- Family members: <Name1>, <Name2>. Their events go on `<family alias>`, with titles that
  start with their name ("<Name1> - Dentist").
- For plan.py, pass `--ignore-title '^(<name1>|<name2>)\b'` (lowercase is fine; it ignores
  case). Leave it out if you have no family calendar.
- Titles starting "<your marker> - ..." are my own events.
- Google categories (`[category_colors]`): <Name1> = basil, Exercise = sage.
