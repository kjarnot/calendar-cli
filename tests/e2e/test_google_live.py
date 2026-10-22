# ABOUTME: Live end-to-end tests: the installed calendar-cli binary against the real Google test calendar.
# ABOUTME: Skipped unless CALENDAR_CLI_E2E=1, the e2e config has alias "e2e-personal", and gmail is signed in.
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1"
    or BINARY is None
    or not E2E_CONFIG.is_file()
    or 'alias = "e2e-personal"' not in E2E_CONFIG.read_text(),
    reason="live Google e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and e2e-personal in the e2e config",
)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )


def test_calendars_lists_the_google_e2e_calendar():
    result = run("calendars", "--account", "gmail", "--json")

    assert result.returncode == 0, result.stderr
    names = [c["name"] for c in json.loads(result.stdout)["gmail"]["calendars"]]
    assert "calendar-cli e2e" in names


def test_list_google_e2e_calendar():
    result = run("list", "-c", "e2e-personal", "--from", "today", "--to", "+7d", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["calendars"][0]["alias"] == "e2e-personal"
    assert payload["calendars"][0]["error"] is None
