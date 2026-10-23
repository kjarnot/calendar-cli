# ABOUTME: Integration tests that run plan.py as a subprocess on a saved calendar-cli JSON file.
# ABOUTME: Covers each command's text and JSON output, stdin input and option handling.
import json
import subprocess
import sys

from tests.skill.conftest import FAMILY, PLAN_PATH


def run(*args, stdin=None):
    return subprocess.run(
        [sys.executable, str(PLAN_PATH), *args], input=stdin, capture_output=True, text=True, check=False
    )


def test_free_text(payload_file):
    result = run(
        "free",
        str(payload_file),
        "--ignore-title",
        FAMILY,
        "--day-start",
        "08:30",
        "--day-end",
        "17:30",
        "--min",
        "60",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "Free windows 08:30-17:30, at least 60 min:",
        "  Tue 2026-10-27  10:00–11:00 (60m), 12:00–17:30 (330m)",
    ]


def test_free_json_from_stdin(payload_file):
    result = run("free", "-", "--json", stdin=payload_file.read_text())

    assert json.loads(result.stdout)["days"][0]["free"][0] == {
        "start": "08:00",
        "end": "09:00",
        "minutes": 60,
    }


def test_conflicts_json(payload_file):
    result = run("conflicts", str(payload_file), "--ignore-title", FAMILY, "--json")

    [conflict] = json.loads(result.stdout)["conflicts"]
    assert conflict["kind"] == "double-booked"
    assert conflict["overlap_minutes"] == 15
    assert (conflict["a"]["ref"], conflict["b"]["ref"]) == ("work:1", "work:2")


def test_load_text_shows_context(payload_file):
    result = run("load", str(payload_file), "--ignore-title", FAMILY)

    assert "Tue 2026-10-27  3 events, 2.0h booked, 09:00–12:00, longest unbroken 60m" in result.stdout
    assert "context: Alex - Work 9am-6pm [family] (family member's event)" in result.stdout
    assert "context: Dan: PTO [work] (all-day)" in result.stdout


def test_no_ignore_title_counts_family_events(payload_file):
    result = run("load", str(payload_file), "--json")

    assert json.loads(result.stdout)["days"][0]["busy_events"] == 4


def test_weekdays_skips_weekend(tmp_path):
    payload = {
        "range": {"from": "2026-10-31T00:00:00-04:00", "to": "2026-11-03T00:00:00-05:00"},
        "calendars": [],
    }
    path = tmp_path / "w.json"
    path.write_text(json.dumps(payload))

    result = run("free", str(path), "--weekdays", "--json")

    assert [d["date"] for d in json.loads(result.stdout)["days"]] == ["2026-11-02"]


def test_bad_command_exits_2(payload_file):
    assert run("nope", str(payload_file)).returncode == 2
