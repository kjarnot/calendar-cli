# ABOUTME: Append-only JSONL journal of every calendar write, with before/after event snapshots.
# ABOUTME: It is the source of truth for `history` and `undo`; entries are never rewritten.
import json
import secrets
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from calendar_cli.models import Event
from calendar_cli.state import private_file, state_dir

Action = Literal["create", "update", "delete", "undo"]


class JournalEntry(BaseModel):
    op_id: str
    timestamp: datetime
    action: Action
    calendar: str
    event_id: str
    title: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    series: bool = False
    undoes: str | None = None
    status: Literal["ok", "failed"] = "ok"
    error: str | None = None

    def before_event(self) -> Event | None:
        return Event.from_snapshot(self.before) if self.before else None

    def after_event(self) -> Event | None:
        return Event.from_snapshot(self.after) if self.after else None


def new_op_id(now: datetime) -> str:
    return f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(2)}"


def record(
    action: Action,
    calendar: str,
    event_id: str,
    title: str,
    tz: str,
    before: Event | None = None,
    after: Event | None = None,
    series: bool = False,
    undoes: str | None = None,
    error: str | None = None,
) -> JournalEntry:
    """Append one entry to the journal and return it."""
    now = datetime.now(ZoneInfo(tz))
    entry = JournalEntry(
        op_id=new_op_id(now),
        timestamp=now,
        action=action,
        calendar=calendar,
        event_id=event_id,
        title=title,
        before=before.snapshot() if before else None,
        after=after.snapshot() if after else None,
        series=series,
        undoes=undoes,
        status="failed" if error else "ok",
        error=error,
    )
    with private_file(state_dir() / "journal.jsonl").open("a") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return entry


def read_all() -> list[JournalEntry]:
    """Every entry, oldest first."""
    path = state_dir() / "journal.jsonl"
    if not path.is_file():
        return []
    return [
        JournalEntry.model_validate(json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def undone_ops(entries: list[JournalEntry]) -> dict[str, str]:
    """Map each op_id that has been successfully undone to the op_id of its undo."""
    return {e.undoes: e.op_id for e in entries if e.action == "undo" and e.status == "ok" and e.undoes}


def find_undo_target(entries: list[JournalEntry], op_id: str | None) -> JournalEntry:
    """Pick the entry to undo: the named one, or the newest successful write not yet undone."""
    done = undone_ops(entries)
    if op_id is not None:
        matches = [e for e in entries if e.op_id == op_id]
        if not matches:
            raise LookupError(f"no journal entry {op_id!r}; see `calendar-cli history`")
        target = matches[0]
        if target.action == "undo":
            raise LookupError(f"{op_id} is itself an undo; undoing an undo is not supported")
        if target.status != "ok":
            raise LookupError(f"{op_id} failed, so there is nothing to undo")
        if op_id in done:
            raise LookupError(f"{op_id} was already undone by {done[op_id]}")
        return target
    for entry in reversed(entries):
        if entry.action != "undo" and entry.status == "ok" and entry.op_id not in done:
            return entry
    raise LookupError("nothing to undo")


def current_event_id(entries: list[JournalEntry], event_id: str) -> str:
    """Follow an event ID through later restores that recreated it under a new ID (M365 does this)."""
    by_op = {e.op_id: e for e in entries}
    current = event_id
    for entry in entries:
        if entry.action != "undo" or entry.status != "ok" or not entry.after:
            continue
        undone = by_op.get(entry.undoes or "")
        if undone and undone.action == "delete" and undone.event_id == current:
            current = entry.after["provider_id"]
    return current
