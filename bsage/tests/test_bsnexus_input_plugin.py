"""Tests for the bsnexus-input plugin."""

import importlib.util

import pytest

from bsage.tests.conftest import make_plugin_context


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "bsnexus_input", "plugins/bsnexus-input/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


@pytest.mark.asyncio
async def test_writes_seed_without_title() -> None:
    """BSNexus deliverable payload → raw seed, no pre-computed title.

    The founder-metaphor flow in BSNexus does NOT know what the knowledge
    note should be titled — it only knows what the run produced. The
    plugin forwards the payload as a seed and lets AgentLoop's refiner
    derive a concise title.
    """
    execute = _load_plugin()
    ctx = make_plugin_context(
        input_data={
            "reply_text": "Built the user registration endpoint and wired it into the API router.",
            "files": [{"path": "backend/api/auth.py"}, {"path": "backend/tests/test_auth.py"}],
            "run_id": "run-123",
            "request_intent": "Wire up user registration",
            "project_name": "demo",
        },
    )

    result = await execute(ctx)

    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.await_args
    assert call_args.args[0] == "bsnexus"
    seed = call_args.args[1]
    # Raw — no pre-computed title or content keys that would bypass refiner.
    assert "title" not in seed
    assert "content" not in seed
    # Preserves originating context the refiner can use.
    assert seed["run_id"] == "run-123"
    assert seed["request_intent"] == "Wire up user registration"
    assert seed["reply_text"].startswith("Built the user registration")
    assert seed["files"] == [
        {"path": "backend/api/auth.py"},
        {"path": "backend/tests/test_auth.py"},
    ]
    assert result == {"collected": 1}


@pytest.mark.asyncio
async def test_empty_payload_returns_zero_without_write() -> None:
    """Empty webhook body → no-op, no seed written."""
    execute = _load_plugin()
    ctx = make_plugin_context(input_data={})

    result = await execute(ctx)

    ctx.garden.write_seed.assert_not_awaited()
    assert result == {"collected": 0}


@pytest.mark.asyncio
async def test_missing_input_data_returns_zero() -> None:
    """input_data=None (pre-refiner edge case) → no-op."""
    execute = _load_plugin()
    ctx = make_plugin_context(input_data=None)

    result = await execute(ctx)

    ctx.garden.write_seed.assert_not_awaited()
    assert result == {"collected": 0}


@pytest.mark.asyncio
async def test_drops_webhook_machinery_keys() -> None:
    """Gateway injects ``raw_body``/``x-hub-signature-256`` — strip them."""
    execute = _load_plugin()
    ctx = make_plugin_context(
        input_data={
            "reply_text": "Shipped the landing page.",
            "files": [{"path": "frontend/pages/Landing.tsx"}],
            "raw_body": '{"reply_text":"..."}',
            "x-hub-signature-256": "sha256=deadbeef",
        },
    )

    await execute(ctx)

    seed = ctx.garden.write_seed.await_args.args[1]
    assert "raw_body" not in seed
    assert "x-hub-signature-256" not in seed
    assert seed["reply_text"] == "Shipped the landing page."
