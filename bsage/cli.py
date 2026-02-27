"""BSage CLI — client for the BSage Gateway."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
import threading
import time
from pathlib import Path

import click
import httpx
import uvicorn

from bsage.core.config import get_settings
from bsage.core.credential_store import CredentialStore
from bsage.core.plugin_loader import PluginLoader, PluginMeta
from bsage.core.skill_loader import SkillLoader, SkillMeta
from bsage.garden.vault import Vault


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
_SERVER_READY_TIMEOUT = 10


@main.command()
@click.option("--no-chat", is_flag=True, help="Start server only, no interactive REPL.")
def run(no_chat: bool) -> None:
    """Start the BSage Gateway server and enter interactive chat."""
    settings = get_settings()
    base_url = f"http://{settings.gateway_host}:{settings.gateway_port}"

    click.echo(f"Starting BSage Gateway on {settings.gateway_host}:{settings.gateway_port}")

    config = uvicorn.Config(
        "bsage.gateway.app:create_app",
        factory=True,
        host=settings.gateway_host,
        port=settings.gateway_port,
        log_level=settings.log_level,
    )
    server = uvicorn.Server(config)

    if no_chat:
        server.run()
        return

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_for_server(base_url):
        click.echo("Error: Gateway failed to start.", err=True)
        raise SystemExit(1)

    try:
        _chat_repl(base_url)
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


def _chat_repl(base_url: str) -> None:
    """Interactive chat REPL that talks to the local Gateway."""
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
            resp = httpx.post(
                f"{base_url}/api/chat",
                json={"message": user_input, "history": history},
                timeout=300.0,
            )
            resp.raise_for_status()
            answer = resp.json().get("response", "")
        except httpx.ConnectError:
            click.echo("Error: Lost connection to Gateway.", err=True)
            return
        except httpx.TimeoutException:
            click.echo("Error: Request timed out. The LLM may be slow — try again.", err=True)
            continue
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", "Unknown error")
            except Exception:
                detail = exc.response.text[:200]
            click.echo(f"Error: {detail}", err=True)
            continue
        except httpx.HTTPError as exc:
            click.echo(f"Error: {exc}", err=True)
            continue
        except Exception as exc:
            click.echo(f"Error: Unexpected error — {exc}", err=True)
            continue

        click.echo(f"BSage> {answer}\n")

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
    base_url = f"http://{host or settings.gateway_host}:{port or settings.gateway_port}"

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
    base_url = f"http://{host or settings.gateway_host}:{port or settings.gateway_port}"

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

    if meta.credentials is None:
        click.echo(f"Skill '{name}' does not declare any credentials.")
        return

    cred_store = CredentialStore(settings.credentials_dir)

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
@click.option("--host", default=None, help="Gateway host")
@click.option("--port", default=None, type=int, help="Gateway port")
def health(host: str | None, port: int | None) -> None:
    """Check Gateway health status."""
    settings = get_settings()
    base_url = f"http://{host or settings.gateway_host}:{port or settings.gateway_port}"

    try:
        response = httpx.get(f"{base_url}/api/health", timeout=5.0)
        response.raise_for_status()
    except httpx.ConnectError:
        click.echo("Error: Cannot connect to Gateway. Is it running?", err=True)
        raise SystemExit(1) from None

    data = response.json()
    click.echo(f"Gateway status: {data.get('status', 'unknown')}")
