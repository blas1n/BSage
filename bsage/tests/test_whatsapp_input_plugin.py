"""Tests for the whatsapp-input plugin."""

import hashlib
import hmac
import json
from unittest.mock import MagicMock

import pytest

from bsage.tests.conftest import make_plugin_context

_DEFAULT_CREDS = {
    "access_token": "whatsapp_token_123",
    "phone_number_id": "123456789",
    "verify_token": "my_verify_token",
}


def _make_context(input_data: dict | None = None) -> MagicMock:
    return make_plugin_context(
        input_data=input_data or {},
        credentials=_DEFAULT_CREDS,
    )


def _load_plugin():
    """Import the plugin module and return execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "whatsapp_input", "plugins/whatsapp-input/plugin.py"
    )
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
async def test_execute_missing_signature_rejected() -> None:
    """Test that execute rejects requests without a webhook signature."""
    execute_fn = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    raw_body = json.dumps(payload)
    input_data = {"body": payload, "raw_body": raw_body}  # No x-hub-signature-256 header
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "Missing webhook signature" in result.get("error", "")


@pytest.mark.asyncio
async def test_execute_invalid_signature() -> None:
    """Test that execute rejects invalid webhook signatures."""
    execute_fn = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    raw_body = json.dumps(payload)
    input_data = {
        "x-hub-signature-256": "sha256=invalid_signature",
        "body": payload,
        "raw_body": raw_body,
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

    # Create valid signature against raw body string
    raw_body = json.dumps(payload)
    expected_signature = hmac.new(
        verify_token.encode(),
        raw_body.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        "x-hub-signature-256": f"sha256={expected_signature}",
        "body": payload,
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

    raw_body = json.dumps(payload)
    signature = hmac.new(
        verify_token.encode(),
        raw_body.encode(),
        hashlib.sha256,
    ).hexdigest()

    input_data = {
        "x-hub-signature-256": f"sha256={signature}",
        "body": payload,
        "raw_body": raw_body,
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["collected"] == 0


@pytest.mark.asyncio
async def test_execute_missing_raw_body() -> None:
    """Test that execute rejects requests without raw_body."""
    execute_fn = _load_plugin()
    payload = {"entry": [{"changes": [{"value": {"messages": []}}]}]}
    input_data = {
        "x-hub-signature-256": "sha256=something",
        "body": payload,
        # No raw_body — signature cannot be verified
    }
    ctx = _make_context(input_data=input_data)

    result = await execute_fn(ctx)

    assert result["success"] is False
    assert "raw" in result.get("error", "").lower()
