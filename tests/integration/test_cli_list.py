# ABOUTME: Integration tests for the `list` and `calendars` commands with an in-memory fake provider.
# ABOUTME: Covers grouping, calendar filtering, JSON output, saved refs and per-calendar errors.
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from calendar_cli import cli
from calendar_cli.models import CalendarInfo, Event
from calendar_cli.providers.base import ProviderError
from calendar_cli.state import resolve_ref

TZ = ZoneInfo("America/New_York")
runner = CliRunner()


class FakeProvider:
    def __init__(self, events: list[Event] | None = None, error: str | None = None) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[tuple] = []

    def list_calendars(self) -> list[CalendarInfo]:
        if self.error:
            raise ProviderError(self.error)
        return [CalendarInfo(calendar_id="cal-1", name="Calendar", is_default=True, can_edit=True)]

    def list_events(self, calendar_alias, calendar_id, start, end) -> list[Event]:
        self.calls.append((calendar_alias, calendar_id, start, end))
        if self.error:
            raise ProviderError(self.error)
        return [e.model_copy(update={"calendar_alias": calendar_alias}) for e in self.events]


def meeting(pid: str, title: str, hour: int) -> Event:
    return Event(
        calendar_alias="",
        provider_id=pid,
        title=title,
        start=datetime(2026, 10, 22, hour, tzinfo=TZ),
        end=datetime(2026, 10, 22, hour + 1, tzinfo=TZ),
    )


@pytest.fixture
def providers(monkeypatch):
    fakes = {
        "office": FakeProvider([meeting("w2", "Retro", 14), meeting("w1", "Standup", 10)]),
        "gmail": FakeProvider([meeting("p1", "Dentist", 16)]),
    }
    monkeypatch.setattr(cli, "build_provider", lambda config, name: fakes[name])
    return fakes


def test_list_groups_by_calendar_and_saves_refs(write_config, providers):
    result = runner.invoke(cli.app, ["list", "--config", str(write_config()), "--from", "2026-10-22"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "work (M365 · someone@example.com)"
    assert "work:1       10:00–11:00  Standup" in result.output
    assert "work:2       14:00–15:00  Retro" in result.output
    assert "personal:1   16:00–17:00  Dentist" in result.output
    assert resolve_ref("work:2") == ("work", "w2")
    _, calendar_id, start, end = providers["office"].calls[0]
    assert calendar_id == "primary"
    assert (start.isoformat(), end.isoformat()) == ("2026-10-22T00:00:00-04:00", "2026-10-29T00:00:00-04:00")


def test_list_filters_by_calendar(write_config, providers):
    result = runner.invoke(cli.app, ["list", "--config", str(write_config()), "-c", "personal"])

    assert result.exit_code == 0, result.output
    assert "work" not in result.output
    assert providers["office"].calls == []


def test_list_json(write_config, providers):
    result = runner.invoke(cli.app, ["list", "--config", str(write_config()), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [c["alias"] for c in payload["calendars"]] == ["work", "personal"]
    assert payload["calendars"][0]["events"][0]["ref"] == "work:1"
    assert payload["calendars"][0]["events"][0]["title"] == "Standup"


def test_list_reports_failed_calendar_and_exits_2(write_config, providers):
    providers["gmail"].error = "token expired"

    result = runner.invoke(cli.app, ["list", "--config", str(write_config())])

    assert result.exit_code == 2
    assert "Standup" in result.output
    assert "personal (Google · primary)\n  error: token expired" in result.output


def test_list_unknown_calendar_exits_1(write_config, providers):
    result = runner.invoke(cli.app, ["list", "--config", str(write_config()), "-c", "home"])

    assert result.exit_code == 1
    assert "unknown calendar 'home'" in result.output


def test_list_bad_date_exits_1(write_config, providers):
    result = runner.invoke(cli.app, ["list", "--config", str(write_config()), "--from", "someday"])

    assert result.exit_code == 1
    assert "cannot understand date 'someday'" in result.output


def test_list_writes_app_log(write_config, providers, isolated_state):
    runner.invoke(cli.app, ["list", "--config", str(write_config()), "--from", "2026-10-22"])

    log = (isolated_state / "app.log").read_text()
    assert "list work 2026-10-22T00:00:00-04:00..2026-10-29T00:00:00-04:00: 2 events" in log


def test_calendars_text_and_error(write_config, providers):
    providers["gmail"].error = "not signed in"

    result = runner.invoke(cli.app, ["calendars", "--config", str(write_config())])

    assert result.exit_code == 2
    assert "office (m365)\n  Calendar  (default)\n    id: cal-1" in result.output
    assert "gmail (google)\n  error: not signed in" in result.output


def test_calendars_json_one_account(write_config, providers):
    result = runner.invoke(
        cli.app, ["calendars", "--config", str(write_config()), "--account", "office", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "office": {
            "calendars": [{"calendar_id": "cal-1", "name": "Calendar", "is_default": True, "can_edit": True}]
        }
    }


def test_calendars_unknown_account_exits_1(write_config, providers):
    result = runner.invoke(cli.app, ["calendars", "--config", str(write_config()), "--account", "icloud"])

    assert result.exit_code == 1
    assert "unknown account 'icloud'" in result.output


def test_list_by_date_text_keeps_refs(write_config, providers):
    result = runner.invoke(
        cli.app, ["list", "--by-date", "--config", str(write_config()), "--from", "2026-10-22"]
    )

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "Thu 2026-10-22",
        "  work:1       10:00–11:00  work      Standup",
        "  work:2       14:00–15:00  work      Retro",
        "  personal:1   16:00–17:00  personal  Dentist",
    ]
    assert resolve_ref("personal:1") == ("personal", "p1")


def test_list_by_date_json_and_error_exit(write_config, providers):
    providers["gmail"].error = "token expired"

    result = runner.invoke(cli.app, ["list", "--by-date", "--json", "--config", str(write_config())])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert [e["title"] for e in payload["days"][0]["events"]] == ["Standup", "Retro"]
    assert payload["errors"] == [{"alias": "personal", "error": "token expired"}]
