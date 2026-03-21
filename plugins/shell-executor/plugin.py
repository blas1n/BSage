"""Shell/Code execution Plugin — run shell commands or Python code with configurable sandboxing."""

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from bsage.plugin import plugin


def _parse_allowed_commands(commands_str: str) -> list[str]:
    """Parse comma-separated allowed commands into a list."""
    if not commands_str or not commands_str.strip():
        return []
    return [cmd.strip() for cmd in commands_str.split(",") if cmd.strip()]


def _validate_command(command: str, allowed_commands: list[str]) -> bool:
    """Check if a command is in the allowed list (or list is empty = allow all).

    Rejects commands with path traversal (e.g. ``../../bin/sh``) when a
    whitelist is active, to prevent bypass via relative paths.
    """
    if not allowed_commands:
        return True
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    cmd_path = parts[0]
    # Reject path traversal attempts like ../../bin/sh
    if ".." in cmd_path:
        return False
    base_cmd = Path(cmd_path).name if "/" in cmd_path else cmd_path
    return any(allowed.lower() == base_cmd.lower() for allowed in allowed_commands)


def _is_path_within_boundary(path: Path, boundary: Path) -> bool:
    """Check if a path (after resolving all symlinks) is within the boundary.

    Uses os.path.realpath to resolve all symlinks, then verifies the
    real path is still within the boundary.  Returns True if safe.
    """
    real = Path(os.path.realpath(path))
    real_boundary = Path(os.path.realpath(boundary))
    try:
        real.relative_to(real_boundary)
        return True
    except ValueError:
        return False


def _escape_working_dir(
    working_dir: str, sandbox_mode: str, vault_path: Path, tmp_dir: Path
) -> tuple[bool, str]:
    """
    Validate working_dir based on sandbox mode.

    Returns: (is_valid, resolved_path)
    """
    try:
        requested = Path(working_dir).resolve()

        if sandbox_mode == "vault_only":
            # Must be inside vault or tmp_dir after resolving ALL symlinks
            if _is_path_within_boundary(requested, vault_path):
                return True, str(Path(os.path.realpath(requested)))
            if _is_path_within_boundary(requested, tmp_dir):
                return True, str(Path(os.path.realpath(requested)))
            return False, f"path {requested} outside vault/tmp (sandbox_mode=vault_only)"

        # sandbox_mode == "system" — allow any path
        return True, str(requested)
    except Exception:
        return False, "path resolution error"


@plugin(
    name="shell-executor",
    version="1.0.0",
    category="process",
    description="Execute shell commands or Python code with configurable sandboxing",
    trigger={"type": "on_demand", "hint": "run command, execute code, terminal"},
    credentials=[
        {
            "name": "sandbox_mode",
            "description": (
                "Sandboxing: 'vault_only' (default, safe) or 'system' (full, needs approval)"
            ),
            "required": False,
        },
        {
            "name": "allowed_commands",
            "description": "Comma-separated whitelist of allowed commands (empty = all allowed)",
            "required": False,
        },
    ],
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute (e.g. 'ls -la', 'python script.py')",
            },
            "timeout_s": {
                "type": "number",
                "description": "Timeout in seconds (default: 30)",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command (default: tmp or current vault)",
            },
        },
        "required": ["command"],
    },
)
async def execute(context) -> dict:
    """Execute a shell command with sandboxing and return output."""
    data = context.input_data or {}
    command = data.get("command", "").strip()
    timeout_s = data.get("timeout_s", 30)
    working_dir = data.get("working_dir", "")

    if not command:
        return {"success": False, "error": "command is required"}

    # Validate timeout
    try:
        timeout_s = float(timeout_s)
        if timeout_s <= 0:
            return {"success": False, "error": "timeout_s must be positive"}
    except (ValueError, TypeError):
        return {"success": False, "error": "timeout_s must be numeric"}

    # Get sandbox settings from credentials
    creds = context.credentials or {}
    sandbox_mode = creds.get("sandbox_mode", "vault_only").lower()
    if sandbox_mode not in ("vault_only", "system"):
        sandbox_mode = "vault_only"

    # system mode requires SafeMode approval
    if sandbox_mode == "system":
        safe_mode = getattr(context.config, "safe_mode", True)
        if safe_mode:
            return {
                "success": False,
                "error": "system sandbox_mode requires SafeMode to be disabled (safe_mode=false)",
            }

    allowed_commands_str = creds.get("allowed_commands", "")
    allowed_commands = _parse_allowed_commands(allowed_commands_str)

    # Validate command against whitelist
    if not _validate_command(command, allowed_commands):
        return {
            "success": False,
            "error": f"command '{command}' not in allowed list: {allowed_commands}",
        }

    # Determine working directory
    if working_dir:
        is_valid, resolved = _escape_working_dir(
            working_dir,
            sandbox_mode,
            context.config.vault_path,
            context.config.tmp_dir,
        )
        if not is_valid:
            return {"success": False, "error": resolved}
        cwd = resolved
    else:
        # Default to tmp_dir (safe)
        cwd = str(context.config.tmp_dir)

    # Execute command
    try:
        result = await asyncio.to_thread(
            _run_subprocess,
            command,
            cwd,
            timeout_s,
        )
        success = result["returncode"] == 0

        # Write execution to action log
        await context.garden.write_action(
            "shell-executor",
            f"Executed: {command}\nReturn code: {result['returncode']}",
        )

        # Write full output to seed for later reference
        await context.garden.write_seed(
            "shell-executor",
            {
                "command": command,
                "working_dir": cwd,
                "return_code": result["returncode"],
                "stdout": result["stdout"],
                "stderr": result["stderr"],
            },
        )

        return {
            "success": success,
            "return_code": result["returncode"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
        }

    except TimeoutError:
        return {"success": False, "error": f"Command timed out after {timeout_s}s"}
    except Exception as e:
        context.logger.exception("shell_execute_error", command=command, error=str(e))
        return {"success": False, "error": f"Execution failed: {e}"}


def _run_subprocess(command: str, cwd: str, timeout_s: float) -> dict:
    """Run subprocess with shell=False (safe)."""
    try:
        try:
            args = shlex.split(command)
        except ValueError as e:
            return {"returncode": 1, "stdout": "", "stderr": f"Invalid command syntax: {e}"}

        if not args:
            return {"returncode": 1, "stdout": "", "stderr": "Empty command"}

        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,  # Always False for security
        )

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Command timed out after {timeout_s}s") from exc


@execute.setup
def setup(cred_store: Any) -> None:
    """Configure shell-executor credentials with sandboxing level and command whitelist."""
    import asyncio

    import click

    click.echo("Shell Executor Setup")
    click.echo("Choose sandboxing level:")
    click.echo("  [1] vault_only (default, safe) — restricted to vault/tmp directories")
    click.echo("  [2] system (full access, requires SafeMode approval)")

    mode_choice = click.prompt("  Sandboxing level", type=click.Choice(["1", "2"]), default="1")
    sandbox_mode = "vault_only" if mode_choice == "1" else "system"

    click.echo(f"  Selected: {sandbox_mode}")

    # Optional command whitelist
    use_whitelist = click.confirm("  Restrict to specific commands?", default=False)
    allowed_commands = ""
    if use_whitelist:
        click.echo("  (Comma-separated list, e.g. 'ls,cat,grep,python')")
        allowed_commands = click.prompt("  Allowed commands", default="")

    data = {
        "sandbox_mode": sandbox_mode,
        "allowed_commands": allowed_commands,
    }

    asyncio.run(cred_store.store("shell-executor", data))
    click.echo("  Credentials saved.")


@execute.notify
async def notify(context) -> dict:
    """Send command output back to the user's active channel."""
    data = context.input_data or {}
    stdout = data.get("stdout", "")
    stderr = data.get("stderr", "")
    output = stdout or stderr

    if not output:
        return {"sent": False, "reason": "no output to send"}

    # Truncate long output
    max_len = 4000
    if len(output) > max_len:
        output = output[: max_len - 20] + f"\n... (truncated, {len(output)} total chars)"

    rc = data.get("return_code", "?")
    message = f"Shell (rc={rc}):\n\n{output}"

    if context.notify:
        await context.notify.send(message)
        return {"sent": True, "length": len(message)}

    return {"sent": False, "reason": "no notification channel available"}
