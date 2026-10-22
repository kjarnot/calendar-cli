# ABOUTME: Loads and validates the calendar-cli TOML config (accounts, calendars, category colors).
# ABOUTME: Refuses config files readable by group or others, since they hold secrets.
import os
import stat
import tomllib
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("~/.config/calendar-cli/config.toml").expanduser()
CONFIG_ENV_VAR = "CALENDAR_CLI_CONFIG"

# Google Calendar event colors, in colorId order (1-11).
GOOGLE_COLORS = (
    "lavender",
    "sage",
    "grape",
    "flamingo",
    "banana",
    "tangerine",
    "peacock",
    "graphite",
    "blueberry",
    "basil",
    "tomato",
)


class ConfigError(Exception):
    """Raised when the config file is missing, unsafe, or invalid."""


class M365Account(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["m365"]
    tenant_id: str
    client_id: str
    client_secret: str = Field(repr=False)
    user: str


class GoogleAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["google"]
    client_id: str
    client_secret: str = Field(repr=False)

    def oauth_client_config(self) -> dict:
        """Build the installed-app client config that google-auth-oauthlib expects."""
        return {
            "installed": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }


Account = Annotated[M365Account | GoogleAccount, Field(discriminator="provider")]


class CalendarEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str
    account: str
    calendar_id: str = "primary"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_timezone: str = "America/New_York"
    accounts: dict[str, Account]
    calendars: list[CalendarEntry]
    category_colors: dict[str, str] = {}

    @field_validator("default_timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {value!r}") from None
        return value

    @field_validator("category_colors")
    @classmethod
    def check_colors(cls, value: dict[str, str]) -> dict[str, str]:
        for category, color in value.items():
            if color not in GOOGLE_COLORS:
                raise ValueError(
                    f"category {category!r} maps to unknown color {color!r}; "
                    f"valid colors: {', '.join(GOOGLE_COLORS)}"
                )
        return value

    @model_validator(mode="after")
    def check_calendars(self) -> "Config":
        if not self.calendars:
            raise ValueError("at least one [[calendars]] entry is required")
        seen: set[str] = set()
        for entry in self.calendars:
            if entry.alias in seen:
                raise ValueError(f"duplicate calendar alias {entry.alias!r}")
            seen.add(entry.alias)
            if entry.account not in self.accounts:
                raise ValueError(f"calendar {entry.alias!r} uses unknown account {entry.account!r}")
        return self

    def calendar(self, alias: str) -> CalendarEntry:
        for entry in self.calendars:
            if entry.alias == alias:
                return entry
        raise ConfigError(
            f"unknown calendar {alias!r}; configured: {', '.join(c.alias for c in self.calendars)}"
        )

    def google_color_id(self, category: str) -> str:
        """Return the Google colorId (as a string, "1"-"11") for a category name."""
        if category not in self.category_colors:
            raise ConfigError(f"category {category!r} has no Google color; add it under [category_colors]")
        return str(GOOGLE_COLORS.index(self.category_colors[category]) + 1)

    def category_for_google_color(self, color_id: str | None) -> str | None:
        """Reverse-map a Google colorId to the first category configured for it."""
        if color_id is None:
            return None
        for category, color in self.category_colors.items():
            if str(GOOGLE_COLORS.index(color) + 1) == color_id:
                return category
        return None


def resolve_config_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    if env_path := os.environ.get(CONFIG_ENV_VAR):
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> Config:
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")

    mode = stat.S_IMODE(config_path.stat().st_mode)
    if mode & 0o077:
        raise ConfigError(
            f"config file {config_path} has mode {mode:o}, but it holds secrets; run: chmod 600 {config_path}"
        )

    try:
        data = tomllib.loads(config_path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {config_path} is not valid TOML: {exc}") from None

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"config file {config_path} is invalid:\n{exc}") from None
