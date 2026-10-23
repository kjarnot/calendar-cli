# ABOUTME: Live end-to-end test of the calendar-planning skill's pipeline: calendar-cli list --json into plan.py.
# ABOUTME: Creates one event on the e2e test calendar, checks plan.py sees it as busy, then removes it.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.skill.conftest import PLAN_PATH

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()
DAY = "2027-01-12"

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1" or BINARY is None or not E2E_CONFIG.is_file(),
    reason="live e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and the e2e config",
)


def cli(*args):
    return subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )


def test_free_windows_exclude_a_real_event():
    created = cli("add", "planning skill e2e", "-c", "e2e-work", "-s", f"{DAY} 11:00", "-d", "60m", "--json")
    assert created.returncode == 0, created.stderr
    try:
        listed = cli("list", "-c", "e2e-work", "--from", DAY, "--to", DAY, "--json")
        assert listed.returncode == 0, listed.stderr
        free = subprocess.run(
            [
                sys.executable,
                str(PLAN_PATH),
                "free",
                "-",
                "--day-start",
                "09:00",
                "--day-end",
                "17:00",
                "--json",
            ],
            input=listed.stdout,
            capture_output=True,
            text=True,
            check=True,
        )
        windows = json.loads(free.stdout)["days"][0]["free"]
        assert [(w["start"], w["end"]) for w in windows] == [("09:00", "11:00"), ("12:00", "17:00")]
    finally:
        assert cli("undo", "-y").returncode == 0
    assert (
        json.loads(cli("list", "-c", "e2e-work", "--from", DAY, "--to", DAY, "--json").stdout)["calendars"][
            0
        ]["events"]
        == []
    )
