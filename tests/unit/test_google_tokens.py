# ABOUTME: Unit tests for the Google token provider: Keychain loading, refresh, and re-auth errors.
# ABOUTME: The Keychain is replaced by an in-memory dict, so the real Keychain is never touched.
import json

import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from calendar_cli import tokens
from calendar_cli.providers.base import ProviderError
from calendar_cli.providers.google import keyring_token_provider


def token_json(token: str, expiry: str) -> str:
    return json.dumps(
        {
            "token": token,
            "refresh_token": "refresh-1",
            "client_id": "client",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token",
            "expiry": expiry,
        }
    )


@pytest.fixture
def keychain(monkeypatch) -> dict[str, str]:
    store: dict[str, str] = {}
    monkeypatch.setattr(tokens, "load_token", store.get)
    monkeypatch.setattr(tokens, "save_token", store.__setitem__)
    return store


def test_not_signed_in(keychain):
    with pytest.raises(ProviderError, match="not signed in; run: calendar-cli auth gmail"):
        keyring_token_provider("gmail")()


def test_valid_token_is_used_as_is(keychain):
    keychain["gmail"] = token_json("access-1", "2099-01-01T00:00:00Z")

    assert keyring_token_provider("gmail")() == "access-1"


def test_expired_token_is_refreshed_and_saved(keychain, monkeypatch):
    keychain["gmail"] = token_json("old", "2000-01-01T00:00:00Z")

    def fake_refresh(self, request):
        self.token = "access-2"
        self.expiry = None

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    assert keyring_token_provider("gmail")() == "access-2"
    assert json.loads(keychain["gmail"])["token"] == "access-2"


def test_revoked_refresh_token_asks_for_reauth(keychain, monkeypatch):
    keychain["gmail"] = token_json("old", "2000-01-01T00:00:00Z")

    def fail_refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", fail_refresh)

    with pytest.raises(ProviderError, match="expired or was revoked .*run: calendar-cli auth gmail"):
        keyring_token_provider("gmail")()
