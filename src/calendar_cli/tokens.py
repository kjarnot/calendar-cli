# ABOUTME: Stores OAuth tokens in the macOS Keychain (via keyring), one entry per config account.
# ABOUTME: Tokens never touch the config file, the app log, or the state directory.
import keyring

KEYRING_SERVICE = "calendar-cli"


def load_token(account_name: str) -> str | None:
    """Return the stored token JSON for an account, or None if it has not signed in."""
    return keyring.get_password(KEYRING_SERVICE, account_name)


def save_token(account_name: str, token_json: str) -> None:
    keyring.set_password(KEYRING_SERVICE, account_name, token_json)
