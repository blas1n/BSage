"""Tests for the voice-input plugin."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {
        "transcription_api_key": "fake-key",
        "audio_dir": "",
        "transcription_api_base": "https://api.openai.com/v1",
    }
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    return ctx


def _load_plugin():
    """Import the plugin module and return the execute function."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("voice_input", "plugins/voice-input/plugin.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_transcribes_webhook_audio() -> None:
    execute_fn = _load_plugin()

    audio_bytes = b"fake-audio-data"
    audio_b64 = base64.b64encode(audio_bytes).decode()

    ctx = _make_context(
        input_data={"audio_base64": audio_b64, "filename": "memo.wav"},
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"text": "Hello world transcription"})

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result == {"collected": 1}
    ctx.garden.write_seed.assert_awaited_once()
    call_args = ctx.garden.write_seed.call_args
    assert call_args[0][0] == "voice"
    transcriptions = call_args[0][1]["transcriptions"]
    assert len(transcriptions) == 1
    assert transcriptions[0]["filename"] == "memo.wav"
    assert transcriptions[0]["transcription"] == "Hello world transcription"

    # Verify the API was called with the right URL
    post_call = mock_client.post.call_args
    assert "/audio/transcriptions" in post_call[0][0]


async def test_execute_scans_directory(tmp_path) -> None:
    execute_fn = _load_plugin()

    # Create dummy audio files
    (tmp_path / "recording1.wav").write_bytes(b"wav-data-1")
    (tmp_path / "recording2.mp3").write_bytes(b"mp3-data-2")
    # Non-audio file should be ignored
    (tmp_path / "notes.txt").write_text("not audio")

    ctx = _make_context(
        input_data={},  # no audio_base64
        credentials={
            "transcription_api_key": "fake-key",
            "audio_dir": str(tmp_path),
            "transcription_api_base": "https://api.openai.com/v1",
        },
    )

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"text": "Transcribed text"})

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    # 2 audio files should be transcribed (txt ignored)
    assert result == {"collected": 2}
    ctx.garden.write_seed.assert_awaited_once()
    transcriptions = ctx.garden.write_seed.call_args[0][1]["transcriptions"]
    assert len(transcriptions) == 2
    filenames = {t["filename"] for t in transcriptions}
    assert "recording1.wav" in filenames
    assert "recording2.mp3" in filenames
    # The API should have been called twice (once per audio file)
    assert mock_client.post.await_count == 2


async def test_execute_no_input() -> None:
    execute_fn = _load_plugin()

    ctx = _make_context(
        input_data=None,
        credentials={
            "transcription_api_key": "fake-key",
            "audio_dir": "",
            "transcription_api_base": "https://api.openai.com/v1",
        },
    )

    result = await execute_fn(ctx)

    assert result == {"collected": 0}
    # write_seed should NOT be called when there are no transcriptions
    ctx.garden.write_seed.assert_not_awaited()
