# ABOUTME: Integration tests for the `auth` command with the browser sign-in replaced by a fake.
# ABOUTME: Checks M365 short-circuit, unknown accounts, success output and failure exit codes.
from typer.testing import CliRunner

from calendar_cli import cli
from calendar_cli.models import CalendarInfo
from calendar_cli.providers.base import ProviderError

runner = CliRunner()


class FakeGoogle:
    def list_calendars(self):
        return [
            CalendarInfo(calendar_id="other@group.calendar.google.com", name="Other"),
            CalendarInfo(calendar_id="me@example.org", name="me@example.org", is_default=True, can_edit=True),
        ]


def test_auth_m365_needs_no_sign_in(write_config, monkeypatch):
    monkeypatch.setattr(
        cli, "google_sign_in", lambda *a: (_ for _ in ()).throw(AssertionError("must not run"))
    )

    result = runner.invoke(cli.app, ["auth", "office", "--config", str(write_config())])

    assert result.exit_code == 0, result.output
    assert "needs no sign-in" in result.output


def test_auth_google_success(write_config, monkeypatch):
    signed_in = []
    monkeypatch.setattr(
        cli, "google_sign_in", lambda name, account: signed_in.append((name, account.client_id))
    )
    monkeypatch.setattr(cli, "build_provider", lambda config, name: FakeGoogle())

    result = runner.invoke(cli.app, ["auth", "gmail", "--config", str(write_config())])

    assert result.exit_code == 0, result.output
    assert signed_in == [("gmail", "google-client-789.apps.googleusercontent.com")]
    assert "Signed in to gmail as me@example.org" in result.output


def test_auth_google_failure_exits_2(write_config, monkeypatch):
    def refuse(name, account):
        raise OSError("address already in use")

    monkeypatch.setattr(cli, "google_sign_in", refuse)

    result = runner.invoke(cli.app, ["auth", "gmail", "--config", str(write_config())])

    assert result.exit_code == 2
    assert "Google sign-in failed: address already in use" in result.output


def test_auth_google_check_failure_exits_2(write_config, monkeypatch):
    class Broken:
        def list_calendars(self):
            raise ProviderError("Google returned HTTP 403: PERMISSION_DENIED: API disabled")

    monkeypatch.setattr(cli, "google_sign_in", lambda name, account: None)
    monkeypatch.setattr(cli, "build_provider", lambda config, name: Broken())

    result = runner.invoke(cli.app, ["auth", "gmail", "--config", str(write_config())])

    assert result.exit_code == 2
    assert "PERMISSION_DENIED" in result.output


def test_auth_unknown_account_exits_1(write_config):
    result = runner.invoke(cli.app, ["auth", "icloud", "--config", str(write_config())])

    assert result.exit_code == 1
    assert "unknown account 'icloud'" in result.output
