"""Tests for the email-sender plugin."""

from unittest.mock import AsyncMock, MagicMock, patch


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {
        "smtp_server": "smtp.example.com",
        "smtp_port": "587",
        "email": "sender@example.com",
        "password": "secret",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.logger = MagicMock()
    return ctx


def _load_plugin():
    """Import the email-sender plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("email_sender", "plugins/email-sender/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── test_execute_sends_email ─────────────────────────────────────────


async def test_execute_sends_email() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "recipient@example.com",
            "subject": "Hello from BSage",
            "body": "This is a test email.",
        },
    )

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["sent"] is True
    assert result["to"] == "recipient@example.com"
    assert result["subject"] == "Hello from BSage"

    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("sender@example.com", "secret")
    mock_server.sendmail.assert_called_once()

    send_args = mock_server.sendmail.call_args[0]
    assert send_args[0] == "sender@example.com"
    assert send_args[1] == ["recipient@example.com"]

    ctx.garden.write_action.assert_awaited_once()


async def test_execute_sends_email_with_cc() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "recipient@example.com",
            "subject": "Test",
            "body": "Body",
            "cc": "cc1@example.com, cc2@example.com",
        },
    )

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["sent"] is True

    send_args = mock_server.sendmail.call_args[0]
    recipients = send_args[1]
    assert "recipient@example.com" in recipients
    assert "cc1@example.com" in recipients
    assert "cc2@example.com" in recipients


# ── test_execute_missing_fields ──────────────────────────────────────


async def test_execute_missing_to() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "subject": "Hello",
            "body": "Content",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "required" in result["error"]


async def test_execute_missing_subject() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "recipient@example.com",
            "body": "Content",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "required" in result["error"]


async def test_execute_missing_body() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "recipient@example.com",
            "subject": "Hello",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "required" in result["error"]


async def test_execute_empty_input() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(input_data={})
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "required" in result["error"]


async def test_execute_none_input() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(input_data=None)
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "required" in result["error"]


# ── test_execute_invalid_email ───────────────────────────────────────


async def test_execute_invalid_email_no_at_sign() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "not-an-email",
            "subject": "Hello",
            "body": "Content",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "Invalid email" in result["error"]


async def test_execute_invalid_email_no_domain() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "user@",
            "subject": "Hello",
            "body": "Content",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "Invalid email" in result["error"]


async def test_execute_invalid_email_spaces() -> None:
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "user @example.com",
            "subject": "Hello",
            "body": "Content",
        },
    )
    result = await execute_fn(ctx)
    assert result["sent"] is False
    assert "Invalid email" in result["error"]


# ── test_execute_logs_action_without_body ────────────────────────────


async def test_execute_logs_action_without_body() -> None:
    """Verify write_action is called but does not include the email body."""
    execute_fn = _load_plugin()
    ctx = _make_context(
        input_data={
            "to": "recipient@example.com",
            "subject": "Confidential",
            "body": "This is secret content that should not appear in logs.",
        },
    )

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["sent"] is True
    ctx.garden.write_action.assert_awaited_once()

    # The action log message should not contain the email body
    action_args = ctx.garden.write_action.call_args[0]
    action_message = str(action_args)
    assert "secret content" not in action_message
