"""Tests for the email-input plugin."""

import email.message
from unittest.mock import AsyncMock, MagicMock, patch


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {
        "imap_server": "imap.example.com",
        "email": "user@example.com",
        "password": "secret",
        "folder": "INBOX",
        "max_emails": "20",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("email_input", "plugins/email-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


def _build_raw_email(from_addr: str, to_addr: str, subject: str, body: str) -> bytes:
    """Build a minimal RFC822 email as raw bytes."""
    msg = email.message.EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = "Wed, 25 Feb 2026 10:00:00 +0000"
    msg.set_content(body)
    return msg.as_bytes()


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_collects_emails() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    raw1 = _build_raw_email("alice@example.com", "me@example.com", "Hello", "Body one")
    raw2 = _build_raw_email("bob@example.com", "me@example.com", "Hi", "Body two")

    mock_imap = MagicMock()
    mock_imap.login = MagicMock()
    mock_imap.select = MagicMock(return_value=("OK", [b"2"]))
    mock_imap.search = MagicMock(return_value=("OK", [b"1 2"]))
    mock_imap.fetch = MagicMock(
        side_effect=[
            ("OK", [(b"1 (RFC822 {1234})", raw1)]),
            ("OK", [(b"2 (RFC822 {1234})", raw2)]),
        ]
    )
    mock_imap.logout = MagicMock()

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        result = await execute_fn(ctx)

    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "email"
    emails = call_args[0][1]["emails"]
    assert len(emails) == 2
    assert emails[0]["from"] == "alice@example.com"
    assert emails[0]["subject"] == "Hello"
    assert "Body one" in emails[0]["body"]
    assert emails[1]["from"] == "bob@example.com"
    assert emails[1]["subject"] == "Hi"


async def test_execute_empty_inbox() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context()

    mock_imap = MagicMock()
    mock_imap.login = MagicMock()
    mock_imap.select = MagicMock(return_value=("OK", [b"0"]))
    mock_imap.search = MagicMock(return_value=("OK", [b""]))
    mock_imap.logout = MagicMock()

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        result = await execute_fn(ctx)

    assert result == {"collected": 0}
    # write_seed should NOT be called when there are no emails
    ctx.garden.write_seed.assert_not_awaited()


async def test_execute_respects_max_emails() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        credentials={
            "imap_server": "imap.example.com",
            "email": "user@example.com",
            "password": "secret",
            "folder": "INBOX",
            "max_emails": "1",
        }
    )

    raw1 = _build_raw_email("alice@example.com", "me@example.com", "First", "Body 1")
    raw2 = _build_raw_email("bob@example.com", "me@example.com", "Second", "Body 2")

    mock_imap = MagicMock()
    mock_imap.login = MagicMock()
    mock_imap.select = MagicMock(return_value=("OK", [b"2"]))
    # Return 2 IDs but max_emails=1 should only fetch the first
    mock_imap.search = MagicMock(return_value=("OK", [b"1 2"]))
    mock_imap.fetch = MagicMock(
        side_effect=[
            ("OK", [(b"1 (RFC822 {1234})", raw1)]),
            ("OK", [(b"2 (RFC822 {1234})", raw2)]),
        ]
    )
    mock_imap.logout = MagicMock()

    with patch("imaplib.IMAP4_SSL", return_value=mock_imap):
        result = await execute_fn(ctx)

    # Only 1 email should be collected due to max_emails=1
    assert result == {"collected": 1}
    # fetch should only have been called once
    assert mock_imap.fetch.call_count == 1
