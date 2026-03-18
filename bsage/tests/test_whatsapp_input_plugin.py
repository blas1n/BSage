"""Tests for the whatsapp-input plugin."""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_context(input_data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data or {}
    ctx.credentials = {
        "access_token": "whatsapp_token_123",
        "phone_number_id": "123456789",
        "verify_token": "my_verify_token",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.chat = None
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("whatsapp_input", "plugins/whatsapp-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_execute_webhook_challenge() -> None:
    """Test that execute handles webhook challenge verification."""
    execute_fn = _load_plugin()
    input_data = {"hub.challenge": "challenge_token_123"}
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["challenge"] == "challenge_token_123"


@pytest.mark.asyncio
async def test_execute_invalid_signature() -> None:
    """Test that execute rejects invalid webhook signatures."""
    execute_fn = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    input_data = {
        "x-hub-signature-256": "sha256=invalid_signature",
        "body": payload,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "Invalid signature" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_processes_valid_message() -> None:
    """Test that execute processes valid messages."""
    execute_fn = _load_plugin()
    verify_token = "my_verify_token"
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

    # Create valid signature
    payload_str = json.dumps(payload)
    expected_signature = hmac.new(
        verify_token.encode(),
        payload_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        "x-hub-signature-256": f"sha256={expected_signature}",
        "body": payload,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 1
    ctx.garden.write_seed.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_ignores_non_text_messages() -> None:
    """Test that execute ignores non-text message types."""
    execute_fn = _load_plugin()
    verify_token = "my_verify_token"
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

    payload_str = json.dumps(payload)
    signature = hmac.new(
        verify_token.encode(),
        payload_str.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        "x-hub-signature-256": f"sha256={signature}",
        "body": payload,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 0
