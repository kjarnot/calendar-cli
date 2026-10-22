# ABOUTME: Live end-to-end tests: the installed calendar-cli binary against the real M365 test calendar.
# ABOUTME: Skipped unless CALENDAR_CLI_E2E=1 and the e2e config (alias "e2e-work") exists.
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1" or BINARY is None or not E2E_CONFIG.is_file(),
    reason="live e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and the e2e config",
)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )


def test_calendars_lists_the_e2e_calendar():
    result = run("calendars", "--account", "office", "--json")

    assert result.returncode == 0, result.stderr
    names = [c["name"] for c in json.loads(result.stdout)["office"]["calendars"]]
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
    assert "Exercise" in [c["name"] for c in payload["office"]["categories"]]
    assert all(
        c["color"] is None or not c["color"].startswith("preset") for c in payload["office"]["categories"]
    )
    if "gmail" in payload:
        assert {"name": "Exercise", "color": "basil"} in payload["gmail"]["categories"]
