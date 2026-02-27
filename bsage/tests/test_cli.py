"""Tests for bsage.cli — Click CLI commands."""

from unittest.mock import MagicMock, patch

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

    @patch("bsage.cli.uvicorn")
    @patch("bsage.cli.get_settings")
    def test_run_no_chat_starts_server_blocking(self, mock_settings, mock_uvicorn, runner) -> None:
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
        mock_uvicorn.Server.return_value = mock_server
        mock_uvicorn.Config.return_value = MagicMock()

        result = runner.invoke(main, ["run"])
        assert result.exit_code == 0
        mock_wait.assert_called_once()
        mock_repl.assert_called_once()
        assert mock_server.should_exit is True

    @patch("bsage.cli._wait_for_server", return_value=False)
    @patch("bsage.cli.uvicorn")
    @patch("bsage.cli.get_settings")
    def test_run_exits_if_server_fails(
        self, mock_settings, mock_uvicorn, mock_wait, runner
    ) -> None:
        mock_settings.return_value = _mock_settings()
        mock_server = MagicMock()
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

    @patch("bsage.cli.time.monotonic", side_effect=[0, 0.5, 1.0, 11.0])
    @patch("bsage.cli.time.sleep")
    @patch("bsage.cli.httpx.get", side_effect=httpx.ConnectError("refused"))
    def test_returns_false_on_timeout(self, mock_get, mock_sleep, mock_time) -> None:
        assert _wait_for_server("http://localhost:8000") is False


class TestChatRepl:
    """Test _chat_repl interactive loop."""

    @patch("bsage.cli.httpx.post")
    @patch("bsage.cli.click.prompt", side_effect=["Hello", "/quit"])
    def test_send_and_quit(self, mock_prompt, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hi there!"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        _chat_repl("http://localhost:8000")

        mock_post.assert_called_once()
        call_json = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json"))
        assert call_json["message"] == "Hello"

    @patch("bsage.cli.click.prompt", side_effect=["/quit"])
    def test_quit_immediately(self, mock_prompt) -> None:
        _chat_repl("http://localhost:8000")
        # Should exit without posting

    @patch("bsage.cli.click.prompt", side_effect=EOFError)
    def test_eof_exits_gracefully(self, mock_prompt) -> None:
        _chat_repl("http://localhost:8000")

    @patch("bsage.cli.httpx.post", side_effect=httpx.ConnectError("lost"))
    @patch("bsage.cli.click.prompt", side_effect=["Hello"])
    def test_connection_lost_exits(self, mock_prompt, mock_post) -> None:
        _chat_repl("http://localhost:8000")

    @patch("bsage.cli.httpx.post")
    @patch("bsage.cli.click.prompt", side_effect=["Hello", "World", "/quit"])
    def test_history_accumulates(self, mock_prompt, mock_post) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Reply"}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        _chat_repl("http://localhost:8000")

        # Two messages sent before /quit
        assert mock_post.call_count == 2
        # Messages are sent with correct content
        first_msg = mock_post.call_args_list[0].kwargs["json"]["message"]
        second_msg = mock_post.call_args_list[1].kwargs["json"]["message"]
        assert first_msg == "Hello"
        assert second_msg == "World"


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
            assert (tmp_path / "vault" / "garden").is_dir()
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
