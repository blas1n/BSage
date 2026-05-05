"""Tests for ``GardenWriter.ensure_entity_stub`` (Step B2).

Auto-stub creation closes the gap between ``[[wikilink]]`` text in note
bodies and graph nodes — without it, ``[[Vaultwarden]]`` would dangle
forever and the graph extractor's WIKILINK sweep would have nothing to
attach to. The stub is intentionally cheap (one frontmatter block + a
backlink list) so creating thousands during a bulk import is safe.

Contract under test:
1. First call creates ``garden/entities/<slug>.md`` with frontmatter
   ``auto_stub: true`` and a ``Mentioned in`` section.
2. Subsequent calls with a NEW mention path append to the ``mentions``
   list and rewrite the body section.
3. Calling twice with the SAME mention is a no-op (idempotent).
4. Once the stub has been edited by a human (``auto_stub`` removed or
   set to false), future calls update only the ``mentions`` list — the
   body stays under user control.
5. The slug normalises Korean / unicode names so we don't write paths
   with raw question-marks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter


@pytest.fixture()
def writer(tmp_path: Path) -> tuple[Vault, GardenWriter]:
    vault = Vault(tmp_path)
    vault.ensure_dirs()
    return vault, GardenWriter(vault)


def _read_frontmatter(path: Path) -> dict:
    import yaml

    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    closing = raw.find("\n---\n", 4)
    return yaml.safe_load(raw[4:closing])


class TestEnsureEntityStub:
    @pytest.mark.asyncio
    async def test_creates_new_stub(self, writer: tuple[Vault, GardenWriter]) -> None:
        vault, w = writer
        mentioning = vault.root / "ideas" / "vaultwarden-setup.md"
        mentioning.parent.mkdir(parents=True, exist_ok=True)
        mentioning.write_text("body", encoding="utf-8")

        path = await w.ensure_entity_stub("Vaultwarden", mentioning)

        assert path.exists()
        assert path.parent == vault.root / "garden" / "entities"
        assert path.name == "vaultwarden.md"
        fm = _read_frontmatter(path)
        assert fm["title"] == "Vaultwarden"
        assert fm["auto_stub"] is True
        assert fm["maturity"] == "seedling"
        assert fm["mentions"] == ["ideas/vaultwarden-setup.md"]
        body = path.read_text(encoding="utf-8")
        assert "## Mentioned in" in body
        assert "[[vaultwarden-setup]]" in body

    @pytest.mark.asyncio
    async def test_second_mention_appends(self, writer: tuple[Vault, GardenWriter]) -> None:
        vault, w = writer
        first = vault.root / "ideas" / "first.md"
        second = vault.root / "ideas" / "second.md"
        for f in (first, second):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("body", encoding="utf-8")

        path = await w.ensure_entity_stub("Caddy", first)
        await w.ensure_entity_stub("Caddy", second)

        fm = _read_frontmatter(path)
        assert fm["mentions"] == ["ideas/first.md", "ideas/second.md"]
        body = path.read_text(encoding="utf-8")
        assert "[[first]]" in body
        assert "[[second]]" in body

    @pytest.mark.asyncio
    async def test_repeat_same_mention_is_idempotent(
        self, writer: tuple[Vault, GardenWriter]
    ) -> None:
        vault, w = writer
        mentioning = vault.root / "ideas" / "n.md"
        mentioning.parent.mkdir(parents=True, exist_ok=True)
        mentioning.write_text("body", encoding="utf-8")

        path = await w.ensure_entity_stub("X", mentioning)
        before = path.read_text(encoding="utf-8")
        await w.ensure_entity_stub("X", mentioning)
        after = path.read_text(encoding="utf-8")
        assert before == after

    @pytest.mark.asyncio
    async def test_human_edited_stub_keeps_body_but_tracks_mentions(
        self, writer: tuple[Vault, GardenWriter]
    ) -> None:
        vault, w = writer
        first = vault.root / "ideas" / "a.md"
        second = vault.root / "ideas" / "b.md"
        for f in (first, second):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("body", encoding="utf-8")

        path = await w.ensure_entity_stub("Project X", first)
        # Simulate the user filling in the stub and removing the auto flag.
        import yaml

        raw = path.read_text(encoding="utf-8")
        closing = raw.find("\n---\n", 4)
        fm = yaml.safe_load(raw[4:closing])
        fm["auto_stub"] = False
        new_body = "# Project X\n\nA real description from the user.\n"
        path.write_text(
            f"---\n{yaml.dump(fm).strip()}\n---\n{new_body}",
            encoding="utf-8",
        )

        await w.ensure_entity_stub("Project X", second)

        body_after = path.read_text(encoding="utf-8")
        # User content preserved verbatim.
        assert "A real description from the user." in body_after
        # But the mentions list is still updated in frontmatter.
        fm_after = _read_frontmatter(path)
        assert fm_after["mentions"] == ["ideas/a.md", "ideas/b.md"]

    @pytest.mark.asyncio
    async def test_unicode_name_slug(self, writer: tuple[Vault, GardenWriter]) -> None:
        vault, w = writer
        mentioning = vault.root / "ideas" / "korean.md"
        mentioning.parent.mkdir(parents=True, exist_ok=True)
        mentioning.write_text("body", encoding="utf-8")

        path = await w.ensure_entity_stub("한글 노트", mentioning)
        assert path.exists()
        # Korean characters survive (slugify preserves \w under unicode).
        assert "한글" in path.name

    @pytest.mark.asyncio
    async def test_empty_name_raises(self, writer: tuple[Vault, GardenWriter]) -> None:
        _, w = writer
        with pytest.raises(ValueError, match="non-empty"):
            await w.ensure_entity_stub("   ", Path("/tmp/x.md"))


class TestIngestCompilerInvokesStubCreation:
    """End-to-end: a compile_batch run with entities populates the stubs."""

    @pytest.mark.asyncio
    async def test_compile_batch_creates_stubs_for_entities(self, tmp_path: Path) -> None:
        import json
        from unittest.mock import AsyncMock

        from bsage.garden.ingest_compiler import BatchItem, IngestCompiler

        vault = Vault(tmp_path)
        vault.ensure_dirs()
        w = GardenWriter(vault)

        plan = json.dumps(
            [
                {
                    "action": "create",
                    "target_path": None,
                    "title": "Vaultwarden behind Caddy",
                    "content": "Got [[Vaultwarden]] running behind [[Caddy]].",
                    "tags": ["self-hosting"],
                    "entities": ["[[Vaultwarden]]", "[[Caddy]]"],
                    "reason": "test",
                    "source_seeds": [1],
                    "related": [],
                }
            ]
        )
        llm = AsyncMock()
        llm.chat = AsyncMock(return_value=plan)

        compiler = IngestCompiler(
            garden_writer=w,
            llm_client=llm,
            retriever=None,
            event_bus=None,
            max_updates=10,
        )
        await compiler.compile_batch(
            items=[BatchItem(label="x.md", content="hi")], seed_source="test"
        )

        entities_dir = vault.root / "garden" / "entities"
        stubs = sorted(p.name for p in entities_dir.glob("*.md"))
        assert stubs == ["caddy.md", "vaultwarden.md"]
