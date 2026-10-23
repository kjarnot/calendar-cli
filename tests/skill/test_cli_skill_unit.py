# ABOUTME: Unit tests for the calendar-cli skill's SKILL.md: frontmatter, scope hand-offs and safety rules.
# ABOUTME: Guards the parts Claude relies on to load the skill and to avoid emailing attendees by mistake.
import re
from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "calendar-cli" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text():
    return SKILL_PATH.read_text()


@pytest.fixture(scope="module")
def frontmatter(skill_text):
    match = re.match(r"^---\n(.*?)\n---\n", skill_text, re.DOTALL)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_frontmatter_has_only_name_and_description(frontmatter):
    assert set(frontmatter) == {"name", "description"}


def test_name_matches_folder(frontmatter):
    assert frontmatter["name"] == SKILL_PATH.parent.name == "calendar-cli"


def test_description_fits_the_limit(frontmatter):
    assert 100 < len(frontmatter["description"]) <= 1024


def test_description_hands_off_planning_and_workouts(frontmatter):
    assert "calendar-planning" in frontmatter["description"]
    assert "weekly-training-plan" in frontmatter["description"]


def test_lists_every_calendar_alias(skill_text):
    for alias in ("work", "personal", "family"):
        assert f"| `{alias}` |" in skill_text


def test_warns_before_attendees_are_emailed(skill_text):
    assert "Never add `--attendee` without asking first" in skill_text
    assert "`attendees` not empty" in skill_text


def test_points_testing_at_the_e2e_config(skill_text):
    assert "~/.config/calendar-cli/e2e.toml" in skill_text
