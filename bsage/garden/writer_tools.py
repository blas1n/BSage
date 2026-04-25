"""LLM tool-call definitions used by ``GardenWriter`` and ``AgentLoop``.

Split out of ``bsage/garden/writer.py`` (M15, Hardening Sprint 2). The
constants are pure data (``dict``s in OpenAI tool-call shape) and have no
runtime dependencies — keeping them in their own module lets callers import
the schemas without paying the cost of loading the rest of ``writer``.
"""

from __future__ import annotations

from typing import Any

from bsage.garden.note import _VALID_NOTE_TYPES

WRITE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write-note",
        "description": (
            "Write a processed garden note — insights, analyzed conclusions, "
            "or structured summaries. Use when the content has been refined "
            "or the user asks for an insight/project note."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title of the note"},
                "content": {"type": "string", "description": "Markdown body content"},
                "note_type": {
                    "type": "string",
                    "enum": sorted(_VALID_NOTE_TYPES),
                    "description": "Note category (default: idea)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization",
                },
            },
            "required": ["title", "content"],
        },
    },
}

WRITE_SEED_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write-seed",
        "description": (
            "Save a seed note — raw ideas, fleeting thoughts, or "
            "unprocessed data. Use by default when the user wants "
            "to save something new."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the seed",
                },
                "content": {
                    "type": "string",
                    "description": "Body text of the idea or data",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for categorization",
                },
            },
            "required": ["title", "content"],
        },
    },
}


UPDATE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update-note",
        "description": (
            "Update the content of an existing vault note. "
            "Use when modifying, replacing, or adding links to an existing note."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path (e.g. garden/idea/my-note.md)",
                },
                "content": {
                    "type": "string",
                    "description": "New markdown body content",
                },
                "preserve_frontmatter": {
                    "type": "boolean",
                    "description": "Keep existing YAML frontmatter (default: true)",
                },
            },
            "required": ["path", "content"],
        },
    },
}

DELETE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete-note",
        "description": (
            "Delete a note from the vault. Cannot delete action logs. "
            "Use when a note is outdated, duplicated, or no longer needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path to delete",
                },
            },
            "required": ["path"],
        },
    },
}

APPEND_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "append-note",
        "description": (
            "Append text to an existing vault note. "
            "Use when adding new content without replacing what already exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Vault-relative path (e.g. garden/idea/my-note.md)",
                },
                "text": {
                    "type": "string",
                    "description": "Text to append to the note",
                },
            },
            "required": ["path", "text"],
        },
    },
}

SEARCH_VAULT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search-vault",
        "description": (
            "Search the vault for relevant notes using semantic search. "
            "Use to find related notes, check for duplicates, or gather context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "context_dirs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Vault subdirectories to search "
                        "(default: seeds, garden/idea, garden/insight)"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max notes to return (default: 10)",
                },
            },
            "required": ["query"],
        },
    },
}


__all__ = [
    "APPEND_NOTE_TOOL",
    "DELETE_NOTE_TOOL",
    "SEARCH_VAULT_TOOL",
    "UPDATE_NOTE_TOOL",
    "WRITE_NOTE_TOOL",
    "WRITE_SEED_TOOL",
]
