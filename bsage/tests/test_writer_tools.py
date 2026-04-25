"""Direct unit tests for ``bsage.garden.writer_tools`` (M15 split).

The OpenAI tool-call schemas are pure data, but they are part of the agent's
external contract — every public field name is matched by name when the LLM
emits a ``tool_calls`` payload. These tests guard the schema shape so
refactors cannot silently strip a parameter.
"""

from __future__ import annotations

from bsage.garden import writer_tools
from bsage.garden.writer_tools import (
    APPEND_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    SEARCH_VAULT_TOOL,
    UPDATE_NOTE_TOOL,
    WRITE_NOTE_TOOL,
    WRITE_SEED_TOOL,
)

ALL_TOOLS = [
    WRITE_NOTE_TOOL,
    WRITE_SEED_TOOL,
    UPDATE_NOTE_TOOL,
    DELETE_NOTE_TOOL,
    APPEND_NOTE_TOOL,
    SEARCH_VAULT_TOOL,
]


class TestToolEnvelope:
    def test_every_tool_is_function_type(self) -> None:
        for tool in ALL_TOOLS:
            assert tool["type"] == "function"
            assert "function" in tool

    def test_function_has_name_description_parameters(self) -> None:
        for tool in ALL_TOOLS:
            fn = tool["function"]
            assert isinstance(fn["name"], str) and fn["name"]
            assert isinstance(fn["description"], str) and fn["description"]
            params = fn["parameters"]
            assert params["type"] == "object"
            assert isinstance(params["properties"], dict)
            assert "required" in params

    def test_tool_names_are_unique(self) -> None:
        names = [t["function"]["name"] for t in ALL_TOOLS]
        assert len(set(names)) == len(names)

    def test_canonical_tool_names(self) -> None:
        names = {t["function"]["name"] for t in ALL_TOOLS}
        assert names == {
            "write-note",
            "write-seed",
            "update-note",
            "delete-note",
            "append-note",
            "search-vault",
        }


class TestWriteNoteSchema:
    def test_required_fields(self) -> None:
        params = WRITE_NOTE_TOOL["function"]["parameters"]
        assert set(params["required"]) == {"title", "content"}

    def test_note_type_enum_includes_canonical_types(self) -> None:
        enum = WRITE_NOTE_TOOL["function"]["parameters"]["properties"]["note_type"]["enum"]
        # Must be sorted and include the canonical set.
        assert enum == sorted(enum)
        for required in ("idea", "insight", "project", "event", "task", "fact"):
            assert required in enum


class TestUpdateAppendDeleteSchemas:
    def test_update_note_required(self) -> None:
        assert set(UPDATE_NOTE_TOOL["function"]["parameters"]["required"]) == {"path", "content"}

    def test_append_note_required(self) -> None:
        assert set(APPEND_NOTE_TOOL["function"]["parameters"]["required"]) == {"path", "text"}

    def test_delete_note_required(self) -> None:
        assert set(DELETE_NOTE_TOOL["function"]["parameters"]["required"]) == {"path"}


class TestSearchVaultSchema:
    def test_required_query(self) -> None:
        params = SEARCH_VAULT_TOOL["function"]["parameters"]
        assert params["required"] == ["query"]
        assert "max_results" in params["properties"]
        assert "context_dirs" in params["properties"]


class TestPublicSurface:
    def test_dunder_all_lists_every_constant(self) -> None:
        assert set(writer_tools.__all__) == {
            "APPEND_NOTE_TOOL",
            "DELETE_NOTE_TOOL",
            "SEARCH_VAULT_TOOL",
            "UPDATE_NOTE_TOOL",
            "WRITE_NOTE_TOOL",
            "WRITE_SEED_TOOL",
        }

    def test_writer_module_re_exports(self) -> None:
        # Existing imports go through bsage.garden.writer — must keep working.
        from bsage.garden.writer import (
            APPEND_NOTE_TOOL as A,
        )
        from bsage.garden.writer import (
            DELETE_NOTE_TOOL as D,
        )
        from bsage.garden.writer import (
            SEARCH_VAULT_TOOL as S,
        )
        from bsage.garden.writer import (
            UPDATE_NOTE_TOOL as U,
        )
        from bsage.garden.writer import (
            WRITE_NOTE_TOOL as WN,
        )
        from bsage.garden.writer import (
            WRITE_SEED_TOOL as WS,
        )

        assert A is APPEND_NOTE_TOOL
        assert D is DELETE_NOTE_TOOL
        assert S is SEARCH_VAULT_TOOL
        assert U is UPDATE_NOTE_TOOL
        assert WN is WRITE_NOTE_TOOL
        assert WS is WRITE_SEED_TOOL
