"""Email sender Plugin — sends emails via SMTP."""

from bsage.plugin import plugin


@plugin(
    name="email-sender",
    version="1.0.0",
    category="process",
    description="Send emails via SMTP",
    trigger={"type": "on_demand", "hint": "When the user wants to send an email"},
    credentials=[
        {"name": "smtp_server", "description": "SMTP server address", "required": True},
        {"name": "smtp_port", "description": "SMTP port (default: 587)", "required": False},
        {"name": "email", "description": "Sender email address", "required": True},
        {"name": "password", "description": "Email password or app password", "required": True},
    ],
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body (plain text)"},
            "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
        },
        "required": ["to", "subject", "body"],
    },
)
async def execute(context) -> dict:
    """Send an email via SMTP."""
    import asyncio
    import re
    import smtplib
    from email.mime.text import MIMEText

    data = context.input_data or {}
    to_addr = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    cc = data.get("cc", "")

    if not to_addr or not subject or not body:
        return {"sent": False, "error": "to, subject, and body are required"}

    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if not re.match(email_pattern, to_addr):
        return {"sent": False, "error": f"Invalid email address: {to_addr}"}

    creds = context.credentials
    smtp_server = creds.get("smtp_server", "")
    smtp_port = int(creds.get("smtp_port", 587))
    sender_email = creds.get("email", "")
    password = creds.get("password", "")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = cc

    recipients = [to_addr]
    if cc:
        recipients.extend(addr.strip() for addr in cc.split(",") if addr.strip())

    def _send() -> None:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, recipients, msg.as_string())

    await asyncio.to_thread(_send)

    await context.garden.write_action("email-sender", f"Sent email to {to_addr}: {subject}")
    return {"sent": True, "to": to_addr, "subject": subject}


@execute.setup
def setup(cred_store):
    """Configure SMTP credentials with connection test."""
    import asyncio
    import smtplib

    import click

    click.echo("Email Sender (SMTP) Setup")
    smtp_server = click.prompt("  SMTP server (e.g. smtp.gmail.com)")
    smtp_port = click.prompt("  SMTP port", default="587")
    email_addr = click.prompt("  Sender email address")
    password = click.prompt("  Password / app password", hide_input=True)

    try:
        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(email_addr, password)
        click.echo("  SMTP login verified.")
    except Exception as exc:
        click.echo(f"Error: SMTP connection failed — {exc}", err=True)
        raise SystemExit(1) from None

    data = {
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "email": email_addr,
        "password": password,
    }
    asyncio.run(cred_store.store("email-sender", data))
