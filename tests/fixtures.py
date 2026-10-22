# ABOUTME: Sample Microsoft Graph payloads shared by the M365 unit and integration tests.
# ABOUTME: Shapes mirror real Graph v1.0 responses, trimmed to the fields calendar-cli selects.
from calendar_cli.config import M365Account

M365_ACCOUNT = M365Account(
    provider="m365", tenant_id="t", client_id="c", client_secret="s", user="me@example.com"
)

GRAPH_MEETING = {
    "id": "AAMk-meeting",
    "subject": "Leadership sync",
    "start": {"dateTime": "2026-10-22T09:00:00.0000000", "timeZone": "America/New_York"},
    "end": {"dateTime": "2026-10-22T09:30:00.0000000", "timeZone": "America/New_York"},
    "isAllDay": False,
    "location": {"displayName": "Teams"},
    "bodyPreview": "Agenda: budget",
    "categories": ["Meetings"],
    "attendees": [
        {
            "emailAddress": {"address": "dan@example.com", "name": "Dan"},
            "status": {"response": "accepted"},
        }
    ],
    "organizer": {"emailAddress": {"address": "me@example.com", "name": "Me"}},
    "isOrganizer": True,
    "seriesMasterId": "AAMk-series",
    "type": "occurrence",
    "webLink": "https://outlook.office365.com/owa/?itemid=x",
}

GRAPH_ALL_DAY = {
    "id": "AAMk-allday",
    "subject": "",
    "start": {"dateTime": "2026-10-24T00:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-10-25T00:00:00.0000000", "timeZone": "UTC"},
    "isAllDay": True,
    "location": {"displayName": ""},
    "bodyPreview": "",
    "categories": [],
    "attendees": [],
    "organizer": {"emailAddress": {"address": "boss@example.com"}},
    "isOrganizer": False,
    "seriesMasterId": None,
    "type": "singleInstance",
    "webLink": None,
}
