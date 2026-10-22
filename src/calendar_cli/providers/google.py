# ABOUTME: Google Calendar provider using the Calendar v3 REST API with installed-app OAuth.
# ABOUTME: Converts Google event payloads into Event objects and maps colorId back to categories.
import json
import logging
from collections.abc import Callable
from datetime import date, datetime, time
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from calendar_cli import tokens
from calendar_cli.config import Config, GoogleAccount
from calendar_cli.models import Attendee, CalendarInfo, Event
from calendar_cli.providers.base import ProviderError

CALENDAR_URL = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EDIT_ROLES = ("owner", "writer")

logger = logging.getLogger("calendar_cli.google")


def sign_in(account_name: str, account: GoogleAccount) -> None:
    """Run the browser OAuth flow and store the resulting token in the Keychain."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(account.oauth_client_config(), SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    tokens.save_token(account_name, credentials.to_json())


def keyring_token_provider(account_name: str) -> Callable[[], str]:
    """Return a function that loads the stored token, refreshing (and re-saving) it when expired."""
    state: dict[str, Credentials] = {}

    def get_token() -> str:
        if "credentials" not in state:
            stored = tokens.load_token(account_name)
            if stored is None:
                raise ProviderError(
                    f"Google account {account_name!r} is not signed in; run: calendar-cli auth {account_name}"
                )
            state["credentials"] = Credentials.from_authorized_user_info(json.loads(stored), SCOPES)
        credentials = state["credentials"]
        if not credentials.valid:
            try:
                credentials.refresh(Request())
            except RefreshError as exc:
                raise ProviderError(
                    f"Google sign-in for {account_name!r} has expired or was revoked ({exc}); "
                    f"run: calendar-cli auth {account_name}"
                ) from None
            tokens.save_token(account_name, credentials.to_json())
        return credentials.token

    return get_token


class GoogleProvider:
    def __init__(
        self,
        account_name: str,
        config: Config,
        token_provider: Callable[[], str] | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.account_name = account_name
        self.config = config
        self.timezone = config.default_timezone
        self._token = token_provider or keyring_token_provider(account_name)
        self._http = http or httpx.Client(timeout=30)

    def list_calendars(self) -> list[CalendarInfo]:
        items = self._get_all("/users/me/calendarList", params={})
        return [
            CalendarInfo(
                calendar_id=item["id"],
                name=item.get("summaryOverride") or item.get("summary", item["id"]),
                is_default=item.get("primary", False),
                can_edit=item.get("accessRole") in EDIT_ROLES,
            )
            for item in items
        ]

    def list_events(
        self, calendar_alias: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Event]:
        items = self._get_all(
            f"/calendars/{quote(calendar_id, safe='')}/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeZone": self.timezone,
                "maxResults": "250",
            },
        )
        return [self._to_event(calendar_alias, item) for item in items if item.get("status") != "cancelled"]

    def _get_all(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET a Calendar API collection, following nextPageToken pages."""
        headers = {"Authorization": f"Bearer {self._token()}"}
        url = f"{CALENDAR_URL}{path}"
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            page_params = {**params, "pageToken": page_token} if page_token else params
            logger.debug("GET %s", url)
            try:
                response = self._http.get(url, params=page_params, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError(f"Google request failed: {exc}") from None
            if response.status_code != 200:
                raise ProviderError(f"Google returned HTTP {response.status_code}: {_google_error(response)}")
            body = response.json()
            items.extend(body.get("items", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return items

    def _to_event(self, calendar_alias: str, item: dict[str, Any]) -> Event:
        organizer = item.get("organizer") or {}
        category = self.config.category_for_google_color(item.get("colorId"))
        return Event(
            calendar_alias=calendar_alias,
            provider_id=item["id"],
            title=item.get("summary") or "(no title)",
            start=self._google_time(item["start"]),
            end=self._google_time(item["end"]),
            all_day="date" in item["start"],
            location=item.get("location") or None,
            description=item.get("description") or None,
            categories=[category] if category else [],
            attendees=[
                Attendee(
                    email=a.get("email", ""), name=a.get("displayName"), response=a.get("responseStatus")
                )
                for a in item.get("attendees", [])
            ],
            organizer=organizer.get("email"),
            # Google sets organizer.self only when it is true; an event with no organizer is our own.
            is_organizer=organizer.get("self", False) if organizer else True,
            series_id=item.get("recurringEventId"),
            is_occurrence="recurringEventId" in item,
            web_link=item.get("htmlLink"),
            raw=item,
        )

    def _google_time(self, value: dict[str, str]) -> datetime:
        """Parse {dateTime} (timed) or {date} (all-day, a floating date) into an aware datetime."""
        tz = ZoneInfo(self.timezone)
        if "date" in value:
            return datetime.combine(date.fromisoformat(value["date"]), time.min, tzinfo=tz)
        return datetime.fromisoformat(value["dateTime"]).astimezone(tz)


def _google_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return f"{error.get('status') or error.get('code')}: {error.get('message')}"
    except ValueError:
        return response.text[:200]
