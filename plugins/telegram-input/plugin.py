"""Telegram message input Plugin — polls getUpdates for new messages."""

import json
from pathlib import Path

from bsage.plugin import plugin

TELEGRAM_API = "https://api.telegram.org/bot{token}"
STATE_SUBPATH = "seeds/telegram-input/_state.json"


def _state_path(context) -> Path:
    """Resolve the offset state file path within the vault."""
    return context.garden.resolve_plugin_state_path("telegram-input")


def _load_offset(path: Path) -> int | None:
    """Load last_update_id from the state file."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("last_update_id")


def _save_offset(path: Path, update_id: int) -> None:
    """Persist last_update_id to the state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_update_id": update_id}), encoding="utf-8")


def _parse_update(update: dict) -> dict | None:
    """Extract a normalized message dict from a Telegram Update object."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    return {
        "update_id": update["update_id"],
        "message_id": msg.get("message_id"),
        "chat_id": msg.get("chat", {}).get("id"),
        "from_id": msg.get("from", {}).get("id"),
        "from_username": msg.get("from", {}).get("username"),
        "text": msg.get("text", ""),
        "date": msg.get("date"),
    }


@plugin(
    name="telegram-input",
    version="1.1.0",
    category="input",
    description="Polls Telegram Bot API for new messages and stores them in the vault",
    trigger={"type": "cron", "schedule": "*/5 * * * *"},
    credentials=[
        {"name": "bot_token", "description": "Telegram Bot API token", "required": True},
        {"name": "chat_id", "description": "Target chat ID for notifications", "required": True},
    ],
)
async def execute(context) -> dict:
    """Poll Telegram getUpdates and write new messages to seeds."""
    import httpx

    creds = context.credentials
    bot_token = creds.get("bot_token", "")
    if not bot_token:
        return {"collected": 0, "error": "missing bot_token"}

    state_file = _state_path(context)
    last_offset = _load_offset(state_file)

    params: dict = {"limit": 100, "timeout": 30}
    if last_offset is not None:
        params["offset"] = last_offset + 1

    url = f"{TELEGRAM_API.format(token=bot_token)}/getUpdates"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

    if not data.get("ok"):
        return {"collected": 0, "error": data.get("description", "unknown")}

    updates = data.get("result", [])
    if not updates:
        return {"collected": 0}

    messages = []
    highest_update_id = last_offset
    for update in updates:
        uid = update.get("update_id", 0)
        if highest_update_id is None or uid > highest_update_id:
            highest_update_id = uid

        parsed = _parse_update(update)
        if parsed:
            messages.append(parsed)

    if messages:
        await context.garden.write_seed("telegram", {"messages": messages})

        # Auto-reply via ChatBridge (vault-aware, same system prompt as CLI/GUI)
        user_texts = [m["text"] for m in messages if m.get("text")]
        if user_texts and context.chat:
            combined = "\n".join(user_texts)
            reply = await context.chat.chat(message=combined)
            if reply and reply.strip():
                context.logger.info("auto_reply_sent", length=len(reply))
            else:
                context.logger.warning("auto_reply_empty")

    if highest_update_id is not None:
        _save_offset(state_file, highest_update_id)

    return {"collected": len(messages)}


@execute.setup
async def setup(cred_store):
    """Configure Telegram bot credentials with token validation and chat_id auto-detection."""
    import click
    import httpx

    click.echo("Telegram Bot Setup")
    bot_token = click.prompt("  Bot token (from @BotFather)")

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10.0)
        if resp.status_code != 200:
            click.echo(f"Error: Invalid bot token (HTTP {resp.status_code})", err=True)
            raise SystemExit(1)
        bot_name = resp.json().get("result", {}).get("username", "unknown")
        click.echo(f"  Verified bot: @{bot_name}")

        # Try auto-detecting chat_id from recent messages
        click.echo("  Checking for recent messages to auto-detect chat ID...")
        click.echo("  (Send a message to the bot now if you haven't already)")
        r = await client.get(
            f"https://api.telegram.org/bot{bot_token}/getUpdates",
            params={"limit": 10, "timeout": 10},
            timeout=20.0,
        )
        detected_ids: list[tuple[int, str]] = []
        if r.status_code == 200 and r.json().get("ok"):
            for update in r.json().get("result", []):
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                cid = chat.get("id")
                name = chat.get("first_name") or chat.get("title") or str(cid)
                if cid and (cid, name) not in detected_ids:
                    detected_ids.append((cid, name))

        if detected_ids:
            click.echo("  Detected chats:")
            for i, (cid, name) in enumerate(detected_ids, 1):
                click.echo(f"    [{i}] {name} (ID: {cid})")
            if len(detected_ids) == 1:
                chat_id = str(detected_ids[0][0])
                click.echo(f"  Auto-selected chat ID: {chat_id}")
            else:
                choice = click.prompt("  Select chat number", type=int, default=1)
                idx = max(0, min(choice - 1, len(detected_ids) - 1))
                chat_id = str(detected_ids[idx][0])
        else:
            click.echo("  No recent messages found. Please enter chat ID manually.")
            chat_id = click.prompt("  Chat ID (numeric)")

    if not chat_id.lstrip("-").isdigit():
        click.echo(f"Error: chat_id must be numeric, got '{chat_id}'", err=True)
        raise SystemExit(1)

    await cred_store.store("telegram-input", {"bot_token": bot_token, "chat_id": chat_id})
    click.echo("  Credentials saved.")


@execute.notify
async def notify(context) -> dict:
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

    url = f"{TELEGRAM_API.format(token=bot_token)}/sendMessage"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=10.0,
        )
        response.raise_for_status()

    return {"sent": True, "chat_id": chat_id}
