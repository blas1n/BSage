"""Tests for the notion-output plugin."""

from unittest.mock import AsyncMock, MagicMock, patch


def _load_plugin():
    """Import the plugin module and return the execute function and module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "notion_output", "plugins/notion-output/plugin.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute, mod._markdown_to_blocks


def _make_context(
    input_data: dict | None = None,
    credentials: dict | None = None,
    config: dict | None = None,
) -> MagicMock:
    ctx = MagicMock()
    ctx.input_data = input_data
    ctx.credentials = credentials or {}
    ctx.garden = AsyncMock()
    ctx.garden.write_seed = AsyncMock()
    ctx.garden.write_action = AsyncMock()
    ctx.config = config or {}
    return ctx


# ── execute() tests ───────────────────────────────────────────────────


async def test_execute_creates_page(tmp_path) -> None:
    execute_fn, _ = _load_plugin()

    # Create a source markdown file
    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "garden" / "my-note.md"
    source.parent.mkdir(parents=True)
    source.write_text("Some paragraph content.\n")

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"notion_api_key": "ntn_test_key", "database_id": "db-123"},
        config={"vault_path": str(vault)},
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "page-abc-123"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["synced"] is True
    assert result["page_id"] == "page-abc-123"
    assert result["title"] == "my-note"

    # Verify API call was made
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args
    assert "https://api.notion.com/v1/pages" in call_kwargs[0]
    payload = call_kwargs[1]["json"]
    assert payload["parent"]["database_id"] == "db-123"
    assert payload["properties"]["Name"]["title"][0]["text"]["content"] == "my-note"
    # Verify auth header
    headers = call_kwargs[1]["headers"]
    assert headers["Authorization"] == "Bearer ntn_test_key"
    assert headers["Notion-Version"] == "2022-06-28"


async def test_execute_parses_frontmatter(tmp_path) -> None:
    execute_fn, _ = _load_plugin()

    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "garden" / "tagged-note.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\n"
        "title: My Custom Title\n"
        "tags:\n"
        "  - productivity\n"
        "  - bsage\n"
        "status: growing\n"
        "---\n"
        "This is the note body.\n"
    )

    ctx = _make_context(
        input_data={"path": str(source)},
        credentials={"notion_api_key": "ntn_key", "database_id": "db-456"},
        config={"vault_path": str(vault)},
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "page-def-456"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await execute_fn(ctx)

    assert result["synced"] is True
    assert result["title"] == "My Custom Title"

    # Verify tags were included in the payload
    payload = mock_client.post.call_args[1]["json"]
    assert "Tags" in payload["properties"]
    tag_names = [t["name"] for t in payload["properties"]["Tags"]["multi_select"]]
    assert "productivity" in tag_names
    assert "bsage" in tag_names

    # Verify the title in the payload uses frontmatter title
    assert payload["properties"]["Name"]["title"][0]["text"]["content"] == "My Custom Title"


async def test_execute_source_not_exists(tmp_path) -> None:
    execute_fn, _ = _load_plugin()

    ctx = _make_context(
        input_data={"path": str(tmp_path / "nonexistent.md")},
        credentials={"notion_api_key": "key", "database_id": "db"},
        config={"vault_path": str(tmp_path)},
    )

    result = await execute_fn(ctx)

    assert result["synced"] is False
    assert "does not exist" in result["error"]


def test_markdown_to_blocks() -> None:
    _, md_to_blocks = _load_plugin()

    md = (
        "# Heading One\n"
        "## Heading Two\n"
        "### Heading Three\n"
        "A plain paragraph.\n"
        "\n"
        "- Bullet item one\n"
        "* Bullet item two\n"
    )

    blocks = md_to_blocks(md)

    assert len(blocks) == 6

    # Heading 1
    assert blocks[0]["type"] == "heading_1"
    assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Heading One"

    # Heading 2
    assert blocks[1]["type"] == "heading_2"
    assert blocks[1]["heading_2"]["rich_text"][0]["text"]["content"] == "Heading Two"

    # Heading 3
    assert blocks[2]["type"] == "heading_3"
    assert blocks[2]["heading_3"]["rich_text"][0]["text"]["content"] == "Heading Three"

    # Paragraph
    assert blocks[3]["type"] == "paragraph"
    assert blocks[3]["paragraph"]["rich_text"][0]["text"]["content"] == "A plain paragraph."

    # Bulleted list items (both - and * syntax)
    assert blocks[4]["type"] == "bulleted_list_item"
    assert blocks[4]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "Bullet item one"

    assert blocks[5]["type"] == "bulleted_list_item"
    assert blocks[5]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "Bullet item two"
