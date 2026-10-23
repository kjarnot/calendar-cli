# ABOUTME: Fixtures for the calendar-planning skill tests: loads plan.py as a module and builds sample input.
# ABOUTME: plan.py lives outside the package (in the skill folder), so it is imported by path.
import importlib.util
import json
from pathlib import Path

import pytest

PLAN_PATH = Path(__file__).resolve().parents[2] / "skills" / "calendar-planning" / "scripts" / "plan.py"
# The --ignore-title pattern for the sample family members in week_payload.
FAMILY = r"^(alex|sam)\b"


@pytest.fixture(scope="session")
def plan():
    spec = importlib.util.spec_from_file_location("plan", PLAN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ev(title, start, end, *, all_day=False, is_organizer=True, ref="", attendees=0):
    return {
        "ref": ref,
        "title": title,
        "start": f"2026-10-27T{start}:00-04:00" if len(start) == 5 else start,
        "end": f"2026-10-27T{end}:00-04:00" if len(end) == 5 else end,
        "all_day": all_day,
        "is_organizer": is_organizer,
        "attendees": [{"email": f"a{i}@x.com"} for i in range(attendees)],
    }


@pytest.fixture
def week_payload():
    """Tue 2026-10-27, with every kind of event the busy rules distinguish."""
    return {
        "range": {"from": "2026-10-27T00:00:00-04:00", "to": "2026-10-28T00:00:00-04:00"},
        "calendars": [
            {
                "alias": "work",
                "events": [
                    ev("Standup", "09:00", "09:30", ref="work:1"),
                    ev("Planning", "09:15", "10:00", ref="work:2"),
                    ev("Dan: PTO", "2026-10-27T00:00:00-04:00", "2026-10-28T00:00:00-04:00", all_day=True),
                    ev("Robin appointment", "14:00", "15:00", is_organizer=False),
                    ev("Canceled: Vendor call", "15:00", "16:00", is_organizer=False),
                ],
            },
            {
                "alias": "family",
                "events": [
                    ev("Alex - Work 9am-6pm", "09:00", "18:00"),
                    ev("K - dentist", "11:00", "12:00", ref="family:2"),
                ],
            },
        ],
    }


@pytest.fixture
def payload_file(tmp_path, week_payload):
    path = tmp_path / "events.json"
    path.write_text(json.dumps(week_payload))
    return path
