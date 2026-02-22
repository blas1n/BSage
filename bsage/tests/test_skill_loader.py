"""Tests for bsage.core.skill_loader — YAML scanning and SkillMeta registry."""

import pytest

from bsage.core.exceptions import SkillLoadError
from bsage.core.skill_loader import SkillLoader, SkillMeta


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
        assert meta.requires_connector is None
        assert meta.entrypoint is None
        assert meta.trigger is None
        assert meta.rules == []

    def test_all_fields(self) -> None:
        meta = SkillMeta(
            name="calendar-input",
            version="2.0.0",
            category="input",
            is_dangerous=True,
            description="Calendar sync",
            author="bslab",
            requires_connector="google-calendar",
            entrypoint="skill.py::execute",
            trigger={"type": "cron", "schedule": "*/15 * * * *"},
            rules=["garden-writer"],
        )
        assert meta.requires_connector == "google-calendar"
        assert meta.entrypoint == "skill.py::execute"
        assert meta.trigger == {"type": "cron", "schedule": "*/15 * * * *"}
        assert meta.rules == ["garden-writer"]


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
            "rules:\n"
            "  - insight-linker\n"
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
            "requires_connector: google-calendar\n"
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
        assert meta.rules == ["insight-linker"]

    async def test_load_all_parses_input_skill(self, skills_dir) -> None:
        loader = SkillLoader(skills_dir)
        registry = await loader.load_all()
        meta = registry["calendar-input"]
        assert meta.requires_connector == "google-calendar"
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

    async def test_load_all_nonexistent_dir(self, tmp_path) -> None:
        loader = SkillLoader(tmp_path / "does-not-exist")
        registry = await loader.load_all()
        assert len(registry) == 0
