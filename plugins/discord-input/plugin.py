"""Discord message input Plugin — polls Discord channel for new messages."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from bsage.plugin import plugin


def _state_path(context) -> Path:
    """Resolve the state file path within the vault."""
    return context.garden.resolve_plugin_state_path("discord-input")


def _load_timestamp(path: Path) -> int | None:
    """Load last message timestamp from state file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
    return data.get("last_message_timestamp")


def _save_timestamp(path: Path, timestamp: int) -> None:
    """Persist last message timestamp to state file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"last_message_timestamp": timestamp}))
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _is_valid_channel_id(channel_id: str) -> bool:
    """Check that channel_id is a numeric Discord snowflake."""
    return str(channel_id).isdigit() and 0 < len(channel_id) <= 20


def _parse_message(msg: dict) -> dict | None:
    """Extract normalized message dict from Discord message object."""
    if not msg.get("content"):
        return None

    return {
        "author": msg.get("author", {}).get("username", "unknown"),
        "author_id": msg.get("author", {}).get("id"),
        "content": msg.get("content", ""),
        "id": msg.get("id"),
        "timestamp": msg.get("timestamp"),
    }


@plugin(
    name="discord-input",
    version="1.0.0",
    category="input",
    description="Polls Discord channel for new messages and stores them in the vault",
    trigger={"type": "cron", "schedule": "*/5 * * * *"},
    credentials=[
        {
            "name": "bot_token",
            "description": "Discord Bot token (from Discord Developer Portal)",
            "required": True,
        },
        {
            "name": "channel_id",
            "description": "Channel ID to monitor (numeric)",
            "required": True,
        },
    ],
)
async def execute(context: Any) -> dict:
    """Poll Discord channel.messages and write new messages to seeds."""
    import httpx
    from dateutil import parser as dateutil_parser

    creds = context.credentials
    bot_token = creds.get("bot_token", "")
    channel_id = creds.get("channel_id", "")

    if not bot_token or not channel_id:
        return {"collected": 0, "error": "missing bot_token or channel_id"}

    # Re-validate channel_id at execution time (credential file may be edited externally)
    if not _is_valid_channel_id(channel_id):
        return {"collected": 0, "error": f"invalid channel_id: {channel_id}"}

    state_file = _state_path(context)
    last_timestamp = _load_timestamp(state_file)

    # Build Discord API request
    headers = {
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "BSage Discord Plugin",
    }

    params = {"limit": 50}

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            messages = resp.json()

            if isinstance(messages, dict) and "code" in messages:
                error = messages.get("message", "unknown error")
                return {"collected": 0, "error": error}

        except httpx.HTTPStatusError as e:
            context.logger.error("discord_api_error", status_code=e.response.status_code)
            return {"collected": 0, "error": f"API error: HTTP {e.response.status_code}"}
        except Exception as e:
            context.logger.error("discord_api_error", error=str(e))
            return {"collected": 0, "error": "Failed to fetch messages"}

    # Parse messages (Discord returns newest first, so reverse for chronological order)
    parsed_messages = []
    highest_timestamp = last_timestamp or 0

    for msg_data in reversed(messages):
        # Parse timestamp
        try:
            ts_str = msg_data.get("timestamp", "")
            ts = dateutil_parser.isoparse(ts_str).timestamp()
            ts_int = int(ts * 1000)
            if ts_int and (last_timestamp is None or ts_int > last_timestamp):
                parsed = _parse_message(msg_data)
                if parsed:
                    parsed_messages.append(parsed)
                    if ts_int > highest_timestamp:
                        highest_timestamp = ts_int
        except Exception:
            context.logger.warning("discord_timestamp_parse_failed", msg_id=msg_data.get("id"))

    if parsed_messages:
        try:
            await context.garden.write_seed("discord", {"messages": parsed_messages})
        except Exception:
            context.logger.exception("discord_seed_write_failed")
            return {"collected": 0, "error": "failed to write seed"}

        # Auto-reply via ChatBridge (only after seed write succeeds)
        user_texts = [m["content"] for m in parsed_messages if m.get("content")]
        if user_texts and context.chat:
            combined = "\n".join(user_texts)
            try:
                reply = await context.chat.chat(message=combined)
                if reply and reply.strip():
                    context.logger.info("auto_reply_sent", length=len(reply))
                else:
                    context.logger.warning("auto_reply_empty")
            except Exception:
                context.logger.warning("auto_reply_failed", exc_info=True)

    if highest_timestamp > (last_timestamp or 0):
        _save_timestamp(state_file, highest_timestamp)

    return {"collected": len(parsed_messages)}


@execute.setup
async def setup(cred_store: Any):
    """Configure Discord credentials with token validation and channel selection."""
    import click
    import httpx

    click.echo("Discord Bot Setup")
    bot_token = click.prompt("  Bot Token (from Developer Portal)", hide_input=True)

    headers = {
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "BSage Discord Plugin",
    }

    # Validate token
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers=headers,
            timeout=10.0,
        )

        if resp.status_code != 200:
            click.echo(f"Error: Invalid token (HTTP {resp.status_code})", err=True)
            raise SystemExit(1)

        user_data = resp.json()
        if "id" not in user_data:
            click.echo(f"Error: {user_data.get('message', 'unknown')}", err=True)
            raise SystemExit(1)

        bot_name = user_data.get("username", "unknown")
        click.echo(f"  Verified bot: {bot_name}#{user_data.get('discriminator', '0')}")

        # List guilds
        click.echo("  Fetching guilds...")
        resp = await client.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers=headers,
            timeout=10.0,
        )

        if resp.status_code != 200:
            click.echo("  Could not fetch guilds, please enter channel ID manually", err=True)
            channel_id = click.prompt("  Channel ID (numeric)")
        else:
            guilds = resp.json()
            if not guilds:
                click.echo("  Bot not in any guilds, please enter channel ID manually", err=True)
                channel_id = click.prompt("  Channel ID")
            else:
                click.echo("  Available guilds:")
                for i, guild in enumerate(guilds[:10], 1):
                    click.echo(f"    [{i}] {guild['name']} ({guild['id']})")

                guild_choice = click.prompt("  Select guild number", type=int, default=1)
                idx = min(max(guild_choice - 1, 0), min(len(guilds), 10) - 1)
                selected_guild = guilds[idx]["id"]

                # Fetch channels in guild
                click.echo("  Fetching channels...")
                resp = await client.get(
                    f"https://discord.com/api/v10/guilds/{selected_guild}/channels",
                    headers=headers,
                    timeout=10.0,
                )

                if resp.status_code != 200:
                    click.echo("  Could not fetch channels", err=True)
                    channel_id = click.prompt("  Channel ID")
                else:
                    channels = [
                        ch
                        for ch in resp.json()
                        if ch.get("type") == 0  # 0 = text channel
                    ]
                    if not channels:
                        click.echo("  No text channels found", err=True)
                        channel_id = click.prompt("  Channel ID")
                    else:
                        click.echo("  Text channels:")
                        for i, ch in enumerate(channels[:20], 1):
                            click.echo(f"    [{i}] #{ch['name']} ({ch['id']})")

                        ch_choice = click.prompt("  Select channel number", type=int, default=1)
                        idx = min(max(ch_choice - 1, 0), min(len(channels), 20) - 1)
                        channel_id = channels[idx]["id"]

    if not _is_valid_channel_id(channel_id):
        click.echo(f"Error: channel_id must be numeric, got '{channel_id}'", err=True)
        raise SystemExit(1)

    await cred_store.store("discord-input", {"bot_token": bot_token, "channel_id": str(channel_id)})
    click.echo("  Credentials saved.")


@execute.notify
async def notify(context: Any) -> dict:
    """Send a message back to the Discord channel via Bot API."""
    import httpx

    creds = context.credentials
    message = (context.input_data or {}).get("message", "")

    if not message:
        return {"sent": False, "reason": "no message provided"}

    bot_token = creds.get("bot_token", "")
    channel_id = creds.get("channel_id", "")

    if not bot_token or not channel_id:
        return {"sent": False, "reason": "missing bot_token or channel_id"}

    if not _is_valid_channel_id(channel_id):
        return {"sent": False, "reason": f"invalid channel_id: {channel_id}"}

    headers = {
        "Authorization": f"Bot {bot_token}",
        "User-Agent": "BSage Discord Plugin",
        "Content-Type": "application/json",
    }

    payload = {"content": message}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers=headers,
            json=payload,
            timeout=10.0,
        )

    if resp.status_code in (200, 201):
        try:
            data = resp.json()
        except Exception:
            context.logger.warning("notify_json_parse_failed", status=resp.status_code)
            return {"sent": True, "message_id": None}
        return {"sent": True, "message_id": data.get("id")}
    else:
        try:
            error = resp.json().get("message", "unknown") if resp.text else str(resp.status_code)
        except Exception:
            context.logger.warning("notify_error_parse_failed", status=resp.status_code)
            error = f"HTTP {resp.status_code}"
        return {"sent": False, "error": error}
