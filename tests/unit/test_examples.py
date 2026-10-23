# ABOUTME: Checks the example files shipped in the repo: both example configs load through the real
# ABOUTME: config loader, the e2e example has what the live tests need, and the skills template is complete.
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from calendar_cli import cli
from calendar_cli.config import GoogleAccount, M365Account, load_config

ROOT = Path(__file__).resolve().parents[2]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def private_copy(name: str, tmp_path: Path) -> Path:
    """The loader refuses group/other-readable files, as the real config would be."""
    path = tmp_path / name
    shutil.copy(ROOT / name, path)
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("name", ["config.example.toml", "e2e.example.toml"])
def test_example_config_loads(name, tmp_path):
    config = load_config(private_copy(name, tmp_path))

    assert isinstance(config.accounts["office"], M365Account)
    assert isinstance(config.accounts["gmail"], GoogleAccount)
    for entry in config.calendars:
        assert entry.account in config.accounts


@pytest.mark.parametrize("name", ["config.example.toml", "e2e.example.toml"])
def test_example_config_uses_only_placeholder_addresses(name):
    for address in EMAIL.findall((ROOT / name).read_text()):
        assert address.endswith(("@example.com", "@group.calendar.google.com")), address


def test_main_example_has_the_documented_calendars(tmp_path):
    config = load_config(private_copy("config.example.toml", tmp_path))

    assert [(c.alias, c.profile) for c in config.calendars] == [
        ("work", "work"),
        ("personal", "personal"),
        ("family", "personal"),
    ]


def test_e2e_example_matches_the_live_tests(tmp_path):
    config = load_config(private_copy("e2e.example.toml", tmp_path))

    assert [c.alias for c in config.calendars] == ["e2e-work", "e2e-personal"]
    assert config.category_colors == {"Exercise": "basil"}


def test_config_command_accepts_the_example(tmp_path):
    result = CliRunner().invoke(
        cli.app, ["config", "--config", str(private_copy("config.example.toml", tmp_path))]
    )

    assert result.exit_code == 0, result.output
    assert "family" in result.output
    assert "your-client-secret" not in result.output


def test_skills_local_template_covers_what_the_skills_read():
    text = (ROOT / "skills" / "local.example.md").read_text()

    for needed in (
        "Address me as",
        "calendar aliases",
        "Family members",
        "--ignore-title",
        "Google categories",
    ):
        assert needed in text
    assert "skills/*/local.md" in (ROOT / ".gitignore").read_text()


def test_readme_config_block_matches_the_example():
    readme = (ROOT / "README.md").read_text()
    example = (ROOT / "config.example.toml").read_text()
    block = re.search(r"Its shape:\n\n```toml\n(.*?)```", readme, re.DOTALL).group(1)

    assert block == example[example.index("default_timezone") :]
