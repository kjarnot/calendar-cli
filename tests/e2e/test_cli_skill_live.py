# ABOUTME: Live end-to-end test of the calendar-cli skill's recipe on the e2e test calendar:
# ABOUTME: add, find the ref in list --json, move it with -y, delete it, then undo the delete by op_id.
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()
DAY = "2027-01-19"
TITLE = "calendar-cli skill e2e"

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1" or BINARY is None or not E2E_CONFIG.is_file(),
    reason="live e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and the e2e config",
)


def cli(*args):
    result = subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def find(title):
    """The skill's lookup step: list --json and match the title; returns the event with its ref."""
    listed = cli("list", "-c", "e2e-work", "--from", DAY, "--to", DAY, "--json")
    return [e for e in listed["calendars"][0]["events"] if e["title"] == title]


def test_skill_recipe_add_move_delete_undo():
    added = cli("add", TITLE, "-c", "e2e-work", "-s", f"{DAY} 14:00", "-d", "45m", "--json")
    try:
        assert added["event"]["title"] == TITLE

        (event,) = find(TITLE)
        assert event["attendees"] == [] and event["is_organizer"] is True
        moved = cli("update", event["ref"], "-s", f"{DAY} 16:00", "-y", "--json")
        assert moved["event"]["start"].startswith(f"{DAY}T16:00")
        assert moved["event"]["end"].startswith(f"{DAY}T16:45")

        (event,) = find(TITLE)
        deleted = cli("delete", event["ref"], "-y", "--json")
        assert find(TITLE) == []

        cli("undo", deleted["op_id"], "-y", "--json")
        (restored,) = find(TITLE)
        assert restored["start"].startswith(f"{DAY}T16:00")

        history = cli("history", "-n", "5", "--json")
        entry = next(h for h in history if h["op_id"] == deleted["op_id"])
        assert entry["action"] == "delete" and entry["undone_by"]
    finally:
        for leftover in find(TITLE):
            cli("delete", leftover["ref"], "-y", "--json")
