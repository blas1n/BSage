"""Tests for bsage.cli — Click CLI commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner

from bsage.cli import _chat_repl, _wait_for_server, main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _mock_settings() -> MagicMock:
    """Create a mock Settings with common gateway defaults."""
    settings = MagicMock()
    settings.gateway_host = "127.0.0.1"
    settings.gateway_port = 8000
    settings.log_level = "info"
    return settings


class TestRunCommand:
    """Test `bsage run` command."""

    @patch("bsage.gateway.app.create_app", return_value=MagicMock())
    @patch("bsage.cli.uvicorn")
    @patch("bsage.cli.get_settings")
    def test_run_no_chat_starts_server_blocking(
        self, mock_settings, mock_uvicorn, mock_create_app, runner
    ) -> None:
        mock_settings.return_value = _mock_settings()
        mock_server = MagicMock()
        mock_uvicorn.Server.return_value = mock_server
        mock_uvicorn.Config.return_value = MagicMock()

        result = runner.invoke(main, ["run", "--no-chat"])
        assert result.exit_code == 0
        mock_server.run.assert_called_once()

    @patch("bsage.cli._chat_repl")
    @patch("bsage.cli._wait_for_server", return_value=True)
    @patch("bsage.cli.uvicorn")
    @patch("bsage.cli.get_settings")
    def test_run_starts_server_and_repl(
        self, mock_settings, mock_uvicorn, mock_wait, mock_repl, runner
    ) -> None:
        mock_settings.return_value = _mock_settings()
        mock_server = MagicMock()
        mock_server.serve = AsyncMock()
        mock_uvicorn.Server.return_value = mock_server
        mock_uvicorn.Config.return_value = MagicMock()

        # Mock the app returned by create_app with app.state.bsage
        mock_state = MagicMock()
        mock_state.chat_bridge = MagicMock()
        mock_state.agent_loop = MagicMock()
        mock_state.garden_writer = MagicMock()
        mock_state.prompt_registry = MagicMock()
        mock_state.retriever = MagicMock()

        mock_app = MagicMock()
        mock_app.state.bsage = mock_state

        # Patch threading.Thread to run its target synchronously (sets server_loop)
        mock_loop = MagicMock()

        class _FakeThread:
            def __init__(self, *, target=None, daemon=False):
                self._target = target

            def start(self):
                if self._target:
                    with (
                        patch("asyncio.new_event_loop", return_value=mock_loop),
                        patch("asyncio.set_event_loop"),
                    ):
                        mock_loop.run_until_complete = MagicMock()
                        self._target()

            def join(self, timeout=None):
                pass

        with (
            patch("bsage.cli.threading.Thread", _FakeThread),
            patch("bsage.gateway.app.create_app", return_value=mock_app),
        ):
            result = runner.invoke(main, ["run"])

        assert result.exit_code == 0
        mock_wait.assert_called_once()
        mock_repl.assert_called_once()
        assert mock_server.should_exit is True

    @patch("bsage.gateway.app.create_app", return_value=MagicMock())
    @patch("bsage.cli._wait_for_server", return_value=False)
    @patch("bsage.cli.uvicorn")
    @patch("bsage.cli.get_settings")
    def test_run_exits_if_server_fails(
        self, mock_settings, mock_uvicorn, mock_wait, mock_create_app, runner
    ) -> None:
        mock_settings.return_value = _mock_settings()
        mock_server = MagicMock()
        mock_server.serve = AsyncMock()
        mock_uvicorn.Server.return_value = mock_server
        mock_uvicorn.Config.return_value = MagicMock()

        result = runner.invoke(main, ["run"])
        assert result.exit_code == 1
        assert "failed to start" in result.output


class TestWaitForServer:
    """Test _wait_for_server health-check polling."""

    @patch("bsage.cli.time.sleep")
    @patch("bsage.cli.httpx.get")
    def test_returns_true_when_healthy(self, mock_get, mock_sleep) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        assert _wait_for_server("http://localhost:8000") is True

    @patch("bsage.cli.time.monotonic", side_effect=[0, 0.5, 1.0, 31.0])
    @patch("bsage.cli.time.sleep")
    @patch("bsage.cli.httpx.get", side_effect=httpx.ConnectError("refused"))
    def test_returns_false_on_timeout(self, mock_get, mock_sleep, mock_time) -> None:
        assert _wait_for_server("http://localhost:8000") is False


class TestChatRepl:
    """Test _chat_repl interactive loop with ChatBridge."""

    @staticmethod
    def _make_bridge_and_loop():
        """Create a mock ChatBridge and event loop for testing."""
        import asyncio

        chat_bridge = MagicMock()
        loop = MagicMock(spec=asyncio.AbstractEventLoop)
        return chat_bridge, loop

    @patch("bsage.cli.asyncio.run_coroutine_threadsafe")
    @patch("bsage.cli.click.prompt", side_effect=["Hello", "/quit"])
    def test_send_and_quit(self, mock_prompt, mock_coro) -> None:
        chat_bridge, loop = self._make_bridge_and_loop()
        mock_future = MagicMock()
        mock_future.result.return_value = "Hi there!"
        mock_coro.return_value = mock_future

        # Capture call args at invocation time (history is mutable)
        captured_calls: list[dict] = []
        original_chat = chat_bridge.chat

        def _capture(**kwargs):
            captured_calls.append(
                {
                    "message": kwargs["message"],
                    "history": list(kwargs["history"]),
                }
            )
            return original_chat(**kwargs)

        chat_bridge.chat = _capture

        _chat_repl(chat_bridge, loop)

        mock_coro.assert_called_once()
        assert len(captured_calls) == 1
        assert captured_calls[0]["message"] == "Hello"
        assert captured_calls[0]["history"] == []
        assert mock_coro.call_args[0][1] is loop

    @patch("bsage.cli.click.prompt", side_effect=["/quit"])
    def test_quit_immediately(self, mock_prompt) -> None:
        chat_bridge, loop = self._make_bridge_and_loop()
        _chat_repl(chat_bridge, loop)

    @patch("bsage.cli.click.prompt", side_effect=EOFError)
    def test_eof_exits_gracefully(self, mock_prompt) -> None:
        chat_bridge, loop = self._make_bridge_and_loop()
        _chat_repl(chat_bridge, loop)

    @patch("bsage.cli.asyncio.run_coroutine_threadsafe")
    @patch("bsage.cli.click.prompt", side_effect=["Hello", "/quit"])
    def test_connection_lost_continues(self, mock_prompt, mock_coro) -> None:
        chat_bridge, loop = self._make_bridge_and_loop()
        mock_coro.return_value = MagicMock()
        mock_coro.return_value.result.side_effect = Exception("connection lost")

        _chat_repl(chat_bridge, loop)
        # Error is caught, user can /quit

    @patch("bsage.cli.asyncio.run_coroutine_threadsafe")
    @patch("bsage.cli.click.prompt", side_effect=["Hello", "World", "/quit"])
    def test_history_accumulates(self, mock_prompt, mock_coro) -> None:
        chat_bridge, loop = self._make_bridge_and_loop()
        mock_future = MagicMock()
        mock_future.result.return_value = "Reply"
        mock_coro.return_value = mock_future

        # Capture call args at invocation time (history is mutable)
        captured_calls: list[dict] = []
        original_chat = chat_bridge.chat

        def _capture(**kwargs):
            captured_calls.append(
                {
                    "message": kwargs["message"],
                    "history": list(kwargs["history"]),
                }
            )
            return original_chat(**kwargs)

        chat_bridge.chat = _capture

        _chat_repl(chat_bridge, loop)

        # Two messages sent before /quit
        assert mock_coro.call_count == 2
        # First call: message="Hello", empty history
        assert captured_calls[0]["message"] == "Hello"
        assert captured_calls[0]["history"] == []
        # Second call: message="World", history includes first exchange
        assert captured_calls[1]["message"] == "World"
        assert len(captured_calls[1]["history"]) == 2
        assert captured_calls[1]["history"][0] == {"role": "user", "content": "Hello"}
        assert captured_calls[1]["history"][1] == {"role": "assistant", "content": "Reply"}


class TestInitCommand:
    """Test `bsage init` command."""

    def test_init_creates_vault_dirs(self, runner, tmp_path) -> None:
        with patch("bsage.cli.get_settings") as mock_settings:
            settings = MagicMock()
            settings.vault_path = tmp_path / "vault"
            mock_settings.return_value = settings
            result = runner.invoke(main, ["init"])
            assert result.exit_code == 0
            assert "Vault initialized" in result.output
            assert (tmp_path / "vault" / "seeds").is_dir()
            assert (tmp_path / "vault" / "ideas").is_dir()
            assert (tmp_path / "vault" / "actions").is_dir()


class TestSkillsCommand:
    """Test `bsage skills` command."""

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_skills_lists_all(self, mock_settings, mock_httpx, runner) -> None:
        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "name": "garden-writer",
                "category": "process",
                "is_dangerous": False,
                "description": "Write notes",
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response

        result = runner.invoke(main, ["skills"])
        assert result.exit_code == 0
        assert "garden-writer" in result.output

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_skills_empty(self, mock_settings, mock_httpx, runner) -> None:
        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response

        result = runner.invoke(main, ["skills"])
        assert result.exit_code == 0
        assert "No skills loaded" in result.output

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_skills_connection_error(self, mock_settings, mock_httpx, runner) -> None:
        import httpx

        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_httpx.get.side_effect = httpx.ConnectError("refused")
        mock_httpx.ConnectError = httpx.ConnectError

        result = runner.invoke(main, ["skills"])
        assert result.exit_code == 1
        assert "Cannot connect" in result.output


class TestRunSkillCommand:
    """Test `bsage run-skill` command."""

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_run_skill_success(self, mock_settings, mock_httpx, runner) -> None:
        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"skill": "garden-writer", "results": [{}]}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response
        mock_httpx.ConnectError = Exception
        mock_httpx.HTTPStatusError = Exception

        result = runner.invoke(main, ["run-skill", "garden-writer"])
        assert result.exit_code == 0
        assert "executed successfully" in result.output
        mock_httpx.post.assert_called_once_with(
            "http://127.0.0.1:8000/api/run/garden-writer", timeout=30.0
        )

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_run_skill_connection_error(self, mock_settings, mock_httpx, runner) -> None:
        import httpx

        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_httpx.post.side_effect = httpx.ConnectError("refused")
        mock_httpx.ConnectError = httpx.ConnectError
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError

        result = runner.invoke(main, ["run-skill", "test-skill"])
        assert result.exit_code == 1
        assert "Cannot connect" in result.output

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_run_skill_http_error(self, mock_settings, mock_httpx, runner) -> None:
        import httpx

        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        error_response = MagicMock()
        error_response.json.return_value = {"detail": "Skill not found"}
        error_response.status_code = 404

        mock_httpx.ConnectError = httpx.ConnectError
        mock_httpx.HTTPStatusError = httpx.HTTPStatusError
        mock_httpx.post.side_effect = httpx.HTTPStatusError(
            "Not Found",
            request=MagicMock(),
            response=error_response,
        )

        result = runner.invoke(main, ["run-skill", "missing-skill"])
        assert result.exit_code == 1
        assert "Skill not found" in result.output

    def test_run_skill_invalid_name(self, runner) -> None:
        result = runner.invoke(main, ["run-skill", "INVALID_NAME!"])
        assert result.exit_code != 0
        assert "Invalid skill name" in result.output


class TestHealthCommand:
    """Test `bsage health` command."""

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_health_ok(self, mock_settings, mock_httpx, runner) -> None:
        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.get.return_value = mock_response

        result = runner.invoke(main, ["health"])
        assert result.exit_code == 0
        assert "ok" in result.output

    @patch("bsage.cli.httpx")
    @patch("bsage.cli.get_settings")
    def test_health_connection_error(self, mock_settings, mock_httpx, runner) -> None:
        import httpx

        settings = MagicMock()
        settings.gateway_host = "127.0.0.1"
        settings.gateway_port = 8000
        mock_settings.return_value = settings

        mock_httpx.get.side_effect = httpx.ConnectError("refused")
        mock_httpx.ConnectError = httpx.ConnectError

        result = runner.invoke(main, ["health"])
        assert result.exit_code == 1
        assert "Cannot connect" in result.output


class TestRotateCredentialsCommand:
    """`bsage rotate-credentials` re-encrypts every stored credential under
    the current primary key. This protects against stale ciphertext after
    Audit §5 / Sprint 1 / H11 key rotation."""

    @staticmethod
    def _isolate_event_loop():
        """Yield, restoring the asyncio default loop policy on exit.

        Click's invoke triggers ``asyncio.run`` inside the CLI, which closes
        the running loop. Some sibling tests in this repo rely on the
        deprecated ``asyncio.get_event_loop()`` autocreating a loop, and the
        residual policy state from ``asyncio.run`` makes that fail. We
        explicitly reset to a fresh loop after the CLI call.
        """
        import asyncio
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            try:
                yield
            finally:
                asyncio.set_event_loop(asyncio.new_event_loop())

        return _ctx()

    @patch("bsage.cli.get_settings")
    def test_rotate_credentials_re_encrypts_all(self, mock_settings, runner, tmp_path) -> None:
        import asyncio
        import json

        from cryptography.fernet import Fernet

        from bsage.core.credential_store import CredentialStore

        old_key = Fernet.generate_key().decode("ascii")
        new_key = Fernet.generate_key().decode("ascii")
        creds_dir = tmp_path / ".credentials"

        def _run_async(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        async def _seed() -> None:
            seed = CredentialStore(creds_dir, primary_key=old_key)
            await seed.store("svc-a", {"k": "1"})
            await seed.store("svc-b", {"k": "2"})

        _run_async(_seed())

        # Sanity: stored ciphertext should not contain plaintext "k":"1".
        raw_a = (creds_dir / "svc-a.json").read_text()
        assert json.loads(raw_a)["v"] == 1

        s = MagicMock()
        s.credentials_dir = creds_dir
        s.credential_encryption_key = new_key
        s.credential_encryption_retired_keys = [old_key]
        mock_settings.return_value = s

        with self._isolate_event_loop():
            result = runner.invoke(main, ["rotate-credentials"])
        assert result.exit_code == 0, result.output
        assert "Re-encrypted 2" in result.output

        # New key alone should now decrypt both files.
        async def _verify() -> None:
            new_only = CredentialStore(creds_dir, primary_key=new_key)
            assert await new_only.get("svc-a") == {"k": "1"}
            assert await new_only.get("svc-b") == {"k": "2"}

        _run_async(_verify())

    @patch("bsage.cli.get_settings")
    def test_rotate_credentials_without_key_errors(self, mock_settings, runner, tmp_path) -> None:
        s = MagicMock()
        s.credentials_dir = tmp_path / ".credentials"
        s.credential_encryption_key = ""
        s.credential_encryption_retired_keys = []
        mock_settings.return_value = s

        with self._isolate_event_loop():
            result = runner.invoke(main, ["rotate-credentials"])
        assert result.exit_code == 1
        assert "not set" in result.output
