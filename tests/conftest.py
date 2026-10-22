# ABOUTME: Shared pytest fixtures for calendar-cli tests.
# ABOUTME: Provides a helper that writes a config.toml with safe (600) permissions.
import logging
from pathlib import Path

import pytest

VALID_CONFIG = """
default_timezone = "America/New_York"

[accounts.office]
provider = "m365"
tenant_id = "tenant-123"
client_id = "client-456"
client_secret = "super-secret-value"
user = "someone@example.com"

[accounts.gmail]
provider = "google"
client_id = "google-client-789.apps.googleusercontent.com"
client_secret = "google-secret-value"

[[calendars]]
alias = "work"
account = "office"

[[calendars]]
alias = "personal"
account = "gmail"
calendar_id = "primary"

[category_colors]
Exercise = "basil"
Family = "tangerine"
"""


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch):
    """Keep every test's refs and app log out of the real state directory."""
    state = tmp_path / "state"
    monkeypatch.setenv("CALENDAR_CLI_STATE_DIR", str(state))
    yield state
    logger = logging.getLogger("calendar_cli")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(text: str = VALID_CONFIG, mode: int = 0o600) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(text)
        path.chmod(mode)
        return path

    return _write
