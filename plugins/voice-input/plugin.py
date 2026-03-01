"""Voice input Plugin — transcribes audio files to text via Whisper API."""

from bsage.plugin import plugin


@plugin(
    name="voice-input",
    version="1.0.0",
    category="input",
    description="Transcribe voice recordings to text using Whisper API and store as seeds",
    trigger={"type": "webhook"},
    credentials=[
        {
            "name": "transcription_api_key",
            "description": "API key for transcription (OpenAI Whisper)",
            "required": True,
        },
        {
            "name": "audio_dir",
            "description": "Directory to scan for audio files (optional)",
            "required": False,
        },
        {
            "name": "transcription_api_base",
            "description": "Custom API base URL (optional)",
            "required": False,
        },
    ],
)
async def execute(context) -> dict:
    """Transcribe audio and write transcription to seeds."""
    import asyncio
    import base64
    from pathlib import Path

    import httpx

    creds = context.credentials
    api_key = creds.get("transcription_api_key", "")
    api_base = creds.get("transcription_api_base", "https://api.openai.com/v1")
    audio_dir = creds.get("audio_dir", "")

    audio_extensions = {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}
    transcriptions: list[dict] = []

    async def _transcribe(file_bytes: bytes, filename: str) -> str:
        url = f"{api_base}/audio/transcriptions"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, file_bytes, "application/octet-stream")},
                data={"model": "whisper-1"},
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json().get("text", "")

    # Mode 1: Webhook with base64 audio data
    input_data = context.input_data or {}
    if "audio_base64" in input_data:
        audio_bytes = base64.b64decode(input_data["audio_base64"])
        filename = input_data.get("filename", "recording.wav")
        text = await _transcribe(audio_bytes, filename)
        transcriptions.append({"filename": filename, "transcription": text})

    # Mode 2: Scan directory for audio files
    elif audio_dir:
        dir_path = Path(audio_dir)

        def _find_audio_files() -> list[Path]:
            if not dir_path.is_dir():
                return []
            return [f for f in sorted(dir_path.iterdir()) if f.suffix.lower() in audio_extensions]

        files = await asyncio.to_thread(_find_audio_files)
        for audio_file in files:
            file_bytes = await asyncio.to_thread(audio_file.read_bytes)
            text = await _transcribe(file_bytes, audio_file.name)
            transcriptions.append({"filename": audio_file.name, "transcription": text})

    if transcriptions:
        await context.garden.write_seed("voice", {"transcriptions": transcriptions})

    return {"collected": len(transcriptions)}


@execute.setup
async def setup(cred_store):
    """Configure Whisper API credentials with connectivity check."""
    import click
    import httpx

    click.echo("Voice Input (Whisper API) Setup")
    api_key = click.prompt("  Transcription API key (OpenAI)")
    api_base = click.prompt("  API base URL", default="https://api.openai.com/v1")
    audio_dir = click.prompt("  Audio directory to scan (optional)", default="")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{api_base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code != 200:
            click.echo(f"Error: API returned HTTP {resp.status_code}", err=True)
            raise SystemExit(1)
        click.echo("  API key verified.")

    data = {"transcription_api_key": api_key, "transcription_api_base": api_base}
    if audio_dir:
        data["audio_dir"] = audio_dir
    await cred_store.store("voice-input", data)
