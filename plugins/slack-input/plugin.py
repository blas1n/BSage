"""Slack message input Plugin — polls Slack channels for new messages."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from bsage.plugin import plugin


def _state_path(context) -> Path:
    """Resolve the offset state file path within the vault."""
    return context.garden.resolve_plugin_state_path("slack-input")


def _load_cursor(path: Path) -> str | None:
    """Load last cursor from state file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None
    return data.get("cursor")


def _save_cursor(path: Path, cursor: str) -> None:
    """Persist cursor to state file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"cursor": cursor}))
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _is_valid_channel_id(channel_id: str) -> bool:
    """Check that channel_id matches Slack format (C/G/D prefix + alphanumeric)."""
    import re

    return bool(re.match(r"^[CGD][A-Za-z0-9]{2,}$", channel_id))


def _parse_message(event: dict) -> dict | None:
    """Extract normalized message dict from Slack event."""
    if event.get("type") != "message" or event.get("subtype"):
        return None

    return {
        "user": event.get("user"),
        "username": event.get("username"),
        "text": event.get("text", ""),
        "ts": event.get("ts"),
        "thread_ts": event.get("thread_ts"),
    }


@plugin(
    name="slack-input",
    version="1.0.0",
    category="input",
    description="Polls Slack channel for new messages and stores them in the vault",
    trigger={"type": "cron", "schedule": "*/5 * * * *"},
    credentials=[
        {
            "name": "bot_token",
            "description": "Slack Bot User OAuth Token (starts with xoxb-)",
            "required": True,
        },
        {
            "name": "channel_id",
            "description": "Channel ID to monitor (starts with C)",
            "required": True,
        },
    ],
)
async def execute(context: Any) -> dict:
    """Poll Slack conversations.history and write new messages to seeds."""
    import httpx

    creds = context.credentials
    bot_token = creds.get("bot_token", "")
    channel_id = creds.get("channel_id", "")

    if not bot_token or not channel_id:
        return {"collected": 0, "error": "missing bot_token or channel_id"}

    # Re-validate channel_id at execution time (credential file may be edited externally)
    if not _is_valid_channel_id(channel_id):
        return {"collected": 0, "error": f"invalid channel_id: {channel_id}"}

    state_file = _state_path(context)
    cursor = _load_cursor(state_file)

    # Fetch recent messages
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }

    params = {"channel": channel_id, "limit": 50}
    if cursor:
        params["oldest"] = cursor

    url = "https://slack.com/api/conversations.history"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            context.logger.error("slack_api_error", status_code=e.response.status_code)
            return {"collected": 0, "error": f"API error: HTTP {e.response.status_code}"}
        except Exception as e:
            context.logger.error("slack_api_error", error=str(e))
            return {"collected": 0, "error": "Failed to fetch messages"}

    if not data.get("ok"):
        error = data.get("error", "unknown")
        return {"collected": 0, "error": error}

    messages = data.get("messages", [])
    if not messages:
        return {"collected": 0}

    # Parse messages (reverse order to get oldest first)
    parsed_messages = []
    latest_ts: str | None = cursor

    for msg_event in reversed(messages):
        # Always advance cursor, even for unparseable messages
        ts = msg_event.get("ts")
        if ts:
            latest_ts = ts
        parsed = _parse_message(msg_event)
        if parsed:
            parsed_messages.append(parsed)

    if parsed_messages:
        try:
            await context.garden.write_seed("slack", {"messages": parsed_messages})
        except Exception:
            context.logger.exception("slack_seed_write_failed")
            return {"collected": 0, "error": "failed to write seed"}

        # Auto-reply via ChatBridge
        user_texts = [m["text"] for m in parsed_messages if m.get("text")]
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

    if latest_ts and latest_ts != cursor:
        _save_cursor(state_file, latest_ts)

    return {"collected": len(parsed_messages)}


@execute.setup
async def setup(cred_store: Any):
    """Configure Slack credentials with token validation and channel selection."""
    import click
    import httpx

    click.echo("Slack Bot Setup")
    bot_token = click.prompt("  Bot User OAuth Token (xoxb-...)", hide_input=True)

    # Validate token and list channels
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }

    # Verify token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/auth.test",
            headers=headers,
            timeout=10.0,
        )
        if resp.status_code != 200:
            click.echo(f"Error: Invalid token (HTTP {resp.status_code})", err=True)
            raise SystemExit(1)

        auth_data = resp.json()
        if not auth_data.get("ok"):
            click.echo(f"Error: {auth_data.get('error', 'unknown')}", err=True)
            raise SystemExit(1)

        team_name = auth_data.get("team")
        user_name = auth_data.get("user")
        click.echo(f"  Verified: {user_name} @ {team_name}")

        # List channels
        click.echo("  Fetching channels...")
        resp = await client.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params={"limit": 50},
            timeout=10.0,
        )

        channels_data = resp.json()
        if not channels_data.get("ok"):
            click.echo(
                "  Warning: Could not fetch channels, please enter channel ID manually", err=True
            )
            channel_id = click.prompt("  Channel ID (C...)")
        else:
            channels = channels_data.get("channels", [])
            if not channels:
                click.echo("  No channels found, please enter channel ID manually", err=True)
                channel_id = click.prompt("  Channel ID (C...)")
            else:
                click.echo("  Available channels:")
                for i, ch in enumerate(channels[:20], 1):
                    click.echo(f"    [{i}] #{ch['name']} ({ch['id']})")

                choice = click.prompt("  Select channel number", type=int, default=1)
                channel_id = channels[min(max(choice - 1, 0), min(len(channels), 20) - 1)]["id"]

    if not _is_valid_channel_id(channel_id):
        click.echo(f"Error: invalid channel_id format, got '{channel_id}'", err=True)
        raise SystemExit(1)

    await cred_store.store("slack-input", {"bot_token": bot_token, "channel_id": channel_id})
    click.echo("  Credentials saved.")


@execute.notify
async def notify(context: Any) -> dict:
    """Send a message back to the Slack channel via Bot API."""
    import httpx

    creds = context.credentials
    message = (context.input_data or {}).get("message", "")

    if not message:
        return {"sent": False, "reason": "no message provided"}

    bot_token = creds.get("bot_token", "")
    channel_id = creds.get("channel_id", "")

    if not bot_token or not channel_id:
        return {"sent": False, "reason": "missing bot_token or channel_id"}

    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "channel": channel_id,
        "text": message,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json=payload,
            timeout=10.0,
        )
        try:
            data = resp.json()
        except Exception:
            context.logger.warning("notify_json_parse_failed", status=resp.status_code)
            return {"sent": False, "error": f"HTTP {resp.status_code}: non-JSON response"}

    if data.get("ok"):
        return {"sent": True, "ts": data.get("ts")}
    else:
        return {"sent": False, "error": data.get("error", "unknown")}
