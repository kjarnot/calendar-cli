# ABOUTME: Microsoft 365 calendar provider using Microsoft Graph with app-only (client-credentials) auth.
# ABOUTME: Converts Graph event payloads into the provider-neutral Event model.
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import msal

from calendar_cli.config import M365Account
from calendar_cli.models import Attendee, CalendarInfo, Event
from calendar_cli.providers.base import ProviderError

GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
EVENT_FIELDS = (
    "id,subject,start,end,isAllDay,location,bodyPreview,categories,attendees,"
    "organizer,isOrganizer,seriesMasterId,type,webLink"
)

logger = logging.getLogger("calendar_cli.m365")


def msal_token_provider(account: M365Account) -> Callable[[], str]:
    """Return a function that fetches (and msal caches) an app-only Graph token."""
    app = msal.ConfidentialClientApplication(
        account.client_id,
        authority=f"https://login.microsoftonline.com/{account.tenant_id}",
        client_credential=account.client_secret,
    )

    def get_token() -> str:
        result = app.acquire_token_for_client(scopes=[GRAPH_SCOPE])
        if "access_token" not in result:
            # Azure error descriptions run to several lines (trace IDs, timestamps); the first is enough.
            description = (result.get("error_description") or "").split("\n")[0]
            raise ProviderError(f"M365 sign-in failed: {result.get('error')}: {description}")
        return result["access_token"]

    return get_token


class M365Provider:
    def __init__(
        self,
        account: M365Account,
        timezone: str,
        token_provider: Callable[[], str] | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.account = account
        self.timezone = timezone
        self._token = token_provider or msal_token_provider(account)
        self._http = http or httpx.Client(timeout=30)

    def list_calendars(self) -> list[CalendarInfo]:
        items = self._get_all(
            f"/users/{self.account.user}/calendars",
            params={"$select": "id,name,isDefaultCalendar,canEdit"},
        )
        return [
            CalendarInfo(
                calendar_id=item["id"],
                name=item["name"],
                is_default=item.get("isDefaultCalendar", False),
                can_edit=item.get("canEdit", False),
            )
            for item in items
        ]

    def list_events(
        self, calendar_alias: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Event]:
        items = self._get_all(
            f"{self._calendar_path(calendar_id)}/calendarView",
            params={
                "startDateTime": start.isoformat(),
                "endDateTime": end.isoformat(),
                "$select": EVENT_FIELDS,
                "$orderby": "start/dateTime",
                "$top": "100",
            },
        )
        return [self._to_event(calendar_alias, item) for item in items]

    def _calendar_path(self, calendar_id: str) -> str:
        if calendar_id == "primary":
            return f"/users/{self.account.user}/calendar"
        return f"/users/{self.account.user}/calendars/{calendar_id}"

    def _get_all(self, path: str, params: dict[str, str] | None) -> list[dict[str, Any]]:
        """GET a Graph collection, following @odata.nextLink pages."""
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Prefer": f'outlook.timezone="{self.timezone}"',
        }
        url: str | None = f"{GRAPH_URL}{path}"
        items: list[dict[str, Any]] = []
        while url:
            logger.debug("GET %s", url)
            try:
                response = self._http.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise ProviderError(f"M365 request failed: {exc}") from None
            if response.status_code != 200:
                raise ProviderError(f"M365 returned HTTP {response.status_code}: {_graph_error(response)}")
            body = response.json()
            items.extend(body.get("value", []))
            url = body.get("@odata.nextLink")
            params = None  # nextLink carries the full query; an empty dict would erase it
        return items

    def _to_event(self, calendar_alias: str, item: dict[str, Any]) -> Event:
        organizer = (item.get("organizer") or {}).get("emailAddress") or {}
        return Event(
            calendar_alias=calendar_alias,
            provider_id=item["id"],
            title=item.get("subject") or "(no title)",
            start=_graph_time(item["start"], self.timezone),
            end=_graph_time(item["end"], self.timezone),
            all_day=item.get("isAllDay", False),
            location=((item.get("location") or {}).get("displayName")) or None,
            description=item.get("bodyPreview") or None,
            categories=item.get("categories", []),
            attendees=[
                Attendee(
                    email=a["emailAddress"].get("address", ""),
                    name=a["emailAddress"].get("name"),
                    response=(a.get("status") or {}).get("response"),
                )
                for a in item.get("attendees", [])
            ],
            organizer=organizer.get("address"),
            is_organizer=item.get("isOrganizer", True),
            series_id=item.get("seriesMasterId"),
            is_occurrence=item.get("type") in ("occurrence", "exception"),
            web_link=item.get("webLink"),
            raw=item,
        )


def _graph_time(value: dict[str, str], fallback_tz: str) -> datetime:
    """Parse Graph's {dateTime, timeZone} pair; dateTime has 7 fractional digits and no offset."""
    stamp = value["dateTime"]
    if "." in stamp:
        whole, fraction = stamp.split(".", 1)
        stamp = f"{whole}.{fraction[:6]}"
    tz_name = value.get("timeZone") or fallback_tz
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        # Graph can report Windows zone names (e.g. "Eastern Standard Time") when no Prefer header applies.
        tz = ZoneInfo(fallback_tz)
    return datetime.fromisoformat(stamp).replace(tzinfo=tz)


def _graph_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return f"{error.get('code')}: {error.get('message')}"
    except ValueError:
        return response.text[:200]
