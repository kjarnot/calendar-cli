# ABOUTME: Integration tests for add, update, delete, history and undo through the CLI with an in-memory provider.
# ABOUTME: Covers confirmations, refs, refusal cases, JSON output, journal contents and exit codes.
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from calendar_cli import cli, journal
from calendar_cli.models import Attendee
from tests.fakes import MemoryProvider

TZ = ZoneInfo("America/New_York")
runner = CliRunner()


@pytest.fixture
def setup(write_config, monkeypatch):
    provider = MemoryProvider()
    monkeypatch.setattr(cli, "build_provider", lambda config, name: provider)
    config = str(write_config())

    def run(*args: str, input: str | None = None):
        return runner.invoke(cli.app, [*args, "--config", config], input=input)

    return provider, run


def at(d: int, h: int) -> datetime:
    return datetime(2026, 12, d, h, tzinfo=TZ)


def test_add_then_undo(setup):
    provider, run = setup

    result = run(
        "add", "Dentist", "-c", "work", "-s", "2026-12-01 14:00", "-d", "30m", "--category", "Exercise"
    )

    assert result.exit_code == 0, result.output
    assert "Created: Dentist — Tue 2026-12-01 14:00–14:30 (work) [Exercise]" in result.output
    [event] = provider.events.values()
    assert event.categories == ["Exercise"]

    result = run("undo", "-y")
    assert result.exit_code == 0, result.output
    assert "Undone: Dentist" in result.output
    assert provider.events == {}


def test_add_json(setup):
    _, run = setup

    result = run("add", "Trip", "-c", "personal", "-s", "2026-12-03", "--all-day", "-d", "2d", "--json")

    payload = json.loads(result.output)
    assert payload["event"]["all_day"] is True
    assert payload["event"]["end"] == "2026-12-05T00:00:00-05:00"
    assert payload["op_id"] == journal.read_all()[0].op_id


def test_add_errors(setup):
    _, run = setup

    assert "has no time" in run("add", "X", "-c", "work", "-s", "2026-12-01").output
    result = run("add", "X", "-c", "work", "-s", "2026-12-01 10:00", "--category", "Nope")
    assert result.exit_code == 1
    assert "unknown category 'Nope'" in result.output
    assert run("add", "X", "-c", "home", "-s", "2026-12-01 10:00").exit_code == 1


def test_provider_failure_exits_2(setup):
    provider, run = setup
    provider.fail_next = "HTTP 503: service unavailable"

    result = run("add", "X", "-c", "work", "-s", "2026-12-01 10:00")

    assert result.exit_code == 2
    assert "HTTP 503" in result.output
    assert journal.read_all()[0].status == "failed"


def test_update_by_short_ref_keeps_length(setup):
    provider, run = setup
    provider.add("work", "Standup", at(1, 9), at(1, 10))
    run("list", "--from", "2026-12-01")

    result = run("update", "work:1", "-s", "2026-12-01 15:00", "--title", "Late standup", "-y")

    assert result.exit_code == 0, result.output
    assert "start: 2026-12-01 09:00:00-05:00 -> 2026-12-01 15:00:00-05:00" in result.output
    [event] = provider.events.values()
    assert (event.title, event.start, event.end) == ("Late standup", at(1, 15), at(1, 16))


def test_json_writes_keep_the_summary_off_stdout(setup):
    provider, run = setup
    event = provider.add("work", "Gym", at(1, 9), at(1, 10), attendees=[Attendee(email="dan@example.com")])
    ref = f"work:{event.provider_id}"

    declined = run("delete", ref, "--json", input="n\n")
    updated = run("update", ref, "-s", "2026-12-01 11:00", "-y", "--json")
    deleted = run("delete", ref, "-y", "--json")
    undone = run("undo", "-y", "--json")

    assert declined.exit_code == 1
    assert "Proceed?" in declined.stderr and "Proceed?" not in declined.stdout

    for result in (updated, deleted, undone):
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["event"]["title"] == "Gym"
    assert "start: 2026-12-01 09:00:00-05:00 -> 2026-12-01 11:00:00-05:00" in updated.stderr
    assert "will be sent a cancellation" in deleted.stderr
    assert "will be sent a new invitation" in undone.stderr


def test_update_full_ref_and_no_category(setup):
    provider, run = setup
    event = provider.add("work", "Gym", at(1, 9), at(1, 10), categories=["Exercise"])

    result = run("update", f"work:{event.provider_id}", "--no-category", "-y")

    assert result.exit_code == 0, result.output
    assert provider.events[event.provider_id].categories == []


def test_update_needs_a_change_and_valid_flags(setup):
    provider, run = setup
    event = provider.add("work", "Gym", at(1, 9), at(1, 10))

    assert "nothing to change" in run("update", f"work:{event.provider_id}", "-y").output
    assert (
        "not both"
        in run("update", f"work:{event.provider_id}", "--category", "Staff", "--no-category").output
    )


def test_confirmation_declined_changes_nothing(setup):
    provider, run = setup
    event = provider.add("work", "Gym", at(1, 9), at(1, 10))

    result = run("delete", f"work:{event.provider_id}", input="n\n")

    assert result.exit_code == 1
    assert "cancelled; nothing was changed" in result.output
    assert event.provider_id in provider.events
    assert journal.read_all() == []


def test_delete_confirmed_then_undo_restores(setup):
    provider, run = setup
    event = provider.add("work", "Gym", at(1, 9), at(1, 10), attendees=[Attendee(email="dan@example.com")])

    result = run("delete", f"work:{event.provider_id}", input="y\n")

    assert result.exit_code == 0, result.output
    assert "1 attendee(s) will be sent a cancellation" in result.output
    assert provider.events == {}

    result = run("undo", "-y")
    assert result.exit_code == 0, result.output
    assert "will be sent a new invitation" in result.output
    [restored] = provider.events.values()
    assert restored.title == "Gym"


def test_delete_refuses_meetings_you_do_not_organize(setup):
    provider, run = setup
    event = provider.add(
        "work", "Board", at(1, 9), at(1, 10), is_organizer=False, organizer="boss@example.com"
    )

    result = run("delete", f"work:{event.provider_id}", "-y")

    assert result.exit_code == 1
    assert "you are not the organizer" in result.output
    assert event.provider_id in provider.events


def test_delete_series(setup):
    provider, run = setup
    master = provider.add("work", "Weekly", at(1, 9), at(1, 10))
    occurrence = provider.add(
        "work", "Weekly", at(8, 9), at(8, 10), series_id=master.provider_id, is_occurrence=True
    )
    single = provider.add("work", "Once", at(2, 9), at(2, 10))

    assert (
        "not part of a recurring series"
        in run("delete", f"work:{single.provider_id}", "--series", "-y").output
    )
    result = run("delete", f"work:{occurrence.provider_id}", "--series", "-y")
    assert result.exit_code == 0, result.output
    assert "undo cannot restore a deleted series" in result.output
    assert master.provider_id not in provider.events

    result = run("undo", "-y")
    assert result.exit_code == 1
    assert "series delete is not supported" in result.output


def test_bad_refs(setup):
    _, run = setup

    assert "must look like work:3" in run("delete", "work").output
    assert "run `calendar-cli list` first" in run("delete", "work:4").output
    assert "unknown calendar 'home'" in run("delete", "home:abc").output


def test_history_text_and_json(setup):
    _, run = setup
    run("add", "A", "-c", "work", "-s", "2026-12-01 10:00")
    run("add", "B", "-c", "work", "-s", "2026-12-01 12:00", "--category", "Nope")
    run("undo", "-y")
    first = journal.read_all()[0]

    text = run("history").output.splitlines()
    assert "undo" in text[0] and f"undoes {first.op_id}" in text[0]
    assert "FAILED: unknown category 'Nope'" in text[1]
    assert text[2].startswith(first.op_id) and text[2].endswith(f"undone by {journal.read_all()[2].op_id}")

    payload = json.loads(run("history", "--json", "-n", "1").output)
    assert len(payload) == 1
    assert payload[0]["action"] == "undo"
    assert "before" not in payload[0]


def test_history_empty_and_nothing_to_undo(setup):
    _, run = setup

    assert "(no operations yet)" in run("history").output
    result = run("undo", "-y")
    assert result.exit_code == 1
    assert "nothing to undo" in result.output


def test_undo_named_op(setup):
    provider, run = setup
    run("add", "A", "-c", "work", "-s", "2026-12-01 10:00")
    run("add", "B", "-c", "work", "-s", "2026-12-01 12:00")
    first = journal.read_all()[0]

    result = run("undo", first.op_id, "-y")

    assert result.exit_code == 0, result.output
    assert [e.title for e in provider.events.values()] == ["B"]


def test_add_with_tz_reads_times_in_that_zone(setup):
    provider, run = setup

    result = run("add", "Call", "-c", "work", "-s", "2026-12-01 14:00", "--tz", "Europe/London", "--json")

    assert result.exit_code == 0, result.output
    [event] = provider.events.values()
    assert event.start.isoformat() == "2026-12-01T14:00:00+00:00"
    assert event.start.astimezone(TZ).hour == 9  # 14:00 London is 09:00 New York in December
