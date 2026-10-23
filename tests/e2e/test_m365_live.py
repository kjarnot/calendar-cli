# ABOUTME: Live end-to-end tests: the installed calendar-cli binary against the real M365 test calendar.
# ABOUTME: Skipped unless CALENDAR_CLI_E2E=1 and the e2e config (alias "e2e-work") exists.
import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1" or BINARY is None or not E2E_CONFIG.is_file(),
    reason="live e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and the e2e config",
)


def m365_account() -> str:
    """The e2e config's M365 account name, so the test works whatever the account is called."""
    accounts = tomllib.loads(E2E_CONFIG.read_text())["accounts"]
    return next(name for name, account in accounts.items() if account["provider"] == "m365")


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )


def test_calendars_lists_the_e2e_calendar():
    result = run("calendars", "--account", m365_account(), "--json")

    assert result.returncode == 0, result.stderr
    names = [c["name"] for c in json.loads(result.stdout)[m365_account()]["calendars"]]
    assert "calendar-cli e2e" in names


def test_list_e2e_calendar():
    result = run("list", "-c", "e2e-work", "--from", "today", "--to", "+7d", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["calendars"][0]["alias"] == "e2e-work"
    assert payload["calendars"][0]["error"] is None


def test_categories_lists_outlook_and_config_categories():
    result = run("categories", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "Exercise" in [c["name"] for c in payload[m365_account()]["categories"]]
    assert all(
        c["color"] is None or not c["color"].startswith("preset")
        for c in payload[m365_account()]["categories"]
    )
    if "gmail" in payload:
        assert {"name": "Exercise", "color": "basil"} in payload["gmail"]["categories"]


def test_list_by_date_json():
    result = run("list", "--by-date", "--from", "today", "--to", "+7d", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"range", "days", "errors"}
    assert payload["errors"] == []


def test_list_tz_override_sets_the_live_range():
    result = run(
        "list", "-c", "e2e-work", "--from", "2026-12-01", "--to", "2026-12-01", "--tz", "UTC", "--json"
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["range"] == {
        "from": "2026-12-01T00:00:00+00:00",
        "to": "2026-12-02T00:00:00+00:00",
    }


def test_list_profile_simple():
    if 'profile = "e2e"' not in E2E_CONFIG.read_text():
        pytest.skip("the e2e config has no e2e profile")
    result = run("list", "-p", "e2e", "--from", "2026-12-01", "--to", "2026-12-01", "--simple")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "(no events)"
    assert result.stderr == ""
