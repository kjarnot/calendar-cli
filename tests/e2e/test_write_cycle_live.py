# ABOUTME: Live end-to-end write cycle (add, update, delete, undo x3) on both "calendar-cli e2e" test calendars.
# ABOUTME: Skipped unless CALENDAR_CLI_E2E=1 and the e2e config exists; cleans up any event it leaves behind.
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BINARY = shutil.which("calendar-cli")
E2E_CONFIG = Path(os.environ.get("CALENDAR_CLI_E2E_CONFIG", "~/.config/calendar-cli/e2e.toml")).expanduser()
DAY = "2027-01-05"  # far enough ahead to stay out of the way

pytestmark = pytest.mark.skipif(
    os.environ.get("CALENDAR_CLI_E2E") != "1" or BINARY is None or not E2E_CONFIG.is_file(),
    reason="live e2e tests need CALENDAR_CLI_E2E=1, an installed binary, and the e2e config",
)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BINARY, *args, "--config", str(E2E_CONFIG)], check=False, capture_output=True, text=True, timeout=60
    )


def events(alias: str) -> list[dict]:
    result = run("list", "-c", alias, "--from", DAY, "--to", DAY, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["calendars"][0]["events"]


@pytest.mark.parametrize("alias", ["e2e-work", "e2e-personal"])
def test_write_cycle(alias):
    if alias not in E2E_CONFIG.read_text():
        pytest.skip(f"{alias} is not in the e2e config")
    title = f"calendar-cli e2e {alias}"
    try:
        added = run(
            "add", title, "-c", alias, "-s", f"{DAY} 10:00", "-d", "30m", "--category", "Exercise", "--json"
        )
        assert added.returncode == 0, added.stderr
        assert json.loads(added.stdout)["event"]["categories"] == ["Exercise"]
        assert [e["title"] for e in events(alias)] == [title]

        updated = run("update", f"{alias}:1", "-s", f"{DAY} 13:00", "--no-category", "-y")
        assert updated.returncode == 0, updated.stderr
        [moved] = events(alias)
        assert moved["start"].startswith(f"{DAY}T13:00")
        assert moved["categories"] == []

        deleted = run("delete", f"{alias}:1", "-y")
        assert deleted.returncode == 0, deleted.stderr
        assert events(alias) == []

        assert run("undo", "-y").returncode == 0  # restores the delete
        assert [e["start"][:16] for e in events(alias)] == [f"{DAY}T13:00"]
        assert run("undo", "-y").returncode == 0  # reverts the update
        [reverted] = events(alias)
        assert reverted["start"].startswith(f"{DAY}T10:00")
        assert reverted["categories"] == ["Exercise"]
        assert run("undo", "-y").returncode == 0  # removes the created event
        assert events(alias) == []
    finally:
        for index, _ in enumerate(events(alias), start=1):
            run("delete", f"{alias}:{index}", "-y")
