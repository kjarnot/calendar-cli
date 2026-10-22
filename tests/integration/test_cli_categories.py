# ABOUTME: Integration tests for the `categories` command and the JSON guidance in top-level help.
# ABOUTME: Providers are replaced with fakes; no network calls are made.
import json

import pytest
from typer.testing import CliRunner

from calendar_cli import cli
from calendar_cli.models import Category
from calendar_cli.providers.base import ProviderError

runner = CliRunner()


class FakeCategories:
    def __init__(self, categories=None, error=None):
        self.categories = categories or []
        self.error = error

    def list_categories(self):
        if self.error:
            raise ProviderError(self.error)
        return self.categories


@pytest.fixture
def providers(monkeypatch):
    fakes = {
        "office": FakeCategories(
            [Category(name="VIP", color="dark yellow"), Category(name="Exercise", color="orange")]
        ),
        "gmail": FakeCategories([Category(name="Exercise", color="basil")]),
    }
    monkeypatch.setattr(cli, "build_provider", lambda config, name: fakes[name])
    return fakes


def test_categories_text(write_config, providers):
    result = runner.invoke(cli.app, ["categories", "--config", str(write_config())])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "office (m365, from Outlook)",
        "  VIP       dark yellow",
        "  Exercise  orange",
        "gmail (google, from [category_colors] in config)",
        "  Exercise  basil",
    ]


def test_categories_json_one_account(write_config, providers):
    result = runner.invoke(
        cli.app, ["categories", "--account", "office", "--json", "--config", str(write_config())]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "office": {
            "provider": "m365",
            "categories": [{"name": "VIP", "color": "dark yellow"}, {"name": "Exercise", "color": "orange"}],
        }
    }


def test_categories_error_and_empty(write_config, providers):
    providers["office"].error = "M365 sign-in failed: invalid_client: bad secret"
    providers["gmail"].categories = []

    result = runner.invoke(cli.app, ["categories", "--config", str(write_config())])

    assert result.exit_code == 2
    assert "office (m365, from Outlook)\n  error: M365 sign-in failed" in result.output
    assert "gmail (google, from [category_colors] in config)\n  (none)" in result.output


def test_categories_unknown_account(write_config, providers):
    result = runner.invoke(cli.app, ["categories", "--account", "icloud", "--config", str(write_config())])

    assert result.exit_code == 1
    assert "unknown account 'icloud'" in result.output


def test_top_level_help_explains_json():
    result = runner.invoke(cli.app, ["--help"], env={"COLUMNS": "120"})

    assert result.exit_code == 0
    assert "add --json after the command" in result.output
    assert "categories" in result.output
