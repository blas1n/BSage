"""Telegram message input Plugin."""

from bsage.plugin import plugin


@plugin(
    name="telegram-input",
    version="1.0.0",
    category="input",
    description="Collects messages from a Telegram bot and stores them in the vault",
    trigger={"type": "webhook"},
    credentials=[
        {"name": "bot_token", "description": "Telegram Bot API token", "required": True},
        {"name": "chat_id", "description": "Target chat ID for notifications", "required": True},
    ],
)
async def execute(context):
    """Receive messages from Telegram and write to seeds."""
    # In a real implementation, this would poll the Telegram API.
    # Placeholder: relies on webhook triggering with pre-populated input_data.
    messages = context.input_data.get("messages", []) if context.input_data else []
    await context.garden.write_seed("telegram", {"messages": messages})
    return {"collected": len(messages)}


@execute.setup
async def setup(cred_store):
    """Configure Telegram bot credentials with token validation."""
    import click
    import httpx

    click.echo("Telegram Bot Setup")
    bot_token = click.prompt("  Bot token (from @BotFather)")
    chat_id = click.prompt("  Chat ID")

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10.0)
        if resp.status_code != 200:
            click.echo(f"Error: Invalid bot token (HTTP {resp.status_code})", err=True)
            raise SystemExit(1)
        bot_name = resp.json().get("result", {}).get("username", "unknown")
        click.echo(f"  Verified bot: @{bot_name}")

    await cred_store.store("telegram-input", {"bot_token": bot_token, "chat_id": chat_id})


@execute.notify
async def notify(context):
    """Send a message back to the Telegram chat via Bot API."""
    import httpx

    creds = context.credentials
    message = (context.input_data or {}).get("message", "")
    if not message:
        return {"sent": False, "reason": "no message provided"}

    bot_token = creds.get("bot_token", "")
    chat_id = creds.get("chat_id", "")
    if not bot_token or not chat_id:
        return {"sent": False, "reason": "missing bot_token or chat_id"}

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=10.0,
        )
        response.raise_for_status()

    return {"sent": True, "chat_id": chat_id}
