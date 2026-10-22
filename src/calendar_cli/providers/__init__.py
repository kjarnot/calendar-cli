# ABOUTME: Builds the right CalendarProvider for a configured account.
# ABOUTME: Providers are created once per account and shared by that account's calendars.
from calendar_cli.config import Config, M365Account
from calendar_cli.providers.base import CalendarProvider, ProviderError


def build_provider(config: Config, account_name: str) -> CalendarProvider:
    account = config.accounts[account_name]
    if isinstance(account, M365Account):
        from calendar_cli.providers.m365 import M365Provider

        return M365Provider(account, config.default_timezone)
    raise ProviderError(f"the {account.provider} provider is not available yet")
