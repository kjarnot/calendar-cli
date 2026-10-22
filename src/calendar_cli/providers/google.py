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
from calendar_cli.config import Config, ConfigError, GoogleAccount
from calendar_cli.models import Attendee, CalendarInfo, Event, EventChanges, EventDraft
from calendar_cli.providers.base import InputError, ProviderError

CALENDAR_URL = "https://www.googleapis.com/calendar/v3"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EDIT_ROLES = ("owner", "writer")
# Email attendees about creates, changes and cancellations, as Outlook does.
SEND_UPDATES = {"sendUpdates": "all"}
# Server-assigned fields that cannot be sent when recreating an event.
NOT_COPYABLE = (
    "id",
    "etag",
    "htmlLink",
    "iCalUID",
    "created",
    "updated",
    "creator",
    "organizer",
    "status",
    "kind",
)

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
            self._events_path(calendar_id),
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

    def get_event(self, calendar_alias: str, calendar_id: str, event_id: str) -> Event:
        return self._to_event(calendar_alias, self._send("GET", self._event_path(calendar_id, event_id)))

    def create_event(self, calendar_alias: str, calendar_id: str, draft: EventDraft) -> Event:
        item = self._send(
            "POST",
            self._events_path(calendar_id),
            params=SEND_UPDATES,
            json=self._payload(draft.model_dump()),
        )
        return self._to_event(calendar_alias, item)

    def update_event(
        self, calendar_alias: str, calendar_id: str, event_id: str, changes: EventChanges
    ) -> Event:
        fields = changes.changed()
        if {"start", "end", "all_day"} & fields.keys():
            # Google needs start and end in the same form (date vs dateTime), so fill in any
            # timing field that is not changing from the current event.
            current = self.get_event(calendar_alias, calendar_id, event_id)
            fields = {"start": current.start, "end": current.end, "all_day": current.all_day, **fields}
        item = self._send(
            "PATCH", self._event_path(calendar_id, event_id), params=SEND_UPDATES, json=self._payload(fields)
        )
        return self._to_event(calendar_alias, item)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._send("DELETE", self._event_path(calendar_id, event_id), params=SEND_UPDATES)

    def restore_event(self, calendar_alias: str, calendar_id: str, snapshot: Event) -> Event:
        """Undelete in place (keeps the ID); if Google has purged it, recreate from the snapshot."""
        try:
            item = self._send(
                "PATCH",
                self._event_path(calendar_id, snapshot.provider_id),
                params=SEND_UPDATES,
                json={"status": "confirmed"},
            )
        except InputError:
            logger.info("undelete of %s failed; recreating from snapshot", snapshot.provider_id)
            payload = {k: v for k, v in snapshot.raw.items() if k not in NOT_COPYABLE}
            item = self._send("POST", self._events_path(calendar_id), params=SEND_UPDATES, json=payload)
        return self._to_event(calendar_alias, item)

    def _payload(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Translate neutral event fields into a Google event body."""
        payload: dict[str, Any] = {}
        if "title" in fields:
            payload["summary"] = fields["title"]
        all_day = bool(fields.get("all_day"))
        for name in ("start", "end"):
            if fields.get(name) is not None:
                moment = fields[name].astimezone(ZoneInfo(self.timezone))
                payload[name] = (
                    {"date": moment.date().isoformat(), "dateTime": None, "timeZone": None}
                    if all_day
                    else {"dateTime": moment.isoformat(), "timeZone": self.timezone, "date": None}
                )
        if "location" in fields:
            payload["location"] = fields["location"]
        if "description" in fields:
            payload["description"] = fields["description"]
        if "categories" in fields:
            categories = fields["categories"] or []
            if len(categories) > 1:
                raise InputError("Google events take one category (one color); got " + ", ".join(categories))
            try:
                payload["colorId"] = self.config.google_color_id(categories[0]) if categories else None
            except ConfigError as exc:
                raise InputError(str(exc)) from None
        if fields.get("attendees"):
            payload["attendees"] = [{"email": email} for email in fields["attendees"]]
        return payload

    def _events_path(self, calendar_id: str) -> str:
        return f"/calendars/{quote(calendar_id, safe='')}/events"

    def _event_path(self, calendar_id: str, event_id: str) -> str:
        return f"{self._events_path(calendar_id)}/{quote(event_id, safe='')}"

    def _send(
        self, method: str, path: str, params: dict[str, str] | None = None, json: dict | None = None
    ) -> dict[str, Any]:
        """Make one Calendar API request and return its JSON body ({} for 204 No Content)."""
        url = f"{CALENDAR_URL}{path}"
        logger.debug("%s %s", method, url)
        try:
            response = self._http.request(
                method, url, params=params, json=json, headers={"Authorization": f"Bearer {self._token()}"}
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Google request failed: {exc}") from None
        if response.status_code in (404, 410):
            raise InputError(f"Google event or calendar not found: {_google_error(response)}")
        if response.status_code >= 400:
            raise ProviderError(f"Google returned HTTP {response.status_code}: {_google_error(response)}")
        return response.json() if response.content else {}

    def _get_all(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET a Calendar API collection, following nextPageToken pages."""
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            page_params = {**params, "pageToken": page_token} if page_token else params
            body = self._send("GET", path, params=page_params)
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
