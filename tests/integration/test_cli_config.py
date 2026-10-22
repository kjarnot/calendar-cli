# ABOUTME: Integration tests for the `config` command, run in-process through Typer's CliRunner.
# ABOUTME: Checks the command wires config loading to output and exit codes correctly.
from typer.testing import CliRunner

from calendar_cli.cli import app

runner = CliRunner()


def test_config_command_shows_accounts_and_calendars(write_config):
    result = runner.invoke(app, ["config", "--config", str(write_config())])

    assert result.exit_code == 0, result.output
    assert "office  (m365)  someone@example.com" in result.output
    assert "work  -> office:primary" in result.output
    assert "Exercise = basil" in result.output
    assert "gmail  (google)  client google-client-789.apps.googleusercontent.com" in result.output
    assert "super-secret-value" not in result.output
    assert "google-secret-value" not in result.output


def test_config_command_reports_error_and_exits_1(write_config):
    result = runner.invoke(app, ["config", "--config", str(write_config(mode=0o644))])

    assert result.exit_code == 1
    assert "chmod 600" in result.output
