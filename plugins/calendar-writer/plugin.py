"""Google Calendar writer Plugin — creates calendar events."""

from bsage.plugin import plugin


@plugin(
    name="calendar-writer",
    version="1.0.0",
    category="process",
    description="Create events in Google Calendar from user requests",
    trigger={"type": "on_demand", "hint": "When the user wants to create a calendar event"},
    credentials=[
        {"name": "google_api_key", "description": "Google Calendar OAuth token", "required": True},
        {"name": "calendar_id", "description": "Calendar ID (default: primary)", "required": False},
    ],
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time (ISO 8601)"},
            "end": {"type": "string", "description": "End time (ISO 8601)"},
            "description": {"type": "string", "description": "Event description"},
            "location": {"type": "string", "description": "Event location"},
        },
        "required": ["title", "start", "end"],
    },
)
async def execute(context) -> dict:
    """Create a Google Calendar event."""
    from datetime import datetime

    import httpx

    data = context.input_data or {}
    title = data.get("title", "")
    start = data.get("start", "")
    end = data.get("end", "")

    if not title or not start or not end:
        return {"created": False, "error": "title, start, and end are required"}

    # Validate ISO 8601 dates
    for dt_str in (start, end):
        try:
            datetime.fromisoformat(dt_str)
        except ValueError:
            return {"created": False, "error": f"Invalid datetime format: {dt_str}"}

    creds = context.credentials
    api_key = creds.get("google_api_key", "")
    calendar_id = creds.get("calendar_id", "primary")

    event_body = {
        "summary": title,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if data.get("description"):
        event_body["description"] = data["description"]
    if data.get("location"):
        event_body["location"] = data["location"]

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=event_body,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )
        response.raise_for_status()
        result = response.json()

    event_id = result.get("id", "")
    html_link = result.get("htmlLink", "")

    await context.garden.write_action("calendar-writer", f"Created event: {title} ({start})")
    return {"created": True, "event_id": event_id, "link": html_link}


@execute.setup
async def setup(cred_store):
    """Configure Google Calendar write credentials with API validation."""
    import click
    import httpx

    click.echo("Google Calendar Writer Setup")
    api_key = click.prompt("  Google OAuth token")
    calendar_id = click.prompt("  Calendar ID", default="primary")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            click.echo(f"Error: API returned HTTP {resp.status_code}", err=True)
            raise SystemExit(1)
        cal_name = resp.json().get("summary", calendar_id)
        click.echo(f"  Verified calendar: {cal_name}")

    data = {"google_api_key": api_key, "calendar_id": calendar_id}
    await cred_store.store("calendar-writer", data)
