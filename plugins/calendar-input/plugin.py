"""Google Calendar input Plugin — collects upcoming events."""

from bsage.plugin import plugin


@plugin(
    name="calendar-input",
    version="1.0.0",
    category="input",
    description="Collect upcoming events from Google Calendar and store as seeds",
    trigger={"type": "cron", "schedule": "0 7 * * *"},
    credentials=[
        {
            "name": "google_api_key",
            "description": "Google Calendar API key or OAuth token",
            "required": True,
        },
        {"name": "calendar_id", "description": "Calendar ID (default: primary)", "required": False},
        {
            "name": "days_ahead",
            "description": "Days ahead to fetch (default: 7)",
            "required": False,
        },
    ],
)
async def execute(context) -> dict:
    """Fetch upcoming calendar events and write to seeds."""
    from datetime import UTC, datetime, timedelta

    import httpx

    creds = context.credentials
    api_key = creds.get("google_api_key", "")
    calendar_id = creds.get("calendar_id", "primary")
    days_ahead = int(creds.get("days_ahead", 7))

    now = datetime.now(tz=UTC)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "key": api_key,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=15.0)
        response.raise_for_status()
        data = response.json()

    events = []
    for item in data.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        events.append(
            {
                "title": item.get("summary", ""),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "description": item.get("description", ""),
                "location": item.get("location", ""),
                "attendees": [a.get("email", "") for a in item.get("attendees", [])],
            }
        )

    await context.garden.write_seed("calendar", {"events": events})
    return {"collected": len(events)}


@execute.setup
async def setup(cred_store):
    """Configure Google Calendar API credentials."""
    import click
    import httpx

    click.echo("Google Calendar Input Setup")
    api_key = click.prompt("  Google API key / OAuth token")
    calendar_id = click.prompt("  Calendar ID", default="primary")
    days_ahead = click.prompt("  Days ahead to fetch", default="7")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}",
            params={"key": api_key},
            timeout=10.0,
        )
        if resp.status_code != 200:
            click.echo(f"Error: API returned HTTP {resp.status_code}", err=True)
            raise SystemExit(1)
        cal_name = resp.json().get("summary", calendar_id)
        click.echo(f"  Verified calendar: {cal_name}")

    data = {"google_api_key": api_key, "calendar_id": calendar_id, "days_ahead": days_ahead}
    await cred_store.store("calendar-input", data)
