"""Tests for bsage.core.plugin_loader — Python plugin scanning and PluginMeta registry."""

import pytest

from bsage.core.exceptions import PluginLoadError
from bsage.core.plugin_loader import PluginLoader, PluginMeta


class TestPluginMeta:
    """Test PluginMeta dataclass."""

    def test_required_fields(self) -> None:
        meta = PluginMeta(
            name="test-plugin",
            version="1.0.0",
            category="input",
            description="A test plugin",
        )
        assert meta.name == "test-plugin"
        assert meta.version == "1.0.0"
        assert meta.category == "input"
        assert meta.description == "A test plugin"

    def test_optional_fields_defaults(self) -> None:
        meta = PluginMeta(
            name="test",
            version="1.0.0",
            category="input",
            description="Test",
        )
        assert meta.author == ""
        assert meta.trigger is None
        assert meta.credentials is None
        assert meta.input_schema is None
        assert meta.mcp_exposed is False
        assert meta._execute_fn is None
        assert meta._notify_fn is None

    def test_mcp_exposed_can_be_set(self) -> None:
        meta = PluginMeta(
            name="test",
            version="1.0.0",
            category="input",
            description="Test",
            mcp_exposed=True,
        )
        assert meta.mcp_exposed is True

    def test_execute_fn_not_shown_in_repr(self) -> None:
        async def my_fn(ctx):
            return {}

        meta = PluginMeta(
            name="test",
            version="1.0.0",
            category="input",
            description="Test",
        )
        meta._execute_fn = my_fn
        repr_str = repr(meta)
        assert "_execute_fn" not in repr_str


class TestPluginLoader:
    """Test PluginLoader scanning and registry."""

    @pytest.fixture()
    def plugins_dir(self, tmp_path):
        """Create a temporary plugins directory with a sample plugin.py."""
        plugin_dir = tmp_path / "telegram-input"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(
            "from bsage.plugin import plugin\n"
            "\n"
            "@plugin(\n"
            "    name='telegram-input',\n"
            "    version='1.0.0',\n"
            "    category='input',\n"
            ""
            "    description='Telegram bot input',\n"
            "    trigger={'type': 'webhook'},\n"
            ")\n"
            "async def execute(context):\n"
            "    return {'collected': 0}\n"
        )
        return tmp_path

    async def test_load_all_discovers_plugin(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()
        assert "telegram-input" in registry

    async def test_load_all_returns_plugin_meta(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()
        meta = registry["telegram-input"]
        assert isinstance(meta, PluginMeta)
        assert meta.category == "input"
        assert meta.trigger == {"type": "webhook"}

    async def test_load_all_stores_execute_fn(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()
        meta = registry["telegram-input"]
        assert meta._execute_fn is not None
        assert callable(meta._execute_fn)

    async def test_load_all_stores_notify_fn_when_present(self, tmp_path) -> None:
        plugin_dir = tmp_path / "with-notify"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(
            "from bsage.plugin import plugin\n"
            "\n"
            "@plugin(\n"
            "    name='with-notify',\n"
            "    version='1.0.0',\n"
            "    category='input',\n"
            ""
            "    description='Plugin with notify',\n"
            ")\n"
            "async def execute(context):\n"
            "    return {}\n"
            "\n"
            "@execute.notify\n"
            "async def notify(context):\n"
            "    return {'sent': True}\n"
        )
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        meta = registry["with-notify"]
        assert meta._notify_fn is not None
        assert callable(meta._notify_fn)

    async def test_load_all_notify_fn_none_when_absent(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        registry = await loader.load_all()
        meta = registry["telegram-input"]
        assert meta._notify_fn is None

    async def test_load_all_skips_missing_plugin_py(self, tmp_path) -> None:
        plugin_dir = tmp_path / "empty-plugin"
        plugin_dir.mkdir()
        # No plugin.py inside
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert "empty-plugin" not in registry

    async def test_load_all_skips_non_directories(self, tmp_path) -> None:
        (tmp_path / "not-a-dir.txt").write_text("hello")
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert len(registry) == 0

    async def test_load_all_handles_syntax_error_in_plugin(self, tmp_path) -> None:
        plugin_dir = tmp_path / "broken-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("def execute(:\n    pass\n")  # syntax error
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert "broken-plugin" not in registry

    async def test_load_all_handles_missing_plugin_decorator(self, tmp_path) -> None:
        plugin_dir = tmp_path / "no-decorator"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text("async def execute(context):\n    return {}\n")
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert "no-decorator" not in registry

    async def test_load_all_nonexistent_dir(self, tmp_path) -> None:
        loader = PluginLoader(tmp_path / "does-not-exist")
        registry = await loader.load_all()
        assert len(registry) == 0

    async def test_get_returns_plugin(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        await loader.load_all()
        meta = loader.get("telegram-input")
        assert meta.name == "telegram-input"

    async def test_get_raises_on_unknown_plugin(self, plugins_dir) -> None:
        loader = PluginLoader(plugins_dir)
        await loader.load_all()
        with pytest.raises(PluginLoadError, match="not found"):
            loader.get("nonexistent")

    async def test_load_all_rejects_invalid_category(self, tmp_path) -> None:
        plugin_dir = tmp_path / "bad-category"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(
            "from bsage.plugin import plugin\n"
            "\n"
            "@plugin(\n"
            "    name='bad-category',\n"
            "    version='1.0.0',\n"
            "    category='invalid',\n"
            ""
            "    description='Bad category',\n"
            ")\n"
            "async def execute(context):\n"
            "    return {}\n"
        )
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert "bad-category" not in registry

    async def test_load_all_minimal_declaration(self, tmp_path) -> None:
        """Plugin can be declared with only name and category."""
        plugin_dir = tmp_path / "minimal"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(
            "from bsage.plugin import plugin\n"
            "\n"
            "@plugin(name='minimal', category='process')\n"
            "async def execute(context):\n"
            "    return {}\n"
        )
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        meta = registry["minimal"]
        assert meta.version == "0.1.0"
        assert meta.description == ""

    async def test_load_all_description_falls_back_to_docstring(self, tmp_path) -> None:
        """Falls back to function docstring when description is omitted."""
        plugin_dir = tmp_path / "doc-plugin"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.py").write_text(
            "from bsage.plugin import plugin\n"
            "\n"
            "@plugin(name='doc-plugin', category='input')\n"
            "async def execute(context):\n"
            '    """My docstring description."""\n'
            "    return {}\n"
        )
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert registry["doc-plugin"].description == "My docstring description."

    async def test_load_all_multiple_plugins(self, tmp_path) -> None:
        for name in ["plugin-a", "plugin-b"]:
            d = tmp_path / name
            d.mkdir()
            (d / "plugin.py").write_text(
                f"from bsage.plugin import plugin\n"
                f"\n"
                f"@plugin(\n"
                f"    name='{name}',\n"
                f"    version='1.0.0',\n"
                f"    category='input',\n"
                ""
                f"    description='{name}',\n"
                f")\n"
                f"async def execute(context):\n"
                f"    return {{}}\n"
            )
        loader = PluginLoader(tmp_path)
        registry = await loader.load_all()
        assert "plugin-a" in registry
        assert "plugin-b" in registry
        assert len(registry) == 2
