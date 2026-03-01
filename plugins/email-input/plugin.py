"""Email input Plugin — collects emails via IMAP."""

from bsage.plugin import plugin


@plugin(
    name="email-input",
    version="1.0.0",
    category="input",
    description="Collect emails via IMAP and store as seeds",
    trigger={"type": "cron", "schedule": "*/30 * * * *"},
    credentials=[
        {"name": "imap_server", "description": "IMAP server address", "required": True},
        {"name": "email", "description": "Email address", "required": True},
        {
            "name": "password",
            "description": "Email password or app-specific password",
            "required": True,
        },
        {
            "name": "folder",
            "description": "Email folder to monitor (default: INBOX)",
            "required": False,
        },
        {
            "name": "max_emails",
            "description": "Max emails per run (default: 20)",
            "required": False,
        },
    ],
)
async def execute(context) -> dict:
    """Fetch unread emails and write to seeds."""
    import asyncio
    import email
    import imaplib

    creds = context.credentials
    server = creds.get("imap_server", "")
    user = creds.get("email", "")
    password = creds.get("password", "")
    folder = creds.get("folder", "INBOX")
    max_emails = int(creds.get("max_emails", 20))

    def _fetch_emails() -> list[dict]:
        mail = imaplib.IMAP4_SSL(server)
        try:
            mail.login(user, password)
            mail.select(folder, readonly=True)
            _, msg_ids = mail.search(None, "UNSEEN")
            ids = msg_ids[0].split()[:max_emails] if msg_ids[0] else []

            results = []
            for msg_id in ids:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0]
                if isinstance(raw, tuple) and len(raw) >= 2:
                    raw_bytes = raw[1]
                else:
                    continue
                msg = email.message_from_bytes(raw_bytes)
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == "text/plain":
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                            break
                        if ct == "text/html" and not body:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body = payload.decode("utf-8", errors="replace")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace")

                results.append(
                    {
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "subject": msg.get("Subject", ""),
                        "date": msg.get("Date", ""),
                        "body": body[:5000],
                    }
                )
            return results
        finally:
            import contextlib

            with contextlib.suppress(Exception):
                mail.logout()

    emails = await asyncio.to_thread(_fetch_emails)

    if emails:
        await context.garden.write_seed("email", {"emails": emails})
    return {"collected": len(emails)}


@execute.setup
def setup(cred_store):
    """Configure IMAP email credentials with login validation."""
    import asyncio
    import imaplib

    import click

    click.echo("Email Input (IMAP) Setup")
    imap_server = click.prompt("  IMAP server (e.g. imap.gmail.com)")
    email_addr = click.prompt("  Email address")
    password = click.prompt("  Password / app password", hide_input=True)
    folder = click.prompt("  Folder", default="INBOX")
    max_emails = click.prompt("  Max emails per run", default="20")

    try:
        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(email_addr, password)
        mail.logout()
        click.echo("  IMAP login verified.")
    except imaplib.IMAP4.error as exc:
        click.echo(f"Error: IMAP login failed — {exc}", err=True)
        raise SystemExit(1) from None

    data = {
        "imap_server": imap_server,
        "email": email_addr,
        "password": password,
        "folder": folder,
        "max_emails": max_emails,
    }
    asyncio.run(cred_store.store("email-input", data))
