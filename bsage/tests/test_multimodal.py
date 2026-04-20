"""Tests for multimodal extraction."""

from __future__ import annotations

from bsage.garden.graph_models import GraphEntity, GraphRelationship
from bsage.garden.multimodal import (
    ExtractionResult,
    MediaType,
    classify_media,
    extract_from_media,
    extract_image_description,
    write_extraction_note,
)
from bsage.garden.storage import FileSystemStorage


class TestClassifyMedia:
    def test_markdown(self):
        assert classify_media("notes/a.md") == MediaType.MARKDOWN

    def test_pdf(self):
        assert classify_media("papers/doc.pdf") == MediaType.PDF

    def test_images(self):
        assert classify_media("img.png") == MediaType.IMAGE
        assert classify_media("img.JPG") == MediaType.IMAGE
        assert classify_media("img.webp") == MediaType.IMAGE

    def test_audio(self):
        assert classify_media("talk.mp3") == MediaType.AUDIO
        assert classify_media("note.m4a") == MediaType.AUDIO

    def test_video(self):
        assert classify_media("clip.mp4") == MediaType.VIDEO

    def test_unknown(self):
        assert classify_media("data.xyz") == MediaType.UNKNOWN
        assert classify_media("noext") == MediaType.UNKNOWN


class TestExtractImageDescription:
    async def test_calls_llm_with_prompt(self):
        captured = []

        async def image_llm(data: bytes, prompt: str) -> str:
            captured.append((data, prompt))
            return "A diagram showing three nodes connected in a triangle"

        result = await extract_image_description(b"fakeimage", image_llm)
        assert "diagram" in result.lower()
        assert len(captured) == 1
        assert captured[0][0] == b"fakeimage"
        assert "knowledge graph" in captured[0][1].lower()

    async def test_custom_prompt(self):
        async def image_llm(data: bytes, prompt: str) -> str:
            return prompt  # echo back

        result = await extract_image_description(b"x", image_llm, prompt="custom")
        assert result == "custom"


class TestExtractFromMedia:
    async def test_pdf_without_llm_returns_empty_entities(self):
        # pypdf may not be installed; just verify graceful handling
        result = await extract_from_media("doc.pdf", b"not-really-pdf")
        assert result.media_type == MediaType.PDF
        # No LLM extractor → no entities
        assert result.entities == []
        assert result.relationships == []

    async def test_image_with_llm(self):
        async def image_llm(data: bytes, prompt: str) -> str:
            return "Alice and Bob are in a meeting"

        async def llm_extractor(path: str, text: str):
            ent_a = GraphEntity(name="Alice", entity_type="person", source_path=path)
            ent_b = GraphEntity(name="Bob", entity_type="person", source_path=path)
            rel = GraphRelationship(
                source_id=ent_a.id,
                target_id=ent_b.id,
                rel_type="meets_with",
                source_path=path,
            )
            return [ent_a, ent_b], [rel]

        result = await extract_from_media(
            "screenshot.png",
            b"image-data",
            llm_extractor=llm_extractor,
            image_llm_fn=image_llm,
        )
        assert result.media_type == MediaType.IMAGE
        assert len(result.entities) == 2
        assert len(result.relationships) == 1
        assert "Alice" in result.extracted_text

    async def test_image_without_image_llm(self):
        """Image with no vision LLM → no text extracted."""
        result = await extract_from_media("img.png", b"x")
        assert result.media_type == MediaType.IMAGE
        assert result.extracted_text == ""
        assert result.entities == []

    async def test_unknown_media_type(self):
        result = await extract_from_media("data.xyz", b"x")
        assert result.media_type == MediaType.UNKNOWN
        assert result.entities == []

    async def test_audio_logs_not_implemented(self):
        result = await extract_from_media("talk.mp3", b"x")
        assert result.media_type == MediaType.AUDIO
        # Transcription not implemented yet
        assert result.extracted_text == ""

    async def test_note_content_has_frontmatter(self):
        result = await extract_from_media("img.png", b"x")
        assert "---" in result.note_content
        assert "type: extracted" in result.note_content
        assert "media_type: image" in result.note_content
        assert "source_file: img.png" in result.note_content


class TestWriteExtractionNote:
    async def test_writes_to_storage(self, tmp_path):
        storage = FileSystemStorage(tmp_path / "vault")
        result = ExtractionResult(
            source_path="garden/extracted/image-test-12345678.md",
            media_type=MediaType.IMAGE,
            extracted_text="a diagram",
            entities=[],
            relationships=[],
            note_content="---\ntype: extracted\n---\n\nbody",
        )
        path = await write_extraction_note(storage, result)
        assert path == result.source_path
        content = await storage.read(path)
        assert "body" in content
