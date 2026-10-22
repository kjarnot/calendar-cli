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
from calendar_cli.models import Attendee, CalendarInfo, Category, Event, EventChanges, EventDraft
from calendar_cli.providers.base import InputError, ProviderError

GRAPH_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
EVENT_FIELDS = (
    "id,subject,start,end,isAllDay,location,bodyPreview,categories,attendees,"
    "organizer,isOrganizer,seriesMasterId,type,webLink"
)

# Graph's categoryColor presets, in order (preset0 = red ... preset24 = dark cranberry).
OUTLOOK_COLORS = (
    "red",
    "orange",
    "brown",
    "yellow",
    "green",
    "teal",
    "olive",
    "blue",
    "purple",
    "cranberry",
    "steel",
    "dark steel",
    "gray",
    "dark gray",
    "black",
    "dark red",
    "dark orange",
    "dark brown",
    "dark yellow",
    "dark green",
    "dark teal",
    "dark olive",
    "dark blue",
    "dark purple",
    "dark cranberry",
)

# Graph event fields copied from a snapshot when recreating a deleted event.
RESTORE_FIELDS = (
    "subject",
    "body",
    "start",
    "end",
    "isAllDay",
    "location",
    "categories",
    "showAs",
    "sensitivity",
    "importance",
    "isReminderOn",
    "reminderMinutesBeforeStart",
    "isOnlineMeeting",
    "onlineMeetingProvider",
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
        self._categories: list[Category] | None = None

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

    def list_categories(self) -> list[Category]:
        """The mailbox's Outlook categories, read live from Graph (cached per provider)."""
        if self._categories is None:
            items = self._get_all(f"/users/{self.account.user}/outlook/masterCategories", params=None)
            self._categories = [
                Category(name=item["displayName"], color=_outlook_color(item.get("color"))) for item in items
            ]
        return self._categories

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

    def get_event(self, calendar_alias: str, calendar_id: str, event_id: str) -> Event:
        # Full payload (no $select) so a later restore has the body and every setting.
        return self._to_event(
            calendar_alias, self._send("GET", f"/users/{self.account.user}/events/{event_id}")
        )

    def create_event(self, calendar_alias: str, calendar_id: str, draft: EventDraft) -> Event:
        payload = self._payload(draft.model_dump())
        return self._to_event(
            calendar_alias, self._send("POST", f"{self._calendar_path(calendar_id)}/events", json=payload)
        )

    def update_event(
        self, calendar_alias: str, calendar_id: str, event_id: str, changes: EventChanges
    ) -> Event:
        payload = self._payload(changes.changed())
        return self._to_event(
            calendar_alias, self._send("PATCH", f"/users/{self.account.user}/events/{event_id}", json=payload)
        )

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._send("DELETE", f"/users/{self.account.user}/events/{event_id}")

    def restore_event(self, calendar_alias: str, calendar_id: str, snapshot: Event) -> Event:
        """Recreate the event from its snapshot; Graph has no undelete, so the ID changes."""
        if not snapshot.raw:
            raise InputError("the snapshot has no Graph payload to restore from")
        payload = {key: snapshot.raw[key] for key in RESTORE_FIELDS if snapshot.raw.get(key) is not None}
        # Attendees get a fresh invitation; their old responses cannot be carried over.
        payload["attendees"] = [
            {"emailAddress": a["emailAddress"], "type": a.get("type", "required")}
            for a in snapshot.raw.get("attendees", [])
        ]
        return self._to_event(
            calendar_alias, self._send("POST", f"{self._calendar_path(calendar_id)}/events", json=payload)
        )

    def _payload(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Translate neutral event fields into a Graph event body."""
        payload: dict[str, Any] = {}
        if "title" in fields:
            payload["subject"] = fields["title"]
        for name in ("start", "end"):
            if fields.get(name) is not None:
                local = fields[name].astimezone(ZoneInfo(self.timezone)).replace(tzinfo=None)
                payload[name] = {"dateTime": local.isoformat(), "timeZone": self.timezone}
        if fields.get("all_day") is not None:
            payload["isAllDay"] = fields["all_day"]
        if "location" in fields:
            payload["location"] = {"displayName": fields["location"] or ""}
        if "description" in fields:
            payload["body"] = {"contentType": "text", "content": fields["description"] or ""}
        if "categories" in fields:
            categories = fields["categories"] or []
            self._check_categories(categories)
            payload["categories"] = categories
        if fields.get("attendees"):
            payload["attendees"] = [
                {"emailAddress": {"address": email}, "type": "required"} for email in fields["attendees"]
            ]
        return payload

    def _check_categories(self, categories: list[str]) -> None:
        if not categories:
            return
        valid = [c.name for c in self.list_categories()]
        unknown = [c for c in categories if c not in valid]
        if unknown:
            raise InputError(
                f"unknown M365 category {', '.join(map(repr, unknown))}; valid: {', '.join(valid)}"
            )

    def _send(
        self, method: str, path_or_url: str, params: dict[str, str] | None = None, json: dict | None = None
    ) -> dict[str, Any]:
        """Make one Graph request and return its JSON body ({} for 204 No Content)."""
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Prefer": f'outlook.timezone="{self.timezone}"',
        }
        url = path_or_url if path_or_url.startswith("https://") else f"{GRAPH_URL}{path_or_url}"
        logger.debug("%s %s", method, url)
        try:
            response = self._http.request(method, url, params=params, headers=headers, json=json)
        except httpx.HTTPError as exc:
            raise ProviderError(f"M365 request failed: {exc}") from None
        if response.status_code == 404:
            raise InputError(f"M365 event or calendar not found: {_graph_error(response)}")
        if response.status_code >= 400:
            raise ProviderError(f"M365 returned HTTP {response.status_code}: {_graph_error(response)}")
        return response.json() if response.content else {}

    def _get_all(self, path: str, params: dict[str, str] | None) -> list[dict[str, Any]]:
        """GET a Graph collection, following @odata.nextLink pages."""
        url: str | None = path
        items: list[dict[str, Any]] = []
        while url:
            body = self._send("GET", url, params=params)
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


def _outlook_color(preset: str | None) -> str | None:
    """Turn a Graph color preset ("preset18") into Outlook's name for it ("dark yellow")."""
    if not preset or preset == "none":
        return None
    index = preset.removeprefix("preset")
    if index.isdigit() and int(index) < len(OUTLOOK_COLORS):
        return OUTLOOK_COLORS[int(index)]
    return preset


def _graph_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return f"{error.get('code')}: {error.get('message')}"
    except ValueError:
        return response.text[:200]
