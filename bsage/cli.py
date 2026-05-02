"""BSage CLI — client for the BSage Gateway."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bsage.core.chat_bridge import ChatBridge

import click
import httpx
import uvicorn

from bsage.core.config import get_settings
from bsage.core.credential_store import CredentialStore
from bsage.core.plugin_loader import PluginLoader, PluginMeta
from bsage.core.skill_loader import SkillLoader, SkillMeta
from bsage.garden.vault import Vault


def _connect_host(host: str) -> str:
    """Convert a listen address to a connect address (0.0.0.0 → 127.0.0.1)."""
    return "127.0.0.1" if host == "0.0.0.0" else host


def _validate_skill_name(name: str) -> str:
    """Validate a skill name matches the required pattern."""
    if not re.match(r"^[a-z][a-z0-9-]*$", name):
        msg = f"Invalid skill name: {name}. Use lowercase alphanumeric with hyphens."
        raise click.BadParameter(msg)
    return name


@click.group()
def main() -> None:
    """BSage — Personal AI Agent for your 2nd Brain."""


_SERVER_READY_POLL_INTERVAL = 0.2
_SERVER_READY_TIMEOUT = 30


@main.command()
@click.option("--no-chat", is_flag=True, help="Start server only, no interactive REPL.")
def run(no_chat: bool) -> None:
    """Start the BSage Gateway server and enter interactive chat."""
    settings = get_settings()
    base_url = f"http://{_connect_host(settings.gateway_host)}:{settings.gateway_port}"

    click.echo(f"Starting BSage Gateway on {settings.gateway_host}:{settings.gateway_port}")

    from bsage.core.chat_bridge import ChatBridge
    from bsage.gateway.app import create_app

    app = create_app(settings)

    config = uvicorn.Config(
        app,
        host=settings.gateway_host,
        port=settings.gateway_port,
        log_level=settings.log_level,
    )
    server = uvicorn.Server(config)

    if no_chat:
        server.run()
        return

    server_loop: asyncio.AbstractEventLoop | None = None

    def _run_server() -> None:
        nonlocal server_loop
        server_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(server_loop)
        server_loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_run_server, daemon=True)
    thread.start()

    if not _wait_for_server(base_url):
        click.echo("Error: Gateway failed to start.", err=True)
        raise SystemExit(1)

    # Access AppState from the app instance (lifespan completed by now)
    assert server_loop is not None
    app_state = app.state.bsage
    if app_state is None or app_state.chat_bridge is None:
        click.echo("Error: Gateway initialized but ChatBridge unavailable.", err=True)
        raise SystemExit(1)

    async def _cli_reply(msg: str) -> None:
        click.echo(f"BSage> {msg}\n")

    cli_chat_bridge = ChatBridge(
        agent_loop=app_state.agent_loop,
        garden_writer=app_state.garden_writer,
        prompt_registry=app_state.prompt_registry,
        retriever=app_state.retriever,
        reply_fn=_cli_reply,
    )

    try:
        _chat_repl(cli_chat_bridge, server_loop)
    except KeyboardInterrupt:
        click.echo("\nGoodbye!")
    finally:
        server.should_exit = True
        thread.join(timeout=3)


def _wait_for_server(base_url: str) -> bool:
    """Poll health endpoint until the server is ready."""
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if resp.status_code == 200:  # noqa: PLR2004
                return True
        except httpx.ConnectError:
            pass
        time.sleep(_SERVER_READY_POLL_INTERVAL)
    return False


def _chat_repl(
    chat_bridge: ChatBridge,
    server_loop: asyncio.AbstractEventLoop,
) -> None:
    """Interactive chat REPL using ChatBridge directly."""
    click.echo("BSage Chat — Type /quit to exit.\n")
    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye!")
            return

        if user_input.strip().lower() == "/quit":
            click.echo("Goodbye!")
            return

        if not user_input.strip():
            continue

        try:
            future = asyncio.run_coroutine_threadsafe(
                chat_bridge.chat(message=user_input, history=history),
                server_loop,
            )
            answer = future.result(timeout=300.0)
        except TimeoutError:
            click.echo("Error: Request timed out. The LLM may be slow — try again.", err=True)
            continue
        except Exception as exc:
            click.echo(f"Error: {exc}", err=True)
            continue

        # reply_fn already printed the response via click.echo
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": answer})


@main.command()
def init() -> None:
    """Initialize the Vault directory structure."""
    settings = get_settings()
    vault = Vault(settings.vault_path)
    vault.ensure_dirs()
    click.echo(f"Vault initialized at {settings.vault_path}")


@main.command()
@click.option("--host", default=None, help="Gateway host")
@click.option("--port", default=None, type=int, help="Gateway port")
def skills(host: str | None, port: int | None) -> None:
    """List all loaded skills from the Gateway."""
    settings = get_settings()
    h = _connect_host(host or settings.gateway_host)
    base_url = f"http://{h}:{port or settings.gateway_port}"

    try:
        response = httpx.get(f"{base_url}/api/skills", timeout=5.0)
        response.raise_for_status()
    except httpx.ConnectError:
        click.echo("Error: Cannot connect to Gateway. Is it running?", err=True)
        raise SystemExit(1) from None

    data = response.json()
    if not data:
        click.echo("No skills loaded.")
        return

    click.echo(f"{'Name':<25} {'Category':<12} {'Dangerous':<10} Description")
    click.echo("-" * 80)
    for skill in data:
        danger = "YES" if skill["is_dangerous"] else "no"
        desc = skill["description"]
        click.echo(f"{skill['name']:<25} {skill['category']:<12} {danger:<10} {desc}")


@main.command("run-skill")
@click.argument("name")
@click.option("--host", default=None, help="Gateway host")
@click.option("--port", default=None, type=int, help="Gateway port")
def run_skill(name: str, host: str | None, port: int | None) -> None:
    """Run a specific skill by name."""
    _validate_skill_name(name)
    settings = get_settings()
    h = _connect_host(host or settings.gateway_host)
    base_url = f"http://{h}:{port or settings.gateway_port}"

    try:
        response = httpx.post(f"{base_url}/api/run/{name}", timeout=30.0)
        response.raise_for_status()
    except httpx.ConnectError:
        click.echo("Error: Cannot connect to Gateway. Is it running?", err=True)
        raise SystemExit(1) from None
    except httpx.HTTPStatusError as exc:
        click.echo(f"Error: {exc.response.json().get('detail', 'Unknown error')}", err=True)
        raise SystemExit(1) from None

    data = response.json()
    click.echo(f"Skill '{name}' executed successfully.")
    click.echo(f"Results: {data.get('results', [])}")


@main.command()
@click.argument("name")
def setup(name: str) -> None:
    """Set up credentials for a skill."""
    _validate_skill_name(name)
    settings = get_settings()

    # Try Skills first, then Plugins
    skill_loader = SkillLoader(settings.skills_dir)
    registry: dict[str, SkillMeta | PluginMeta] = dict(asyncio.run(skill_loader.load_all()))

    if name not in registry:
        plugin_loader = PluginLoader(settings.plugins_dir, danger_analyzer=None)
        plugin_registry = asyncio.run(plugin_loader.load_all())
        registry.update(plugin_registry)

    meta = registry.get(name)
    if meta is None:
        click.echo(
            f"Error: '{name}' not found in {settings.skills_dir} or {settings.plugins_dir}",
            err=True,
        )
        raise SystemExit(1)

    cred_store = CredentialStore(
        settings.credentials_dir,
        primary_key=settings.credential_encryption_key or None,
        retired_keys=settings.credential_encryption_retired_keys,
    )

    # Plugin with @execute.setup decorator — run the custom setup function
    if isinstance(meta, PluginMeta) and meta._setup_fn is not None:
        click.echo(f"[BSage] Running custom setup for plugin '{name}'")
        if inspect.iscoroutinefunction(meta._setup_fn):
            asyncio.run(meta._setup_fn(cred_store))
        else:
            meta._setup_fn(cred_store)
        click.echo(f"[BSage] Setup complete for '{name}'.")
        return

    if meta.credentials is None:
        click.echo(f"'{name}' does not declare any credentials.")
        return

    # PluginMeta.credentials is list[dict] (the fields list directly).
    # SkillMeta.credentials is dict with optional "setup_entrypoint" and "fields" keys.
    if isinstance(meta.credentials, list):
        fields = meta.credentials
    else:
        # Custom setup entrypoint
        setup_ep = meta.credentials.get("setup_entrypoint")
        if setup_ep:
            _run_credential_setup(settings.skills_dir, name, setup_ep, cred_store)
            return

        fields = meta.credentials.get("fields", [])
    if not fields:
        click.echo(f"Skill '{name}' has no credential fields defined.")
        return

    click.echo(f"[BSage] Setting up credentials for '{name}'")
    data: dict = {}
    for field_def in fields:
        field_name = field_def.get("name", "")
        desc = field_def.get("description", field_name)
        required = field_def.get("required", True)

        if required:
            value = click.prompt(f"  {field_name} ({desc})")
        else:
            value = click.prompt(f"  {field_name} ({desc}) [optional]", default="")

        if value:
            data[field_name] = value

    asyncio.run(cred_store.store(name, data))
    click.echo(f"[BSage] Credentials saved for '{name}'.")


def _run_credential_setup(
    skills_dir: Path, skill_name: str, setup_ep: str, cred_store: CredentialStore
) -> None:
    """Run a custom setup entrypoint for credential configuration."""
    parts = setup_ep.split("::")
    if len(parts) != 2:  # noqa: PLR2004
        click.echo(f"Error: Invalid setup_entrypoint format '{setup_ep}'", err=True)
        raise SystemExit(1)

    module_file, func_name = parts
    module_path = skills_dir / skill_name / module_file

    if not module_path.resolve().is_relative_to(skills_dir.resolve()):
        click.echo(f"Error: Path traversal detected in setup_entrypoint '{setup_ep}'", err=True)
        raise SystemExit(1)

    if not module_path.exists():
        click.echo(f"Error: Setup module not found: {module_path}", err=True)
        raise SystemExit(1)

    spec = importlib.util.spec_from_file_location("setup_module", module_path)
    if spec is None or spec.loader is None:
        click.echo(f"Error: Cannot load setup module: {module_path}", err=True)
        raise SystemExit(1)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    func = getattr(module, func_name, None)
    if func is None:
        click.echo(f"Error: Function '{func_name}' not found in {module_path}", err=True)
        raise SystemExit(1)

    if inspect.iscoroutinefunction(func):
        asyncio.run(func(cred_store))
    else:
        func(cred_store)


@main.command()
@click.argument("name")
def install(name: str) -> None:
    """Install dependencies for a plugin from its requirements.txt."""
    _validate_skill_name(name)
    settings = get_settings()
    plugin_dir = settings.plugins_dir / name
    if not plugin_dir.is_dir():
        click.echo(f"Error: Plugin directory not found: {plugin_dir}", err=True)
        raise SystemExit(1)

    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        click.echo(f"Plugin '{name}' has no requirements.txt — no dependencies to install.")
        return

    click.echo(f"Installing dependencies for '{name}' from {req_file}")
    result = subprocess.run(
        ["uv", "pip", "install", "-r", str(req_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        click.echo(f"Dependencies installed for '{name}'.")
    else:
        click.echo(f"Error installing dependencies:\n{result.stderr}", err=True)
        raise SystemExit(1)


@main.command("rotate-credentials")
def rotate_credentials() -> None:
    """Re-encrypt all stored credentials with the current primary key.

    Run after rotating CREDENTIAL_ENCRYPTION_KEY. The previous key must
    still be present in CREDENTIAL_ENCRYPTION_RETIRED_KEYS so existing
    ciphertexts can be read; once rotation completes you may remove it.
    """
    settings = get_settings()
    if not settings.credential_encryption_key:
        click.echo(
            "Error: CREDENTIAL_ENCRYPTION_KEY is not set; nothing to rotate.",
            err=True,
        )
        raise SystemExit(1)
    store = CredentialStore(
        settings.credentials_dir,
        primary_key=settings.credential_encryption_key,
        retired_keys=settings.credential_encryption_retired_keys,
    )
    count = asyncio.run(store.rotate_keys())
    click.echo(f"[BSage] Re-encrypted {count} credential(s) with the current primary key.")


@main.command()
def reindex() -> None:
    """Rebuild the _index/ files for the vault."""
    settings = get_settings()

    from bsage.garden.file_index_reader import FileIndexReader
    from bsage.garden.retriever import VaultRetriever

    vault = Vault(settings.vault_path)
    index_reader = FileIndexReader(vault=vault)
    retriever = VaultRetriever(vault=vault, index_reader=index_reader)

    async def _run() -> int:
        return await retriever.reindex_all()

    click.echo(f"Reindexing vault at {settings.vault_path}")
    count = asyncio.run(_run())
    click.echo(f"  Done. {count} notes indexed.")


@main.command()
@click.option("--host", default=None, help="Gateway host")
@click.option("--port", default=None, type=int, help="Gateway port")
def health(host: str | None, port: int | None) -> None:
    """Check Gateway health status."""
    settings = get_settings()
    h = _connect_host(host or settings.gateway_host)
    base_url = f"http://{h}:{port or settings.gateway_port}"

    try:
        response = httpx.get(f"{base_url}/api/health", timeout=5.0)
        response.raise_for_status()
    except httpx.ConnectError:
        click.echo("Error: Cannot connect to Gateway. Is it running?", err=True)
        raise SystemExit(1) from None

    data = response.json()
    click.echo(f"Gateway status: {data.get('status', 'unknown')}")
