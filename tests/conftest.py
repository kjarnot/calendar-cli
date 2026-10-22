# ABOUTME: Shared pytest fixtures for calendar-cli tests.
# ABOUTME: Provides a helper that writes a config.toml with safe (600) permissions.
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
client_secrets_file = "~/google_client_secret.json"

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


@pytest.fixture
def write_config(tmp_path: Path):
    def _write(text: str = VALID_CONFIG, mode: int = 0o600) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(text)
        path.chmod(mode)
        return path

    return _write
