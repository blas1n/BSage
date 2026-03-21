"""Tests for the whatsapp-input plugin."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest

from bsage.tests.conftest import make_httpx_mock, make_plugin_context

_DEFAULT_CREDS = {
    "access_token": "whatsapp_token_123",
    "phone_number_id": "123456789",
    "verify_token": "my_verify_token",
    "app_secret": "my_app_secret",
}


def _make_context(input_data: dict | None = None) -> MagicMock:
    return make_plugin_context(
        input_data=input_data or {},
        credentials=_DEFAULT_CREDS,
    )


def _load_plugin():
    """Import the plugin module and return (execute, notify) functions."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "whatsapp_input", "plugins/whatsapp-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod.execute.__notify__


@pytest.mark.asyncio
async def test_execute_webhook_challenge() -> None:
    """Test that execute handles webhook challenge verification."""
    execute_fn, _ = _load_plugin()
    input_data = {
        "hub.challenge": "challenge_token_123",
        "hub.verify_token": "my_verify_token",
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["challenge"] == "challenge_token_123"


@pytest.mark.asyncio
async def test_execute_webhook_challenge_invalid_token() -> None:
    """Test that execute rejects challenge with wrong verify_token."""
    execute_fn, _ = _load_plugin()
    input_data = {
        "hub.challenge": "challenge_token_123",
        "hub.verify_token": "wrong_token",
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "verify token" in result["error"].lower()


@pytest.mark.asyncio
async def test_execute_webhook_challenge_missing_token() -> None:
    """Test that execute rejects challenge without verify_token."""
    execute_fn, _ = _load_plugin()
    input_data = {"hub.challenge": "challenge_token_123"}
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False


@pytest.mark.asyncio
async def test_execute_missing_signature_rejected() -> None:
    """Test that execute rejects requests without a webhook signature."""
    execute_fn, _ = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    raw_body = json.dumps(payload)
    input_data = {**payload, "raw_body": raw_body}  # No x-hub-signature-256 header
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "Missing webhook signature" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_invalid_signature() -> None:
    """Test that execute rejects invalid webhook signatures."""
    execute_fn, _ = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    raw_body = json.dumps(payload)
    input_data = {
        **payload,
        "x-hub-signature-256": "sha256=invalid_signature",
        "raw_body": raw_body,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "Invalid signature" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_processes_valid_message() -> None:
    """Test that execute processes valid messages."""
    execute_fn, _ = _load_plugin()
    app_secret = "my_app_secret"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "msg123",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "Hello WhatsApp"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    # Create valid signature against raw body string
    raw_body = json.dumps(payload)
    expected_signature = hmac.new(
        app_secret.encode(),
        raw_body.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        **payload,
        "x-hub-signature-256": f"sha256={expected_signature}",
        "raw_body": raw_body,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 1
    assert result["from"] == "1234567890"
    ctx.garden.write_seed.assert_awaited_once()
    # Verify reply_phone is stored in seed for notify()
    seed_data = ctx.garden.write_seed.call_args[0][1]
    assert seed_data["reply_phone"] == "1234567890"


@pytest.mark.asyncio
async def test_execute_ignores_non_text_messages() -> None:
    """Test that execute ignores non-text message types."""
    execute_fn, _ = _load_plugin()
    app_secret = "my_app_secret"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "1234567890",
                                    "id": "msg123",
                                    "timestamp": "1700000000",
                                    "type": "image",  # Not text
                                    "image": {"id": "image123"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }

    raw_body = json.dumps(payload)
    signature = hmac.new(
        app_secret.encode(),
        raw_body.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        **payload,
        "x-hub-signature-256": f"sha256={signature}",
        "raw_body": raw_body,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 0


@pytest.mark.asyncio
async def test_execute_missing_raw_body() -> None:
    """Test that execute rejects requests without raw_body."""
    execute_fn, _ = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    input_data = {
        **payload,
        "x-hub-signature-256": "sha256=something",
        # No raw_body — signature cannot be verified
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "raw" in result.get("error", "").lower()


# ── notify() tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_sends_message() -> None:
    """Test that notify sends a WhatsApp message via Cloud API."""
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"message": "Hello", "reply_phone": "+1234567890"})

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"messages": [{"id": "wamid.123"}]}

    with make_httpx_mock(post_response=mock_resp) as mock_client:
        result = await notify_fn(ctx)

    assert result["sent"] is True
    assert result["message_id"] == "wamid.123"
    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_missing_message() -> None:
    """Test that notify returns error when no message is provided."""
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"reply_phone": "+1234567890"})

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "no message" in result["reason"]


@pytest.mark.asyncio
async def test_notify_missing_credentials() -> None:
    """Test that notify returns error when credentials are missing."""
    _, notify_fn = _load_plugin()
    ctx = make_plugin_context(
        input_data={"message": "hi", "reply_phone": "+1234567890"},
        credentials={
            "access_token": "",
            "phone_number_id": "",
            "verify_token": "",
            "app_secret": "",
        },
    )

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "missing" in result["reason"]


@pytest.mark.asyncio
async def test_notify_missing_recipient() -> None:
    """Test that notify returns error when no recipient phone is provided."""
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"message": "hello"})

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "no recipient" in result["reason"]


@pytest.mark.asyncio
async def test_notify_invalid_phone_number() -> None:
    """Test that notify rejects invalid phone numbers."""
    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"message": "hello", "reply_phone": "abc"})

    result = await notify_fn(ctx)

    assert result["sent"] is False
    assert "invalid phone" in result["reason"]


@pytest.mark.asyncio
async def test_notify_api_error() -> None:
    """Test that notify handles API errors without leaking details."""
    from unittest.mock import AsyncMock

    _, notify_fn = _load_plugin()
    ctx = _make_context(input_data={"message": "hello", "reply_phone": "+1234567890"})

    with make_httpx_mock() as mock_client:
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        result = await notify_fn(ctx)

    assert result["sent"] is False
    # Should NOT expose raw exception message
    assert "connection refused" not in result.get("error", "")
    assert result["error"] == "API request failed"


def _sign_payload(payload: dict, app_secret: str = "my_app_secret") -> dict:
    """Create a signed webhook payload for testing."""
    raw_body = json.dumps(payload)
    signature = hmac.new(app_secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
    return {**payload, "x-hub-signature-256": f"sha256={signature}", "raw_body": raw_body}


@pytest.mark.asyncio
async def test_execute_empty_entry_array() -> None:
    """Test that execute handles empty entry array without IndexError."""
    execute_fn, _ = _load_plugin()
    input_data = _sign_payload({"entry": []})
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 0


@pytest.mark.asyncio
async def test_execute_empty_changes_array() -> None:
    """Test that execute handles empty changes array without IndexError."""
    execute_fn, _ = _load_plugin()
    input_data = _sign_payload({"entry": [{"changes": []}]})
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 0
