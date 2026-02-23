"""Tests for bsage.core.prompt_registry — YAML prompt template management."""

import pytest

from bsage.core.prompt_registry import PromptRegistry


@pytest.fixture()
def prompts_dir(tmp_path):
    """Create a prompts directory with test YAML files."""
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "system.yaml").write_text("template: |\n  You are BSage.\n")
    (d / "chat.yaml").write_text("template: |\n  Chat context: {context_section}\n")
    (d / "skill.yaml").write_text("template: |\n  Executing '{skill_name}': {description}\n")
    (d / "router.yaml").write_text("template: |\n  Route skills: {skill_descriptions}\n")
    return d


class TestPromptRegistryLoad:
    """Test loading YAML prompt files."""

    def test_loads_all_templates(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        assert sorted(registry.list_names()) == ["chat", "router", "skill", "system"]

    def test_missing_dir_loads_empty(self, tmp_path) -> None:
        registry = PromptRegistry(tmp_path / "nonexistent")
        assert registry.list_names() == []

    def test_skips_invalid_yaml(self, tmp_path) -> None:
        d = tmp_path / "prompts"
        d.mkdir()
        (d / "good.yaml").write_text("template: |\n  Good template\n")
        (d / "bad.yaml").write_text("not_template: foo\n")
        registry = PromptRegistry(d)
        assert registry.list_names() == ["good"]

    def test_skips_malformed_yaml(self, tmp_path) -> None:
        d = tmp_path / "prompts"
        d.mkdir()
        (d / "broken.yaml").write_text("{{{{invalid yaml")
        registry = PromptRegistry(d)
        assert registry.list_names() == []

    def test_strips_trailing_newline(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        template = registry.get("system")
        assert not template.endswith("\n")


class TestPromptRegistryGet:
    """Test getting raw templates."""

    def test_get_returns_template(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        assert "BSage" in registry.get("system")

    def test_get_missing_raises_key_error(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get("nonexistent")


class TestPromptRegistryRender:
    """Test rendering templates with variables."""

    def test_render_chat(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        result = registry.render("chat", context_section="My notes here")
        assert "My notes here" in result

    def test_render_skill(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        result = registry.render("skill", skill_name="garden-writer", description="Write notes")
        assert "garden-writer" in result
        assert "Write notes" in result

    def test_render_router(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        result = registry.render("router", skill_descriptions="- skill-a: desc")
        assert "skill-a" in result

    def test_render_missing_var_raises(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        with pytest.raises(KeyError):
            registry.render("chat")  # missing context_section

    def test_render_missing_template_raises(self, prompts_dir) -> None:
        registry = PromptRegistry(prompts_dir)
        with pytest.raises(KeyError, match="nonexistent"):
            registry.render("nonexistent", foo="bar")
