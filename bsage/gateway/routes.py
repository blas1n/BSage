"""HTTP route handlers for the BSage Gateway."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bsage.core.exceptions import VaultPathError
from bsage.core.patterns import WIKILINK_RE
from bsage.core.plugin_loader import PluginMeta
from bsage.core.skill_loader import SkillMeta
from bsage.gateway.dependencies import AppState

logger = structlog.get_logger(__name__)
_TAG_RE = re.compile(r"(?:^|(?<=\s))#([a-zA-Z][a-zA-Z0-9_/-]+)", re.MULTILINE)


class ChatMessage(BaseModel):
    """Request body for POST /api/chat."""

    message: str
    history: list[dict[str, Any]] = []
    context_paths: list[str] | None = None


class ConfigUpdate(BaseModel):
    """Request body for PATCH /api/config.

    Only fields included in the request body are changed.
    Use model_fields_set to distinguish 'not provided' from 'set to null'.
    """

    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    safe_mode: bool | None = None
    disabled_entries: list[str] | None = None


class CredentialStoreRequest(BaseModel):
    """Request body for POST /api/entries/{name}/credentials."""

    credentials: dict[str, str]


def _find_entry(state: AppState, name: str) -> PluginMeta | SkillMeta:
    """Look up a plugin or skill by name, raising 404 if not found."""
    try:
        return state.plugin_loader.get(name)
    except Exception:
        pass
    try:
        return state.skill_loader.get(name)
    except Exception:
        pass
    raise HTTPException(status_code=404, detail=f"'{name}' not found in registry")


def _meta_to_dict(
    meta: Any,
    danger_map: dict[str, bool] | None = None,
    configured_services: list[str] | None = None,
    disabled_entries: list[str] | None = None,
) -> dict[str, Any]:
    """Serialize a PluginMeta or SkillMeta to a JSON-safe dict."""
    creds = meta.credentials
    if isinstance(creds, list):
        has_credentials = bool(creds)
    elif isinstance(creds, dict):
        has_credentials = bool(creds.get("fields"))
    else:
        has_credentials = False
    credentials_configured = meta.name in (configured_services or []) if has_credentials else True
    # Entries that need credentials but haven't been set up default to disabled.
    if has_credentials and not credentials_configured:
        enabled = False
    else:
        enabled = meta.name not in (disabled_entries or [])
    return {
        "name": meta.name,
        "version": meta.version,
        "category": meta.category,
        "is_dangerous": (danger_map or {}).get(meta.name, False),
        "description": meta.description,
        "has_credentials": has_credentials,
        "credentials_configured": credentials_configured,
        "enabled": enabled,
    }


def create_routes(state: AppState) -> APIRouter:
    """Create API routes with injected application state.

    Routes are split into *public* (health, webhooks) and *protected*
    (everything else).  The protected router applies ``state.get_current_user``
    as a router-level dependency so individual handlers don't need to declare it.
    """
    public = APIRouter(prefix="/api")
    protected = APIRouter(
        prefix="/api",
        dependencies=[Depends(state.get_current_user)],
    )

    @public.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @public.get("/auth/callback")
    async def auth_callback(request: Request) -> HTMLResponse:
        """Handle OAuth callback from external auth provider.

        Returns an HTML page that extracts tokens from both query params
        and URL hash fragment (Supabase sends tokens in the hash),
        stores them in localStorage, and redirects to the frontend root.
        """
        params = dict(request.query_params)
        params_json = json.dumps(params)
        html = f"""<!DOCTYPE html>
<html><head><title>Authenticating...</title></head>
<body><p>Authenticating...</p><script>
(function() {{
  var p = {params_json};
  var h = window.location.hash.substring(1);
  if (h) new URLSearchParams(h).forEach(function(v,k) {{ p[k] = v; }});
  if (p.access_token) localStorage.setItem('bsage_access_token', p.access_token);
  if (p.refresh_token) localStorage.setItem('bsage_refresh_token', p.refresh_token);
  window.location.replace('/');
}})();
</script></body></html>"""
        return HTMLResponse(content=html)

    @protected.get("/plugins")
    async def list_plugins() -> list[dict[str, Any]]:
        """List all loaded Plugins (code-based)."""
        registry = await state.plugin_loader.load_all()
        configured = state.credential_store.list_services()
        disabled = state.runtime_config.disabled_entries
        return [
            _meta_to_dict(meta, state.danger_map, configured, disabled)
            for meta in registry.values()
        ]

    @protected.get("/skills")
    async def list_skills() -> list[dict[str, Any]]:
        """List all loaded Skills (LLM-based)."""
        registry = await state.skill_loader.load_all()
        configured = state.credential_store.list_services()
        disabled = state.runtime_config.disabled_entries
        return [
            _meta_to_dict(meta, state.danger_map, configured, disabled)
            for meta in registry.values()
        ]

    @protected.post("/plugins/{name}/run")
    async def run_plugin(name: str) -> dict[str, Any]:
        """Trigger a plugin by name via AgentLoop.on_input."""
        try:
            state.plugin_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if name in state.runtime_config.disabled_entries:
            raise HTTPException(status_code=403, detail=f"'{name}' is disabled")

        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            results = await state.agent_loop.on_input(name, {})
            return {"plugin": name, "results": results}
        except Exception as exc:
            logger.exception("plugin_run_failed", plugin=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @public.post("/webhooks/{name}")
    async def webhook(name: str, request: Request) -> dict[str, Any]:
        """Receive a webhook payload and trigger an input plugin."""
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            state.plugin_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        raw_bytes = await request.body()
        # Decode once for both JSON parsing and signature verification.
        # Use strict decoding — invalid UTF-8 must not silently differ
        # from the raw bytes used in HMAC verification.
        try:
            raw_str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Request body is not valid UTF-8") from None
        try:
            body = json.loads(raw_str)
        except (json.JSONDecodeError, ValueError):
            body = {}

        # Merge raw_body and signature header into the parsed body so
        # existing plugins that read input_data keys directly still work,
        # while plugins that need signature verification (e.g. whatsapp)
        # can access raw_body and x-hub-signature-256.
        if isinstance(body, dict):
            body.setdefault("raw_body", raw_str)
            sig = request.headers.get("x-hub-signature-256", "")
            if sig:
                body.setdefault("x-hub-signature-256", sig)
        else:
            body = {
                "data": body,
                "raw_body": raw_str,
            }

        try:
            results = await state.agent_loop.on_input(name, body)
            return {"plugin": name, "results": results}
        except Exception as exc:
            logger.exception("webhook_plugin_failed", plugin=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @protected.post("/run/{name}")
    async def run_entry(name: str) -> dict[str, Any]:
        """Run a plugin or skill by name via unified registry."""
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            state.agent_loop.get_entry(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"'{name}' not found in registry") from None

        if name in state.runtime_config.disabled_entries:
            raise HTTPException(status_code=403, detail=f"'{name}' is disabled")

        try:
            results = await state.agent_loop.on_input(name, {})
            return {"name": name, "results": results}
        except Exception as exc:
            logger.exception("run_entry_failed", name=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # -- Credential setup endpoints ------------------------------------------

    @protected.get("/entries/{name}/credentials/fields")
    async def credential_fields(name: str) -> dict[str, Any]:
        """Return credential field definitions for a plugin or skill."""
        meta = _find_entry(state, name)

        if isinstance(meta, PluginMeta):
            return {"name": name, "fields": meta.credentials or []}

        # SkillMeta
        if isinstance(meta.credentials, dict):
            return {"name": name, "fields": meta.credentials.get("fields", [])}

        return {"name": name, "fields": []}

    @protected.post("/entries/{name}/credentials")
    async def store_credentials(name: str, body: CredentialStoreRequest) -> dict[str, Any]:
        """Store credentials for a plugin or skill via the GUI."""
        _find_entry(state, name)  # 404 if not found

        await state.credential_store.store(name, body.credentials)
        logger.info("credentials_stored_via_gui", name=name)
        if state.agent_loop:
            state.runtime_config.rebuild_enabled(state.agent_loop._registry, state.credential_store)
        return {"status": "ok", "name": name}

    # -- Enable/Disable toggle -----------------------------------------------

    @protected.post("/entries/{name}/toggle")
    async def toggle_entry(name: str) -> dict[str, Any]:
        """Toggle enabled/disabled state for a plugin or skill."""
        disabled: list[str] = list(state.runtime_config.disabled_entries)
        if name in disabled:
            disabled.remove(name)
            enabled = True
        else:
            disabled.append(name)
            enabled = False
        state.runtime_config.update(disabled_entries=disabled)
        if state.agent_loop:
            state.runtime_config.rebuild_enabled(state.agent_loop._registry, state.credential_store)
        logger.info("entry_toggled", name=name, enabled=enabled)
        return {"name": name, "enabled": enabled}

    # -- Vault browser -------------------------------------------------------

    @protected.get("/vault/actions")
    async def list_actions() -> list[str]:
        notes = await state.vault.read_notes("actions")
        return [str(p.name) for p in notes]

    @protected.get("/vault/tree")
    async def vault_tree() -> list[dict[str, Any]]:
        """Return the vault directory tree structure."""
        vault_root = state.vault.root

        def _walk() -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for dirpath, dirnames, filenames in os.walk(vault_root):
                # Exclude hidden directories
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                rel = os.path.relpath(dirpath, vault_root)
                if rel == ".":
                    rel = ""
                result.append(
                    {
                        "path": rel,
                        "dirs": list(dirnames),
                        "files": sorted(filenames),
                    }
                )
            return result

        return await asyncio.to_thread(_walk)

    @protected.get("/vault/file")
    async def vault_file(
        path: str = Query(..., description="Relative path within the vault"),
    ) -> dict[str, Any]:
        """Return the content of a vault file."""
        try:
            resolved = state.vault.resolve_path(path)
        except VaultPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not resolved.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        try:
            content = await state.vault.read_note_content(resolved)
        except OSError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return {"path": path, "content": content}

    # -- Vault search / backlinks / graph / tags -----------------------------

    async def _scan_vault_md_files(max_files: int = 0) -> list[tuple[str, str]]:
        """Walk vault and return (relative_path, content) for all .md files.

        Args:
            max_files: Maximum number of files to return. 0 means no limit.
        """
        vault_root = state.vault.root

        def _walk() -> list[tuple[str, str]]:
            results: list[tuple[str, str]] = []
            for dirpath, dirnames, filenames in os.walk(vault_root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for f in sorted(filenames):
                    if not f.endswith(".md"):
                        continue
                    if max_files and len(results) >= max_files:
                        return results
                    full = Path(dirpath) / f
                    rel = str(full.relative_to(vault_root))
                    try:
                        content = full.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    results.append((rel, content))
            return results

        return await asyncio.to_thread(_walk)

    def _extract_title(content: str, rel_path: str) -> str:
        """Extract title from first # heading or fallback to filename stem."""
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return Path(rel_path).stem

    def _build_stem_lookup(files: list[tuple[str, str]]) -> dict[str, str]:
        """Map lowercase filename stem → relative path (first match wins)."""
        lookup: dict[str, str] = {}
        for rel, _ in files:
            stem = Path(rel).stem.lower()
            if stem not in lookup:
                lookup[stem] = rel
        return lookup

    @protected.get("/vault/search")
    async def vault_search(
        q: str = Query(..., min_length=1, description="Search query"),
        max_files: int = Query(default=500, ge=1, le=2000, description="Max files to scan"),
    ) -> list[dict[str, Any]]:
        """Full-text search across vault .md files (case-insensitive, max 50 results)."""
        files = await _scan_vault_md_files(max_files=max_files)
        query_lower = q.lower()
        results: list[dict[str, Any]] = []

        for rel, content in files:
            matches: list[dict[str, Any]] = []
            for i, line in enumerate(content.split("\n"), start=1):
                if query_lower in line.lower():
                    matches.append({"line": i, "text": line.strip()})
            if matches:
                results.append({"path": rel, "matches": matches[:10]})
            if len(results) >= 50:
                break

        return results

    @protected.get("/vault/backlinks")
    async def vault_backlinks(
        path: str = Query(..., description="Relative path of the target note"),
    ) -> list[dict[str, Any]]:
        """Find notes containing [[wikilink]] references to the given path."""
        files = await _scan_vault_md_files()
        target_stem = Path(path).stem.lower()
        target_path_no_ext = path.removesuffix(".md").lower()
        results: list[dict[str, Any]] = []

        for rel, content in files:
            if rel == path:
                continue
            for m in WIKILINK_RE.finditer(content):
                link = m.group(1).strip()
                link_lower = link.lower()
                # Match by filename stem or by relative path (with/without .md)
                if link_lower in (target_stem, target_path_no_ext):
                    title = _extract_title(content, rel)
                    results.append({"path": rel, "title": title})
                    break

        return results

    @protected.get("/vault/graph")
    async def vault_graph(
        max_files: int = Query(default=500, ge=1, le=2000, description="Max files to scan"),
    ) -> dict[str, Any]:
        """Return all notes as nodes and wikilink connections as edges."""
        files = await _scan_vault_md_files(max_files=max_files)
        truncated = len(files) >= max_files
        stem_lookup = _build_stem_lookup(files)
        known_paths = {rel for rel, _ in files}

        nodes: list[dict[str, str]] = []
        links: list[dict[str, str]] = []

        for rel, content in files:
            # Group = top-level directory (seeds, garden, actions) or "root"
            parts = rel.split("/", 1)
            group = parts[0] if len(parts) > 1 else "root"
            name = Path(rel).stem
            nodes.append({"id": rel, "name": name, "group": group})

            for m in WIKILINK_RE.finditer(content):
                link = m.group(1).strip()
                link_lower = link.lower()
                # Resolve link to a known path
                target = None
                if link in known_paths:
                    target = link
                elif link + ".md" in known_paths:
                    target = link + ".md"
                elif link_lower in stem_lookup:
                    target = stem_lookup[link_lower]
                if target and target != rel:
                    links.append({"source": rel, "target": target})

        return {"nodes": nodes, "links": links, "truncated": truncated}

    @protected.get("/vault/tags")
    async def vault_tags(
        max_files: int = Query(default=500, ge=1, le=2000, description="Max files to scan"),
    ) -> dict[str, Any]:
        """Extract all #tag occurrences from vault files."""
        files = await _scan_vault_md_files(max_files=max_files)
        truncated = len(files) >= max_files
        tag_map: dict[str, list[str]] = {}

        for rel, content in files:
            # Skip YAML frontmatter for tag extraction
            body = content
            if content.startswith("---\n"):
                end_idx = content.find("\n---\n", 4)
                if end_idx != -1:
                    body = content[end_idx + 5 :]

            found_tags: set[str] = set()
            for m in _TAG_RE.finditer(body):
                found_tags.add(m.group(1).lower())
            for tag in found_tags:
                tag_map.setdefault(tag, []).append(rel)

        return {"tags": tag_map, "truncated": truncated}

    # -- Config --------------------------------------------------------------

    @protected.get("/config")
    async def get_config() -> dict[str, Any]:
        """Return current runtime config (api_key excluded)."""
        snap = state.runtime_config.snapshot()
        snap["has_llm_api_key"] = bool(state.runtime_config.llm_api_key)
        snap["index_available"] = state.retriever.index_available
        return snap

    @protected.patch("/config")
    async def update_config(update: ConfigUpdate) -> dict[str, Any]:
        """Update runtime config. Only provided fields are changed."""
        changes: dict[str, Any] = {
            field: getattr(update, field)
            for field in update.model_fields_set
            if field != "safe_mode" or update.safe_mode is not None
        }
        if not changes:
            snap = state.runtime_config.snapshot()
            snap["has_llm_api_key"] = bool(state.runtime_config.llm_api_key)
            snap["index_available"] = state.retriever.index_available
            return snap
        try:
            state.runtime_config.update(**changes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        snap = state.runtime_config.snapshot()
        snap["has_llm_api_key"] = bool(state.runtime_config.llm_api_key)
        snap["index_available"] = state.retriever.index_available
        return snap

    @protected.post("/chat")
    async def chat(body: ChatMessage) -> dict[str, str]:
        """Vault-aware conversational chat with plugin tool use."""
        if state.chat_bridge is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")
        try:
            response = await state.chat_bridge.chat(
                message=body.message,
                history=body.history,
                context_paths=body.context_paths,
            )
            return {"response": response}
        except Exception as exc:
            logger.exception("chat_failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @protected.get("/sync-backends")
    async def list_sync_backends() -> list[str]:
        """Return names of registered sync backends."""
        return state.sync_manager.list_backends()

    parent = APIRouter()
    parent.include_router(public)
    parent.include_router(protected)
    return parent
