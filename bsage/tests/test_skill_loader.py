"""Tests for bsage.core.skill_loader — YAML scanning and SkillMeta registry."""

import pytest

from bsage.core.exceptions import SkillLoadError
from bsage.core.skill_loader import OutputTarget, SkillLoader, SkillMeta


class TestSkillMeta:
    """Test SkillMeta dataclass."""

    def test_required_fields(self) -> None:
        meta = SkillMeta(
            name="test",
            version="1.0.0",
            category="process",
            is_dangerous=False,
            description="A test skill",
        )
        assert meta.name == "test"
        assert meta.version == "1.0.0"
        assert meta.category == "process"
        assert meta.is_dangerous is False
        assert meta.description == "A test skill"

    def test_optional_fields_defaults(self) -> None:
        meta = SkillMeta(
            name="test",
            version="1.0.0",
            category="process",
            is_dangerous=False,
            description="A test skill",
        )
        assert meta.author == ""
        assert meta.entrypoint is None
        assert meta.trigger is None
        assert meta.credentials is None
        assert meta.read_context == []
        assert meta.output_target is None
        assert meta.output_note_type == "idea"
        assert meta.system_prompt is None
        assert meta.output_format is None

    def test_all_fields(self) -> None:
        meta = SkillMeta(
            name="calendar-input",
            version="2.0.0",
            category="input",
            is_dangerous=True,
            description="Calendar sync",
            author="bslab",
            entrypoint="skill.py::execute",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
            credentials={"fields": [{"name": "api_key", "required": True}]},
        )
        assert meta.entrypoint == "skill.py::execute"
        assert meta.trigger == {"type": "cron", "schedule": "*/15 * * * *"}
        assert meta.credentials == {"fields": [{"name": "api_key", "required": True}]}

    def test_yaml_only_fields(self) -> None:
        meta = SkillMeta(
            name="weekly-digest",
            version="1.0.0",
            category="process",
            is_dangerous=False,
            description="Weekly digest",
            read_context=["garden/idea", "garden/insight"],
            output_target=OutputTarget.GARDEN,
            output_note_type="insight",
            system_prompt="You are a digest generator.",
            output_format="json",
        )
        assert meta.read_context == ["garden/idea", "garden/insight"]
        assert meta.output_target is OutputTarget.GARDEN
        assert meta.output_note_type == "insight"
        assert meta.system_prompt == "You are a digest generator."
        assert meta.output_format == "json"


class TestSkillLoader:
    """Test SkillLoader YAML scanning and registry."""

    @pytest.fixture()
    def skills_dir(self, tmp_path):
        """Create a temporary skills directory with sample skills."""
        # Valid process skill
        skill1 = tmp_path / "garden-writer"
        skill1.mkdir()
        (skill1 / "skill.yaml").write_text(
            "name: garden-writer\n"
            "version: 1.0.0\n"
            "category: process\n"
            "is_dangerous: false\n"
            "description: Write garden notes\n"
            "trigger:\n"
            "  type: on_input\n"
        )

        # Valid input skill
        skill2 = tmp_path / "calendar-input"
        skill2.mkdir()
        (skill2 / "skill.yaml").write_text(
            "name: calendar-input\n"
            "version: 1.0.0\n"
            "category: input\n"
            "is_dangerous: false\n"
            "description: Collect calendar events\n"
            "entrypoint: skill.py::execute\n"
            "trigger:\n"
            "  type: cron\n"
            "  schedule: '*/15 * * * *'\n"
        )

        return tmp_path

    async def test_load_all_discovers_skills(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        registry = await loader.load_all()
        assert "garden-writer" in registry
        assert "calendar-input" in registry
        assert len(registry) == 2

    async def test_load_all_returns_skill_meta(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        registry = await loader.load_all()
        meta = registry["garden-writer"]
        assert isinstance(meta, SkillMeta)
        assert meta.category == "process"
        assert meta.is_dangerous is False
        assert meta.trigger == {"type": "on_input"}

    async def test_load_all_parses_input_skill(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        registry = await loader.load_all()
        meta = registry["calendar-input"]
        assert meta.entrypoint == "skill.py::execute"
        assert meta.trigger["type"] == "cron"

    async def test_load_all_skips_missing_yaml(self, tmp_path) -> None:
        (tmp_path / "bad-skill").mkdir()
        # No skill.yaml inside
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "bad-skill" not in registry
        assert len(registry) == 0

    async def test_load_all_skips_files_not_dirs(self, tmp_path) -> None:
        (tmp_path / "not-a-dir.txt").write_text("hello")
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert len(registry) == 0

    async def test_get_returns_skill(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        await loader.load_all()
        meta = loader.get("garden-writer")
        assert meta.name == "garden-writer"

    async def test_get_raises_on_unknown_skill(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        await loader.load_all()
        with pytest.raises(SkillLoadError, match="not found"):
            loader.get("nonexistent")

    async def test_load_all_handles_invalid_yaml(self, tmp_path) -> None:
        skill_dir = tmp_path / "broken-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text("name: broken\n[invalid yaml")
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "broken" not in registry

    async def test_load_all_handles_missing_required_fields(self, tmp_path) -> None:
        skill_dir = tmp_path / "incomplete-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text("name: incomplete\nversion: 1.0.0\n")
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "incomplete" not in registry

    async def test_load_all_rejects_invalid_skill_name(self, tmp_path) -> None:
        skill_dir = tmp_path / "bad-name"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            "name: Bad_Name!\n"
            "version: 1.0.0\n"
            "category: process\n"
            "is_dangerous: false\n"
            "description: Invalid name\n"
        )
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "Bad_Name!" not in registry

    async def test_load_all_rejects_invalid_category(self, tmp_path) -> None:
        skill_dir = tmp_path / "meta-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            "name: meta-skill\n"
            "version: 1.0.0\n"
            "category: meta\n"
            "is_dangerous: false\n"
            "description: Old meta category\n"
        )
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "meta-skill" not in registry

    async def test_load_all_parses_yaml_only_fields(self, tmp_path) -> None:
        skill_dir = tmp_path / "weekly-digest"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            "name: weekly-digest\n"
            "version: 1.0.0\n"
            "category: process\n"
            "is_dangerous: false\n"
            "description: Weekly digest\n"
            "read_context:\n"
            "  - garden/idea\n"
            "  - garden/insight\n"
            "output_target: garden\n"
            "output_note_type: insight\n"
            "output_format: json\n"
            "system_prompt: You are a digest generator.\n"
        )
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        meta = registry["weekly-digest"]
        assert meta.read_context == ["garden/idea", "garden/insight"]
        assert meta.output_target is OutputTarget.GARDEN
        assert meta.output_note_type == "insight"
        assert meta.output_format == "json"
        assert meta.system_prompt == "You are a digest generator."

    async def test_load_all_parses_credentials(self, tmp_path) -> None:
        skill_dir = tmp_path / "telegram-input"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            "name: telegram-input\n"
            "version: 1.0.0\n"
            "category: input\n"
            "is_dangerous: false\n"
            "description: Telegram messages\n"
            "credentials:\n"
            "  fields:\n"
            "    - name: bot_token\n"
            "      description: Bot API token\n"
            "      required: true\n"
        )
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        meta = registry["telegram-input"]
        assert meta.credentials is not None
        assert meta.credentials["fields"][0]["name"] == "bot_token"

    async def test_load_all_rejects_invalid_output_target(self, tmp_path) -> None:
        skill_dir = tmp_path / "bad-target"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            "name: bad-target\n"
            "version: 1.0.0\n"
            "category: process\n"
            "is_dangerous: false\n"
            "description: Invalid output target\n"
            "output_target: invalid\n"
        )
        loader = SkillLoader(tmp_path)
        registry = await loader.load_all()
        assert "bad-target" not in registry

    async def test_load_all_nonexistent_dir(self, tmp_path) -> None:
        loader = SkillLoader(tmp_path / "does-not-exist")
        registry = await loader.load_all()
        assert len(registry) == 0
