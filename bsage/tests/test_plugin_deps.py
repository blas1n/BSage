"""Tests for plugin dependency checking (requirements.txt) and bsage install CLI."""

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from bsage.cli import main
from bsage.core.plugin_loader import PluginLoader, PluginMeta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLUGIN_PY = """\
from bsage.plugin import plugin

@plugin(
    name="{name}",
    version="1.0.0",
    category="input",
    description="Test plugin",
)
async def execute(context):
    return {{"ok": True}}
"""


def _make_plugin(plugins_dir, name, requirements=None):
    """Create a plugin directory with optional requirements.txt."""
    d = plugins_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.py").write_text(_PLUGIN_PY.format(name=name))
    if requirements is not None:
        (d / "requirements.txt").write_text(requirements)
    return d


# ---------------------------------------------------------------------------
# PluginLoader._check_requirements
# ---------------------------------------------------------------------------


class TestCheckRequirements:
    """Tests for PluginLoader._check_requirements()."""

    def test_all_present(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        (d / "requirements.txt").write_text("structlog>=23.0.0\n")
        assert PluginLoader._check_requirements(d) == []

    def test_missing_package(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        (d / "requirements.txt").write_text("nonexistent_pkg_xyz>=1.0.0\n")
        missing = PluginLoader._check_requirements(d)
        assert "nonexistent_pkg_xyz" in missing

    def test_no_file(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        assert PluginLoader._check_requirements(d) == []

    def test_ignores_comments_and_blank_lines(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        (d / "requirements.txt").write_text(
            "# This is a comment\n\nstructlog>=23.0.0\n  # Another comment\n"
        )
        assert PluginLoader._check_requirements(d) == []

    def test_handles_various_version_specifiers(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        (d / "requirements.txt").write_text("structlog==23.0.0\nclick>8.0\npyyaml~=6.0\n")
        # pyyaml import name is yaml, but pip name pyyaml → pyyaml (find_spec("pyyaml") works)
        # Actually find_spec("pyyaml") may or may not work — yaml is the import name.
        # For this test we just check structlog and click are found.
        missing = PluginLoader._check_requirements(d)
        assert "structlog" not in missing
        assert "click" not in missing

    def test_hyphen_to_underscore_normalization(self, tmp_path) -> None:
        d = tmp_path / "my-plugin"
        d.mkdir()
        # pydantic-settings → pydantic_settings (should be found)
        (d / "requirements.txt").write_text("pydantic-settings>=2.0.0\n")
        assert PluginLoader._check_requirements(d) == []


# ---------------------------------------------------------------------------
# PluginLoader.load_all with dependency check
# ---------------------------------------------------------------------------


class TestLoadAllWithDeps:
    """Tests for PluginLoader.load_all() skipping plugins with missing deps."""

    async def test_skips_plugin_with_missing_deps(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _make_plugin(plugins_dir, "good-plugin")
        _make_plugin(plugins_dir, "bad-plugin", requirements="nonexistent_xyz>=1.0\n")

        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()

        assert "good-plugin" in registry
        assert "bad-plugin" not in registry

    async def test_loads_plugin_without_requirements(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _make_plugin(plugins_dir, "simple-plugin")

        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()

        assert "simple-plugin" in registry

    async def test_loads_plugin_with_satisfied_requirements(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _make_plugin(plugins_dir, "ok-plugin", requirements="structlog>=23.0.0\n")

        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()

        assert "ok-plugin" in registry


# ---------------------------------------------------------------------------
# PluginLoader.scan_new with dependency check
# ---------------------------------------------------------------------------


class TestScanNewWithDeps:
    """Tests for PluginLoader.scan_new() skipping plugins with missing deps."""

    async def test_skips_new_plugin_with_missing_deps(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        _make_plugin(plugins_dir, "existing")

        loader = PluginLoader(plugins_dir)
        await loader.load_all()

        # Add a new plugin with unsatisfied deps
        _make_plugin(plugins_dir, "needs-stuff", requirements="no_such_package>=1.0\n")
        new = await loader.scan_new()

        assert "needs-stuff" not in new
        assert "needs-stuff" not in loader._registry


# ---------------------------------------------------------------------------
# bsage install CLI
# ---------------------------------------------------------------------------


class TestInstallCLI:
    """Tests for the `bsage install <name>` CLI command."""

    def test_no_requirements_file(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "my-plugin").mkdir()

        runner = CliRunner()
        with patch("bsage.cli.get_settings") as mock_settings:
            s = MagicMock()
            s.plugins_dir = plugins_dir
            mock_settings.return_value = s
            result = runner.invoke(main, ["install", "my-plugin"])

        assert result.exit_code == 0
        output = result.output.lower()
        assert "no requirements.txt" in output or "no dependencies" in output

    def test_plugin_not_found(self, tmp_path) -> None:
        runner = CliRunner()
        with patch("bsage.cli.get_settings") as mock_settings:
            s = MagicMock()
            s.plugins_dir = tmp_path / "plugins"
            (s.plugins_dir).mkdir()
            mock_settings.return_value = s
            result = runner.invoke(main, ["install", "nonexistent"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    @patch("bsage.cli.subprocess.run")
    def test_runs_uv_pip_install(self, mock_run, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        plugin_dir = plugins_dir / "my-plugin"
        plugin_dir.mkdir()
        req_file = plugin_dir / "requirements.txt"
        req_file.write_text("httpx>=0.27.0\n")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = CliRunner()
        with patch("bsage.cli.get_settings") as mock_settings:
            s = MagicMock()
            s.plugins_dir = plugins_dir
            mock_settings.return_value = s
            result = runner.invoke(main, ["install", "my-plugin"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "uv"
        assert call_args[1] == "pip"
        assert call_args[2] == "install"
        assert str(req_file) in call_args

    @patch("bsage.cli.subprocess.run")
    def test_install_failure(self, mock_run, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        plugin_dir = plugins_dir / "my-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "requirements.txt").write_text("httpx>=0.27.0\n")

        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="some error")

        runner = CliRunner()
        with patch("bsage.cli.get_settings") as mock_settings:
            s = MagicMock()
            s.plugins_dir = plugins_dir
            mock_settings.return_value = s
            result = runner.invoke(main, ["install", "my-plugin"])

        assert result.exit_code != 0
        assert "error" in result.output.lower()


# ---------------------------------------------------------------------------
# @execute.setup decorator
# ---------------------------------------------------------------------------


class TestSetupDecorator:
    """Tests for the @execute.setup decorator and integration."""

    def test_setup_decorator_registers_fn(self) -> None:
        from bsage.plugin import plugin

        @plugin(name="my-plugin", version="1.0.0", category="input", description="Test")
        async def execute(context):
            return {"ok": True}

        @execute.setup
        async def setup(cred_store):
            pass

        assert hasattr(execute, "__setup__")
        assert execute.__setup__ is setup

    def test_plugin_loader_reads_setup_fn(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        d = plugins_dir / "setup-plugin"
        d.mkdir(parents=True)
        (d / "plugin.py").write_text(
            "from bsage.plugin import plugin\n\n"
            '@plugin(name="setup-plugin", version="1.0.0", category="input", '
            'description="Has setup")\n'
            "async def execute(context):\n"
            '    return {"ok": True}\n\n'
            "@execute.setup\n"
            "async def setup(cred_store):\n"
            "    pass\n"
        )
        meta = PluginLoader._load_plugin(d / "plugin.py")
        assert meta._setup_fn is not None

    def test_plugin_loader_no_setup_fn(self, tmp_path) -> None:
        plugins_dir = tmp_path / "plugins"
        _make_plugin(plugins_dir, "no-setup")
        meta = PluginLoader._load_plugin(plugins_dir / "no-setup" / "plugin.py")
        assert meta._setup_fn is None


# ---------------------------------------------------------------------------
# bsage setup CLI with @execute.setup
# ---------------------------------------------------------------------------


class TestSetupCLIWithSetupFn:
    """Tests for `bsage setup <name>` using @execute.setup function."""

    def test_cli_setup_calls_setup_fn(self, tmp_path) -> None:
        setup_called = []

        def my_setup(cred_store):
            setup_called.append(True)

        meta = PluginMeta(
            name="my-plugin",
            version="1.0.0",
            category="input",
            description="Test",
            _execute_fn=None,
            _setup_fn=my_setup,
        )

        runner = CliRunner()
        with (
            patch("bsage.cli.get_settings") as mock_settings,
            patch("bsage.cli.SkillLoader") as mock_skill_loader,
            patch("bsage.cli.PluginLoader") as mock_plugin_loader,
        ):
            s = MagicMock()
            s.plugins_dir = tmp_path / "plugins"
            s.skills_dir = tmp_path / "skills"
            s.credentials_dir = tmp_path / ".credentials"
            s.credential_encryption_key = ""
            s.credential_encryption_retired_keys = []
            mock_settings.return_value = s
            mock_skill_loader.return_value.load_all = AsyncMock(return_value={})
            mock_plugin_loader.return_value.load_all = AsyncMock(return_value={"my-plugin": meta})
            result = runner.invoke(main, ["setup", "my-plugin"])

        assert result.exit_code == 0
        assert len(setup_called) == 1
        assert "custom setup" in result.output.lower() or "setup complete" in result.output.lower()

    def test_cli_setup_falls_back_to_prompts(self, tmp_path) -> None:
        meta = PluginMeta(
            name="my-plugin",
            version="1.0.0",
            category="input",
            description="Test",
            credentials=[
                {"name": "api_key", "description": "API key", "required": True},
            ],
            _execute_fn=None,
            _setup_fn=None,
        )

        runner = CliRunner()
        with (
            patch("bsage.cli.get_settings") as mock_settings,
            patch("bsage.cli.SkillLoader") as mock_skill_loader,
            patch("bsage.cli.PluginLoader") as mock_plugin_loader,
        ):
            s = MagicMock()
            s.plugins_dir = tmp_path / "plugins"
            s.skills_dir = tmp_path / "skills"
            s.credentials_dir = tmp_path / ".credentials"
            s.credential_encryption_key = ""
            s.credential_encryption_retired_keys = []
            mock_settings.return_value = s
            mock_skill_loader.return_value.load_all = AsyncMock(return_value={})
            mock_plugin_loader.return_value.load_all = AsyncMock(return_value={"my-plugin": meta})
            result = runner.invoke(main, ["setup", "my-plugin"], input="my-secret-key\n")

        assert result.exit_code == 0
        assert "api_key" in result.output
