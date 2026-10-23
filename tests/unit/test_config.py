# ABOUTME: Unit tests for config loading, validation, path resolution and category color mapping.
# ABOUTME: Uses temporary config files only; never reads the real config.

import pytest

from calendar_cli.config import (
    CONFIG_ENV_VAR,
    ConfigError,
    GoogleAccount,
    M365Account,
    load_config,
    resolve_config_path,
)
from tests.conftest import VALID_CONFIG


def test_loads_valid_config(write_config):
    config = load_config(write_config())

    assert config.default_timezone == "America/New_York"
    assert isinstance(config.accounts["office"], M365Account)
    assert isinstance(config.accounts["gmail"], GoogleAccount)
    assert [c.alias for c in config.calendars] == ["work", "personal"]
    assert config.calendar("work").calendar_id == "primary"


def test_google_oauth_client_config(write_config):
    client = load_config(write_config()).accounts["gmail"].oauth_client_config()["installed"]

    assert client["client_id"] == "google-client-789.apps.googleusercontent.com"
    assert client["client_secret"] == "google-secret-value"
    assert client["token_uri"] == "https://oauth2.googleapis.com/token"


def test_secrets_not_in_repr(write_config):
    config = load_config(write_config())

    assert "super-secret-value" not in repr(config)
    assert "google-secret-value" not in repr(config)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "nope.toml")


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_rejects_group_or_world_readable(write_config, mode):
    with pytest.raises(ConfigError, match="chmod 600"):
        load_config(write_config(mode=mode))


def test_rejects_invalid_toml(write_config):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_config("this is = = not toml"))


def test_rejects_unknown_timezone(write_config):
    text = VALID_CONFIG.replace("America/New_York", "Mars/Olympus_Mons")
    with pytest.raises(ConfigError, match="unknown timezone"):
        load_config(write_config(text))


def test_rejects_unknown_color(write_config):
    text = VALID_CONFIG.replace('"basil"', '"chartreuse"')
    with pytest.raises(ConfigError, match="unknown color 'chartreuse'"):
        load_config(write_config(text))


def test_rejects_calendar_with_unknown_account(write_config):
    text = VALID_CONFIG.replace('account = "gmail"', 'account = "icloud"')
    with pytest.raises(ConfigError, match="unknown account 'icloud'"):
        load_config(write_config(text))


def test_rejects_duplicate_alias(write_config):
    text = VALID_CONFIG.replace('alias = "personal"', 'alias = "work"')
    with pytest.raises(ConfigError, match="duplicate calendar alias 'work'"):
        load_config(write_config(text))


def test_rejects_unknown_provider(write_config):
    text = VALID_CONFIG.replace('provider = "google"', 'provider = "icloud"')
    with pytest.raises(ConfigError, match="invalid"):
        load_config(write_config(text))


def test_unknown_calendar_alias(write_config):
    config = load_config(write_config())

    with pytest.raises(ConfigError, match="unknown calendar 'home'; configured: work, personal"):
        config.calendar("home")


def test_google_color_mapping_both_ways(write_config):
    config = load_config(write_config())

    assert config.google_color_id("Exercise") == "10"
    assert config.google_color_id("Family") == "6"
    assert config.category_for_google_color("10") == "Exercise"
    assert config.category_for_google_color("1") is None
    assert config.category_for_google_color(None) is None


def test_unmapped_category_raises(write_config):
    config = load_config(write_config())

    with pytest.raises(ConfigError, match="no Google color"):
        config.google_color_id("Meetings")


def test_resolve_path_prefers_explicit_then_env(monkeypatch, tmp_path):
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "env.toml"))

    assert resolve_config_path(tmp_path / "explicit.toml") == tmp_path / "explicit.toml"
    assert resolve_config_path() == tmp_path / "env.toml"


def test_with_timezone_overrides_without_touching_original(write_config):
    config = load_config(write_config())

    london = config.with_timezone("Europe/London")

    assert london.default_timezone == "Europe/London"
    assert config.default_timezone == "America/New_York"
    assert config.with_timezone(None) is config


def test_with_timezone_rejects_unknown_names(write_config):
    with pytest.raises(ConfigError, match="unknown timezone 'Mars/Base'; use an IANA name"):
        load_config(write_config()).with_timezone("Mars/Base")


PROFILED = (
    VALID_CONFIG.replace('alias = "work"\n', 'alias = "work"\nprofile = "job"\n').replace(
        'alias = "personal"\n', 'alias = "personal"\nprofile = "home"\n'
    )
    + """
[[calendars]]
alias = "family"
account = "gmail"
calendar_id = "family@group.calendar.google.com"
profile = "home"
"""
)


def test_profiles_in_config_order(write_config):
    config = load_config(write_config(PROFILED))

    assert config.profiles() == ["job", "home"]
    assert config.calendar("family").profile == "home"


def test_select_calendars(write_config):
    config = load_config(write_config(PROFILED))

    def aliases(*args):
        return [c.alias for c in config.select_calendars(*args)]

    assert aliases(None, None) == ["work", "personal", "family"]
    assert aliases(None, ["home"]) == ["personal", "family"]
    assert aliases(["work"], ["home"]) == ["work", "personal", "family"]
    assert aliases(["family"], ["home"]) == ["personal", "family"]  # no duplicates, config order
    assert aliases(["family"], None) == ["family"]


def test_select_unknown_profile_or_alias(write_config):
    config = load_config(write_config(PROFILED))

    with pytest.raises(ConfigError, match="unknown profile 'work'; configured: job, home"):
        config.select_calendars(None, ["work"])
    with pytest.raises(ConfigError, match="unknown calendar 'nope'"):
        config.select_calendars(["nope"], ["home"])


def test_unknown_profile_when_none_configured(write_config):
    with pytest.raises(ConfigError, match=r"\(none; add profile = \.\.\. to \[\[calendars\]\]\)"):
        load_config(write_config()).select_calendars(None, ["home"])
