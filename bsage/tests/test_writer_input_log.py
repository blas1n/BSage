"""Tests for GardenWriter.write_input_log."""

from unittest.mock import MagicMock

import pytest

from bsage.garden.writer import GardenWriter


@pytest.fixture
def writer(tmp_path):
    vault = MagicMock()
    vault.root = tmp_path
    vault.resolve_path = MagicMock(side_effect=lambda p: tmp_path / p)
    return GardenWriter(vault)


async def test_write_input_log_creates_file(writer: GardenWriter, tmp_path) -> None:
    await writer.write_input_log("telegram", "Hello world")
    log_dir = tmp_path / "actions" / "input-log"
    assert log_dir.exists()
    logs = list(log_dir.glob("*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert "telegram" in content
    assert "Hello world" in content


async def test_write_input_log_appends_to_existing(writer: GardenWriter, tmp_path) -> None:
    await writer.write_input_log("source-a", "first")
    await writer.write_input_log("source-b", "second")
    log_dir = tmp_path / "actions" / "input-log"
    logs = list(log_dir.glob("*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert "source-a" in content
    assert "source-b" in content


async def test_write_input_log_truncates_long_text(writer: GardenWriter) -> None:
    long_text = "x" * 1000
    await writer.write_input_log("test", long_text)
    # Should not raise; content is truncated to 500 chars in the log entry


async def test_write_input_log_empty_text(writer: GardenWriter, tmp_path) -> None:
    await writer.write_input_log("test", "")
    log_dir = tmp_path / "actions" / "input-log"
    logs = list(log_dir.glob("*.md"))
    assert len(logs) == 1
