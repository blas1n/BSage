"""WhatsApp message input Plugin — receives messages via webhook from Meta WhatsApp Cloud API."""

import hashlib
import hmac
from collections import OrderedDict
from typing import Any

from bsage.plugin import plugin

# Module-level dedup cache — LRU bounded to last 200 message IDs.
# Handles Meta webhook retries without requiring persistent state.
_SEEN_MSG_IDS: OrderedDict = OrderedDict()
_DEDUP_MAX = 200


def _verify_webhook_signature(payload: str, signature: str, app_secret: str) -> bool:
    """Verify WhatsApp webhook signature using SHA256 HMAC.

    Meta signs payloads with the App Secret, NOT the verify token.
    See: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests
    """
    expected = hmac.new(
        app_secret.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def _parse_incoming_message(webhook_event: dict) -> dict | None:
    """Extract message from WhatsApp webhook entry object."""
    entries = webhook_event.get("entry", [])
    if not entries:
        return None
    entry = entries[0]
    changes_list = entry.get("changes", [])
    if not changes_list:
        return None
    changes = changes_list[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return None

    msg = messages[0]
    if msg.get("type") != "text":
        return None

    text_obj = msg.get("text", {})
    if not text_obj.get("body"):
        return None

    return {
        "from": msg.get("from"),
        "id": msg.get("id"),
        "timestamp": msg.get("timestamp"),
        "text": text_obj.get("body", ""),
    }


@plugin(
    name="whatsapp-input",
    version="1.0.0",
    category="input",
    description="Receives WhatsApp messages via webhook from Meta Cloud API",
    trigger={"type": "webhook"},
    credentials=[
        {
            "name": "access_token",
            "description": "WhatsApp Business Account access token (from Meta Business Platform)",
            "required": True,
        },
        {
            "name": "phone_number_id",
            "description": "Phone number ID associated with your WhatsApp Business Account",
            "required": True,
        },
        {
            "name": "verify_token",
            "description": "Token for webhook challenge verification (set in Meta app config)",
            "required": True,
        },
        {
            "name": "app_secret",
            "description": (
                "App Secret from Meta App Dashboard (used for webhook signature verification)"
            ),
            "required": True,
        },
    ],
)
async def execute(context: Any) -> dict:
    """Process incoming WhatsApp webhook event."""
    webhook_data = context.input_data or {}

    # Handle challenge verification (GET request from Meta during setup)
    if "hub.challenge" in webhook_data:
        creds = context.credentials or {}
        stored_verify_token = creds.get("verify_token", "")
        received_verify_token = webhook_data.get("hub.verify_token", "")
        if not stored_verify_token or received_verify_token != stored_verify_token:
            context.logger.warning("whatsapp_invalid_verify_token")
            return {"success": False, "error": "Invalid verify token"}
        challenge = webhook_data.get("hub.challenge")
        return {"challenge": challenge}

    # Verify webhook signature
    creds = context.credentials or {}
    app_secret = creds.get("app_secret", "")

    signature = webhook_data.get("x-hub-signature-256", "")
    # Strip "sha256=" prefix from Meta's webhook signature format
    if signature.startswith("sha256="):
        signature = signature[7:]

    # Use raw_body for signature verification — re-serializing parsed JSON
    # produces different bytes (key order, whitespace) and breaks HMAC.
    raw_body = webhook_data.get("raw_body", "")
    if not raw_body:
        context.logger.warning("whatsapp_raw_body_missing")
        return {"success": False, "error": "Missing raw request body"}

    if not signature:
        context.logger.warning("whatsapp_signature_missing")
        return {"success": False, "error": "Missing webhook signature"}

    if not app_secret:
        context.logger.warning("whatsapp_app_secret_missing")
        return {"success": False, "error": "Missing app_secret credential"}

    if not _verify_webhook_signature(raw_body, signature, app_secret):
        context.logger.warning("whatsapp_signature_invalid")
        return {"success": False, "error": "Invalid signature"}

    # Parse message — webhook_data is the flattened Meta payload with extra
    # keys (raw_body, x-hub-signature-256) injected by the Gateway.
    parsed = _parse_incoming_message(webhook_data)

    if not parsed:
        return {"collected": 0, "reason": "no text message"}

    # Dedup by Meta message ID to handle webhook retries gracefully.
    msg_id = parsed.get("id", "")
    if msg_id and msg_id in _SEEN_MSG_IDS:
        context.logger.info("whatsapp_duplicate_skipped", msg_id=msg_id)
        return {"collected": 0, "reason": "duplicate message"}

    # Write to seed — include sender phone so notify() can reply.
    # Cache update happens AFTER the write so a failed write doesn't poison
    # the dedup cache (Meta would retry and the message would be lost).
    await context.garden.write_seed(
        "whatsapp",
        {
            "message": parsed,
            "reply_phone": parsed.get("from"),
        },
    )

    # Mark as seen only after successful write.
    if msg_id:
        _SEEN_MSG_IDS[msg_id] = True
        if len(_SEEN_MSG_IDS) > _DEDUP_MAX:
            _SEEN_MSG_IDS.popitem(last=False)

    # Auto-reply via ChatBridge
    if context.chat:
        try:
            reply = await context.chat.chat(message=parsed["text"])
            if reply and reply.strip():
                context.logger.info("auto_reply_sent", length=len(reply))
            else:
                context.logger.warning("auto_reply_empty")
        except Exception:
            context.logger.warning("auto_reply_failed", exc_info=True)

    return {"collected": 1, "from": parsed["from"]}


@execute.setup
def setup(cred_store: Any):
    """Configure WhatsApp credentials."""
    import asyncio

    import click

    click.echo("WhatsApp Business Account Setup")
    click.echo("Get these from https://developers.facebook.com/")
    click.echo("")

    access_token = click.prompt("  Access Token", hide_input=True)
    phone_number_id = click.prompt("  Phone Number ID")
    app_secret = click.prompt(
        "  App Secret (from Meta App Dashboard, for webhook signature)",
        hide_input=True,
    )
    verify_token = click.prompt("  Webhook Verify Token (for challenge verification)")

    click.echo("")
    click.echo("After saving, configure your webhook in Meta App Dashboard:")
    click.echo("  Callback URL: https://your-domain/api/webhooks/whatsapp-input")
    click.echo("  Verify Token: (use the same token you entered above)")
    click.echo("  Subscribe to: messages")

    data = {
        "access_token": access_token,
        "phone_number_id": phone_number_id,
        "app_secret": app_secret,
        "verify_token": verify_token,
    }

    asyncio.run(cred_store.store("whatsapp-input", data))
    click.echo("  Credentials saved.")


@execute.notify
async def notify(context: Any) -> dict:
    """Send a WhatsApp message via Cloud API."""
    import httpx

    creds = context.credentials
    message_text = (context.input_data or {}).get("message", "")

    if not message_text:
        return {"sent": False, "reason": "no message provided"}

    access_token = creds.get("access_token", "")
    phone_number_id = creds.get("phone_number_id", "")

    if not access_token or not phone_number_id:
        return {"sent": False, "reason": "missing credentials"}

    # Get recipient phone number from context (set by execute() in seed's reply_phone)
    recipient = (context.input_data or {}).get("reply_phone", "")
    if not recipient:
        return {"sent": False, "reason": "no recipient phone number"}

    # Normalize to E.164: strip non-digits, prepend '+'
    digits = "".join(c for c in recipient if c.isdigit())
    if not digits or len(digits) < 7 or len(digits) > 15:
        return {"sent": False, "reason": f"invalid phone number: {recipient}"}
    if digits[0] == "0":
        return {"sent": False, "reason": "invalid phone number: missing country code"}
    recipient = "+" + digits

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {
            "body": message_text,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    whatsapp_api_version = "v18.0"
    url = f"https://graph.facebook.com/{whatsapp_api_version}/{phone_number_id}/messages"

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
        except Exception:
            context.logger.warning("notify_api_request_failed", exc_info=True)
            return {"sent": False, "error": "API request failed"}

        try:
            data = resp.json()
        except (ValueError, UnicodeDecodeError):
            context.logger.warning("notify_json_parse_failed", status=resp.status_code)
            return {
                "sent": False,
                "error": f"Invalid JSON response (HTTP {resp.status_code})",
            }

        if data.get("messages"):
            message_id = data["messages"][0].get("id")
            return {"sent": True, "message_id": message_id}

        error = data.get("error", {}).get("message", "unknown error")
        return {"sent": False, "error": error}
