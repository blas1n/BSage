"""HTTP route handlers for the BSage Gateway."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from bsage.core.exceptions import VaultPathError
from bsage.core.patterns import WIKILINK_RE
from bsage.core.plugin_loader import PluginMeta
from bsage.core.skill_loader import SkillMeta
from bsage.garden.audit_outbox import safe_emit as _audit_safe_emit
from bsage.garden.markdown_utils import extract_frontmatter, extract_title
from bsage.garden.writer import GardenNote
from bsage.gateway.authz import require_bsage_permission
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


class NotifyRequest(BaseModel):
    """Request body for POST /api/notify."""

    message: str = Field(..., min_length=1)
    channel: str | None = None
    metadata: dict[str, Any] = {}


class NotifyResponse(BaseModel):
    """Response for POST /api/notify."""

    sent: bool
    channel: str | None = None
    error: str | None = None


class SearchResultItem(BaseModel):
    """A single search result."""

    title: str
    path: str
    content_preview: str
    relevance_score: float
    tags: list[str]


class SearchResponse(BaseModel):
    """Response for GET /api/knowledge/search."""

    results: list[SearchResultItem]


class CreateEntryRequest(BaseModel):
    """Request body for POST /api/knowledge/entries."""

    title: str
    content: str
    note_type: str = "idea"
    tags: list[str] = []
    links: list[str] = []
    source: str = "api"
    metadata: dict[str, Any] = {}


class CreateEntryResponse(BaseModel):
    """Response for POST /api/knowledge/entries."""

    id: str
    path: str
    created_at: str


class CreateDecisionRequest(BaseModel):
    """Request body for POST /api/knowledge/decisions."""

    title: str
    decision: str
    reasoning: str
    note_type: str = "insight"
    alternatives: list[str] = []
    context: str = ""
    tags: list[str] = []
    source: str = "api"


def _principal_tenant(principal: Any) -> str | None:
    """Extract ``active_tenant_id`` from a principal in a way that works for
    both real ``bsvibe_authz.User`` and the mock principals legacy tests put
    onto ``state.get_current_user``."""
    if principal is None:
        return None
    tid = getattr(principal, "active_tenant_id", None)
    if isinstance(tid, str) and tid:
        return tid
    return None


def _frontmatter_tenant(content: str) -> str | None:
    fm = extract_frontmatter(content) if content.startswith("---\n") else {}
    tid = fm.get("tenant_id") if isinstance(fm, dict) else None
    return tid if isinstance(tid, str) and tid else None


def _tenant_can_read(content: str, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return True
    return _frontmatter_tenant(content) == tenant_id


def _audit_actor_from_principal(principal: Any) -> Any:
    """Build an :class:`AuditActor` from a principal, falling back to system.

    Imported lazily so test fixtures that mock the routes module without
    touching audit infra do not pay an import cost.
    """
    from bsvibe_audit import AuditActor

    if principal is None:
        return AuditActor(type="system", id="bsage")
    pid = getattr(principal, "id", None) or getattr(principal, "sub", None) or "anonymous"
    email = getattr(principal, "email", None)
    return AuditActor(type="user", id=str(pid), email=email if isinstance(email, str) else None)


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
        "trigger": meta.trigger,
        "entry_type": "plugin" if hasattr(meta, "_execute_fn") else "skill",
        "input_schema": getattr(meta, "input_schema", None),
        "mcp_exposed": bool(getattr(meta, "mcp_exposed", False)),
    }


async def _read_json_body(request: Request) -> dict[str, Any]:
    """Decode an optional JSON request body, returning ``{}`` on absence/invalid."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def create_routes(state: AppState) -> APIRouter:
    """Create API routes with injected application state.

    Routes are split into *public* (health, webhooks) and *protected*
    (everything else).  The protected router applies ``state.get_current_user``
    as a router-level dependency so individual handlers don't need to declare it.

    Phase 0 P0.5 — ``state.get_current_user`` returns a ``bsvibe_authz.User``
    (either a real human or a service principal). Handlers that need to stamp
    ``tenant_id`` onto written notes pull the principal via
    ``Depends(state.get_current_user)`` directly. Permission enforcement is
    layered on top via :func:`bsage.gateway.authz.require_bsage_permission`,
    which routes the same principal through OpenFGA.
    """
    public = APIRouter(prefix="/api")
    protected = APIRouter(
        prefix="/api",
        dependencies=[Depends(state.get_current_user)],
    )

    # Per-route permission helpers — bind the BSage permission strings up-front
    # so route definitions stay short. These are constructed once per app
    # creation, NOT once per request.
    #
    # ``principal_dep=state.get_current_user`` makes the permission factory
    # share the same principal source as the router-level auth dep — tests
    # that override ``state.get_current_user`` automatically flow through to
    # the permission check too.
    _principal = state.get_current_user
    knowledge_read = require_bsage_permission("bsage.knowledge.read", principal_dep=_principal)
    knowledge_write = require_bsage_permission("bsage.knowledge.write", principal_dep=_principal)
    decisions_write = require_bsage_permission("bsage.decisions.write", principal_dep=_principal)
    vault_read = require_bsage_permission("bsage.vault.read", principal_dep=_principal)
    notify_write = require_bsage_permission("bsage.notify.write", principal_dep=_principal)
    config_read = require_bsage_permission("bsage.config.read", principal_dep=_principal)
    config_write = require_bsage_permission("bsage.config.write", principal_dep=_principal)
    plugins_read = require_bsage_permission("bsage.plugins.read", principal_dep=_principal)
    plugins_execute = require_bsage_permission("bsage.plugins.execute", principal_dep=_principal)
    chat_write = require_bsage_permission("bsage.chat.write", principal_dep=_principal)

    async def _tenant_graph_snapshot(tenant_id: str | None) -> Any:
        graph = await state.graph_store.to_networkx_snapshot()
        if tenant_id is None:
            return graph

        visible_paths = {
            rel
            for rel, _ in await _scan_vault_md_files(
                max_files=0,
                tenant_id=tenant_id,
            )
        }
        filtered = graph.copy()
        for node, data in list(filtered.nodes(data=True)):
            source_path = data.get("source_path")
            if isinstance(source_path, str) and source_path not in visible_paths:
                filtered.remove_node(node)

        for node, data in list(filtered.nodes(data=True)):
            source_path = data.get("source_path")
            if not isinstance(source_path, str) and filtered.degree(node) == 0:
                filtered.remove_node(node)

        return filtered

    @public.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @public.get("/auth/callback")
    async def auth_callback(request: Request) -> HTMLResponse:
        """Handle OAuth callback from external auth provider.

        Returns an HTML page that extracts tokens from both query params
        and URL hash fragment (some OAuth providers send tokens in the hash),
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
    async def list_plugins(_perm: None = Depends(plugins_read)) -> list[dict[str, Any]]:
        """List all loaded Plugins (code-based)."""
        registry = await state.plugin_loader.load_all()
        configured = state.credential_store.list_services()
        disabled = state.runtime_config.disabled_entries
        return [
            _meta_to_dict(meta, state.danger_map, configured, disabled)
            for meta in registry.values()
        ]

    @protected.get("/skills")
    async def list_skills(_perm: None = Depends(plugins_read)) -> list[dict[str, Any]]:
        """List all loaded Skills (LLM-based)."""
        registry = await state.skill_loader.load_all()
        configured = state.credential_store.list_services()
        disabled = state.runtime_config.disabled_entries
        return [
            _meta_to_dict(meta, state.danger_map, configured, disabled)
            for meta in registry.values()
        ]

    @protected.post("/plugins/{name}/run")
    async def run_plugin(
        name: str,
        request: Request,
        _perm: None = Depends(plugins_execute),
    ) -> dict[str, Any]:
        """Trigger a plugin directly with the request body as input_data.

        Direct invocation path — the plugin's ``execute()`` receives the
        JSON body as ``context.input_data``. Bypasses the inbound-webhook
        refine/compile pipeline (use ``POST /webhooks/{name}`` for that).
        """
        try:
            state.plugin_loader.get(name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if name in state.runtime_config.disabled_entries:
            raise HTTPException(status_code=403, detail=f"'{name}' is disabled")

        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        body = await _read_json_body(request)
        try:
            result = await state.agent_loop.run_entry_direct(name, body)
            return {"plugin": name, "result": result}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
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
    async def run_entry(
        name: str,
        request: Request,
        _perm: None = Depends(plugins_execute),
    ) -> dict[str, Any]:
        """Run a plugin or skill directly with the request body as input_data.

        Direct invocation — the entry's ``execute()`` sees the JSON body
        as ``context.input_data``. Use this for explicit user-triggered
        runs (Imports & Exports UI, ``bsage run`` CLI, MCP plugin bridge).
        """
        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        try:
            state.agent_loop.get_entry(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"'{name}' not found in registry") from None

        if name in state.runtime_config.disabled_entries:
            raise HTTPException(status_code=403, detail=f"'{name}' is disabled")

        body = await _read_json_body(request)
        try:
            result = await state.agent_loop.run_entry_direct(name, body)
            return {"name": name, "result": result}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("run_entry_failed", name=name)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # -- Credential setup endpoints ------------------------------------------

    @protected.get("/entries/{name}/credentials/fields")
    async def credential_fields(name: str, _perm: None = Depends(plugins_read)) -> dict[str, Any]:
        """Return credential field definitions for a plugin or skill."""
        meta = _find_entry(state, name)

        if isinstance(meta, PluginMeta):
            return {"name": name, "fields": meta.credentials or []}

        # SkillMeta
        if isinstance(meta.credentials, dict):
            return {"name": name, "fields": meta.credentials.get("fields", [])}

        return {"name": name, "fields": []}

    @protected.post("/entries/{name}/credentials")
    async def store_credentials(
        name: str, body: CredentialStoreRequest, _perm: None = Depends(config_write)
    ) -> dict[str, Any]:
        """Store credentials for a plugin or skill via the GUI."""
        _find_entry(state, name)  # 404 if not found

        await state.credential_store.store(name, body.credentials)
        logger.info("credentials_stored_via_gui", name=name)
        if state.agent_loop:
            state.runtime_config.rebuild_enabled(state.agent_loop._registry, state.credential_store)
        return {"status": "ok", "name": name}

    # -- Enable/Disable toggle -----------------------------------------------

    @protected.post("/entries/{name}/toggle")
    async def toggle_entry(name: str, _perm: None = Depends(config_write)) -> dict[str, Any]:
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
    async def list_actions(
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> list[str]:
        notes = await state.vault.read_notes("actions")
        tenant_id = _principal_tenant(principal)
        visible: list[str] = []
        for path in notes:
            with contextlib.suppress(OSError):
                content = await state.vault.read_note_content(path)
                if _tenant_can_read(content, tenant_id):
                    visible.append(str(path.name))
        return visible

    @protected.get("/vault/tree")
    async def vault_tree(
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> list[dict[str, Any]]:
        """Return the vault directory tree structure."""
        vault_root = state.vault.root
        tenant_id = _principal_tenant(principal)

        def _walk() -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for dirpath, dirnames, filenames in os.walk(vault_root):
                # Exclude hidden directories
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                rel = os.path.relpath(dirpath, vault_root)
                if rel == ".":
                    rel = ""
                visible_files: list[str] = []
                for filename in sorted(filenames):
                    if not filename.endswith(".md"):
                        continue
                    full = Path(dirpath) / filename
                    try:
                        content = full.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    if _tenant_can_read(content, tenant_id):
                        visible_files.append(filename)
                result.append(
                    {
                        "path": rel,
                        "dirs": list(dirnames),
                        "files": visible_files,
                    }
                )
            return result

        return await asyncio.to_thread(_walk)

    @protected.get("/vault/file")
    async def vault_file(
        path: str = Query(..., description="Relative path within the vault"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Return the content of a vault file."""
        try:
            resolved = state.vault.resolve_path(path)
        except VaultPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            # ``Path.resolve()`` raises ``ValueError`` on embedded null
            # bytes — surface as a 400 traversal-style rejection rather
            # than a 500 so attackers don't get to crash the endpoint.
            raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

        if not resolved.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        try:
            content = await state.vault.read_note_content(resolved)
        except OSError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not _tenant_can_read(content, _principal_tenant(principal)):
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        return {"path": path, "content": content}

    # -- Vault search / backlinks / graph / tags -----------------------------

    async def _scan_vault_md_files(
        max_files: int = 0, tenant_id: str | None = None
    ) -> list[tuple[str, str]]:
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
                    rel = full.relative_to(vault_root).as_posix()
                    try:
                        content = full.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    if not _tenant_can_read(content, tenant_id):
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

    def _canonicalize_link(text: str) -> str:
        """Collapse a wikilink target or filename stem to a comparison key.

        Strips every non-alphanumeric character and lowercases. Makes
        "프로젝트: 온톨로지 구축" match "프로젝트-온톨로지-구축" — the same
        identity rendered as prose vs as a slugified filename.
        """
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def _build_alias_lookup(files: list[tuple[str, str]]) -> dict[str, str]:
        """Map canonical stem AND frontmatter title → relative path."""
        lookup: dict[str, str] = {}
        for rel, content in files:
            stem_key = _canonicalize_link(Path(rel).stem)
            if stem_key and stem_key not in lookup:
                lookup[stem_key] = rel
            fm = extract_frontmatter(content) if content.startswith("---\n") else {}
            title = fm.get("title") if isinstance(fm, dict) else None
            if isinstance(title, str):
                title_key = _canonicalize_link(title)
                if title_key and title_key not in lookup:
                    lookup[title_key] = rel
        return lookup

    @protected.get("/vault/search")
    async def vault_search(
        q: str = Query(..., min_length=1, description="Search query"),
        max_files: int = Query(default=500, ge=1, le=2000, description="Max files to scan"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> list[dict[str, Any]]:
        """Full-text search across vault .md files (case-insensitive, max 50 results)."""
        files = await _scan_vault_md_files(
            max_files=max_files,
            tenant_id=_principal_tenant(principal),
        )
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
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> list[dict[str, Any]]:
        """Find notes containing [[wikilink]] references to the given path."""
        files = await _scan_vault_md_files(tenant_id=_principal_tenant(principal))
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
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Return all notes as nodes and wikilink connections as edges."""
        files = await _scan_vault_md_files(
            max_files=max_files,
            tenant_id=_principal_tenant(principal),
        )
        truncated = len(files) >= max_files
        stem_lookup = _build_stem_lookup(files)
        alias_lookup = _build_alias_lookup(files)
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
                else:
                    canon = _canonicalize_link(link)
                    if canon and canon in alias_lookup:
                        target = alias_lookup[canon]
                if target and target != rel:
                    links.append({"source": rel, "target": target})

        return {"nodes": nodes, "links": links, "truncated": truncated}

    @protected.get("/vault/communities")
    async def vault_communities(
        algorithm: str = Query(default="louvain", description="louvain or label_propagation"),
        min_size: int = Query(default=2, ge=2, le=100, description="Minimum community size"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Detect communities in the knowledge graph and return them."""
        from bsage.garden.community import (
            communities_to_graph_data,
            detect_communities,
        )

        graph = await _tenant_graph_snapshot(_principal_tenant(principal))
        communities = detect_communities(graph, algorithm=algorithm, min_size=min_size)
        # Remap entity UUIDs → vault file paths so members match /vault/graph node IDs
        data = communities_to_graph_data(communities)
        for comm in data:
            remapped: list[str] = []
            for mid in comm["members"]:
                if graph.has_node(mid):
                    src = graph.nodes[mid].get("source_path")
                    remapped.append(src or mid)
                else:
                    remapped.append(mid)
            comm["members"] = remapped
        return {
            "communities": data,
            "algorithm": algorithm,
            "total": len(communities),
        }

    @protected.get("/vault/analytics")
    async def vault_analytics(
        top_k: int = Query(default=20, ge=1, le=100),
        include_betweenness: bool = Query(default=False),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Return graph analytics: centrality, stats, god nodes, gaps."""
        from dataclasses import asdict

        from bsage.garden.analytics import (
            compute_centrality,
            compute_graph_stats,
            find_god_nodes,
            find_knowledge_gaps,
        )

        graph = await _tenant_graph_snapshot(_principal_tenant(principal))

        stats = compute_graph_stats(graph)
        top_nodes = compute_centrality(graph, top_k=top_k, include_betweenness=include_betweenness)
        god_nodes = find_god_nodes(graph, top_k=10)
        gaps = find_knowledge_gaps(graph)

        return {
            "stats": asdict(stats),
            "centrality": [asdict(n) for n in top_nodes],
            "god_nodes": [asdict(n) for n in god_nodes],
            "gaps": gaps,
        }

    @protected.get("/vault/tags")
    async def vault_tags(
        max_files: int = Query(default=500, ge=1, le=2000, description="Max files to scan"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Extract all #tag occurrences from vault files."""
        files = await _scan_vault_md_files(
            max_files=max_files,
            tenant_id=_principal_tenant(principal),
        )
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

    # -- Knowledge search ----------------------------------------------------

    @protected.get("/knowledge/search", response_model=SearchResponse)
    async def knowledge_search(
        q: str = Query(..., min_length=1, description="Search query"),
        limit: int = Query(default=5, ge=1, le=50, description="Max results"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(knowledge_read),
    ) -> SearchResponse:
        """Semantic search over vault knowledge notes with full-text fallback."""
        results: list[SearchResultItem] = []

        # Try semantic search via vector store + embedder
        if state.vector_store is not None and state.embedder is not None and state.embedder.enabled:
            try:
                query_embedding = await state.embedder.embed(q)
                vector_results = await state.vector_store.search(query_embedding, top_k=limit)
                tenant_id = _principal_tenant(principal)
                all_notes = await _scan_vault_md_files(tenant_id=tenant_id)
                note_map = {rel: content for rel, content in all_notes}

                for path, score in vector_results:
                    content = note_map.get(path, "")
                    if not content:
                        continue
                    fm = extract_frontmatter(content)
                    title = extract_title(content) or Path(path).stem
                    note_tags = [str(t).lower() for t in fm.get("tags", []) or []]
                    body = content
                    if content.startswith("---\n"):
                        try:
                            end_idx = content.index("\n---\n", 4)
                            body = content[end_idx + 5 :].strip()
                        except ValueError:
                            pass
                    preview = body[:200].strip()
                    results.append(
                        SearchResultItem(
                            title=title,
                            path=path,
                            content_preview=preview,
                            relevance_score=round(score, 4),
                            tags=note_tags,
                        )
                    )
                return SearchResponse(results=results)
            except (RuntimeError, OSError, ValueError):
                logger.warning("vector_search_failed_fallback", exc_info=True)
                results = []

        # Full-text fallback
        all_notes = await _scan_vault_md_files(tenant_id=_principal_tenant(principal))
        query_lower = q.lower()

        scored: list[tuple[float, str, str]] = []
        for rel, content in all_notes:
            content_lower = content.lower()
            count = content_lower.count(query_lower)
            if count > 0:
                scored.append((count, rel, content))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored = scored[:limit]

        for count, rel, content in scored:
            fm = extract_frontmatter(content)
            title = extract_title(content) or Path(rel).stem
            note_tags = [str(t).lower() for t in fm.get("tags", []) or []]
            body = content
            if content.startswith("---\n"):
                try:
                    end_idx = content.index("\n---\n", 4)
                    body = content[end_idx + 5 :].strip()
                except ValueError:
                    pass
            preview = body[:200].strip()
            # Normalize count to 0-1 range (simple heuristic)
            score = min(count / 10.0, 1.0)
            results.append(
                SearchResultItem(
                    title=title,
                    path=rel,
                    content_preview=preview,
                    relevance_score=round(score, 4),
                    tags=note_tags,
                )
            )

        return SearchResponse(results=results)

    # -- Vault lint ----------------------------------------------------------

    @protected.post("/vault/lint")
    async def run_vault_lint(
        stale_days: int = Query(default=90, ge=1, description="Days threshold for stale check"),
        principal: Any = Depends(_principal),
        _perm: None = Depends(vault_read),
    ) -> dict[str, Any]:
        """Run a comprehensive vault health check."""
        from bsage.garden.vault_linter import VaultLinter

        linter = VaultLinter(
            vault=state.vault,
            garden_writer=state.garden_writer,
            graph_store=state.graph_store,
            ontology=state.ontology,
            stale_days=stale_days,
        )
        report = await linter.lint()
        tenant_id = _principal_tenant(principal)
        issues = []
        for issue in report.issues:
            if tenant_id is None:
                issues.append(issue)
                continue
            try:
                content = await state.vault.read_note_content(state.vault.resolve_path(issue.path))
            except Exception:
                continue
            if _tenant_can_read(content, tenant_id):
                issues.append(issue)
        return {
            "total_notes_scanned": report.total_notes_scanned,
            "issues_count": len(issues),
            "issues": [
                {
                    "check": i.check,
                    "severity": i.severity,
                    "path": i.path,
                    "description": i.description,
                }
                for i in issues
            ],
            "timestamp": report.timestamp,
        }

    # -- Knowledge catalog ---------------------------------------------------

    @protected.get("/knowledge/catalog")
    async def knowledge_catalog(
        principal: Any = Depends(_principal),
        _perm: None = Depends(knowledge_read),
    ) -> dict[str, Any]:
        """Return the auto-generated vault catalog grouped by note type."""
        summaries = await state.index_reader.get_all_summaries()
        tenant_id = _principal_tenant(principal)
        by_type: dict[str, list[dict[str, Any]]] = {}
        for s in summaries:
            if tenant_id is not None:
                visible = False
                with contextlib.suppress(Exception):
                    content = await state.vault.read_note_content(state.vault.resolve_path(s.path))
                    visible = _tenant_can_read(content, tenant_id)
                if not visible:
                    continue
            key = s.note_type or "uncategorized"
            by_type.setdefault(key, []).append(
                {
                    "title": s.title,
                    "path": s.path,
                    "tags": s.tags,
                    "captured_at": s.captured_at,
                }
            )
        return {"total": len(summaries), "categories": by_type}

    # -- Knowledge write -----------------------------------------------------

    @protected.post(
        "/knowledge/entries",
        response_model=CreateEntryResponse,
        status_code=201,
    )
    async def create_knowledge_entry(
        body: CreateEntryRequest,
        principal: Any = Depends(_principal),
        _perm: None = Depends(knowledge_write),
    ) -> CreateEntryResponse:
        """Create a new knowledge entry via GardenWriter."""
        # Build content with wikilinks appended
        content = body.content
        if body.links:
            wikilinks = " ".join(f"[[{link}]]" for link in body.links)
            content = f"{content}\n\n{wikilinks}"

        note = GardenNote(
            title=body.title,
            content=content,
            note_type=body.note_type,
            source=body.source,
            related=list(body.links),
            tags=list(body.tags),
            extra_fields=dict(body.metadata),
            tenant_id=_principal_tenant(principal),
        )

        try:
            written_path = await state.garden_writer.write_garden(note)
        except Exception as exc:
            logger.exception("knowledge_entry_write_failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        rel_path = str(written_path)
        with contextlib.suppress(ValueError, AttributeError):
            rel_path = str(written_path.relative_to(state.vault.root))

        now = datetime.now(tz=UTC).isoformat()
        note_id = Path(rel_path).stem

        # Phase Audit Batch 2 — sage.knowledge.entry_created. Failures are
        # swallowed by ``safe_emit`` so the sync-API contract (201 + body)
        # is preserved even when the audit outbox is offline.
        with contextlib.suppress(Exception):
            from bsvibe_audit import AuditResource
            from bsvibe_audit.events.sage import KnowledgeEntryCreated

            await _audit_safe_emit(
                getattr(state, "audit_outbox", None),
                KnowledgeEntryCreated(
                    actor=_audit_actor_from_principal(principal),
                    tenant_id=_principal_tenant(principal),
                    resource=AuditResource(type="knowledge_entry", id=note_id),
                    data={
                        "title": body.title,
                        "note_type": body.note_type,
                        "tags": list(body.tags),
                        "source": body.source,
                        "path": rel_path,
                    },
                ),
            )

        return CreateEntryResponse(id=note_id, path=rel_path, created_at=now)

    # -- Decision records ----------------------------------------------------

    @protected.post(
        "/knowledge/decisions",
        response_model=CreateEntryResponse,
        status_code=201,
    )
    async def create_decision_record(
        body: CreateDecisionRequest,
        principal: Any = Depends(_principal),
        _perm: None = Depends(decisions_write),
    ) -> CreateEntryResponse:
        """Create a structured decision record as an insight note."""
        # Build structured markdown content from template
        alt_lines = "\n".join(f"- {alt}" for alt in body.alternatives)
        content_parts = [
            "## Decision\n",
            body.decision,
            "\n\n## Reasoning\n",
            body.reasoning,
            "\n\n## Alternatives Considered\n",
            alt_lines if alt_lines else "_None._",
            "\n\n## Context\n",
            body.context if body.context else "_No additional context._",
        ]
        content = "".join(content_parts)

        note = GardenNote(
            title=body.title,
            content=content,
            note_type=body.note_type,
            source=body.source,
            tags=list(body.tags),
            extra_fields={"decision_record": True},
            tenant_id=_principal_tenant(principal),
        )

        try:
            written_path = await state.garden_writer.write_garden(note)
        except Exception as exc:
            logger.exception("decision_record_write_failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        rel_path = str(written_path)
        with contextlib.suppress(ValueError, AttributeError):
            rel_path = str(written_path.relative_to(state.vault.root))

        now = datetime.now(tz=UTC).isoformat()
        note_id = Path(rel_path).stem

        # Phase Audit Batch 2 — sage.decision.recorded. Same safety contract
        # as the entry route: emit failure must not change the 201 response.
        with contextlib.suppress(Exception):
            from bsvibe_audit import AuditResource
            from bsvibe_audit.events.sage import DecisionRecorded

            await _audit_safe_emit(
                getattr(state, "audit_outbox", None),
                DecisionRecorded(
                    actor=_audit_actor_from_principal(principal),
                    tenant_id=_principal_tenant(principal),
                    resource=AuditResource(type="decision", id=note_id),
                    data={
                        "title": body.title,
                        "decision": body.decision,
                        "alternatives": list(body.alternatives),
                        "tags": list(body.tags),
                        "source": body.source,
                        "path": rel_path,
                    },
                ),
            )

        return CreateEntryResponse(id=note_id, path=rel_path, created_at=now)

    # -- Notification ---------------------------------------------------------

    @protected.post("/notify", response_model=NotifyResponse)
    async def send_notification(
        body: NotifyRequest, _perm: None = Depends(notify_write)
    ) -> NotifyResponse:
        """Send a notification through BSage's multi-channel notification system.

        Used by BSNexus and other BSVibe services to send messages without
        managing channel SDKs directly.
        """
        from bsage.core.plugin_loader import PluginMeta
        from bsage.core.skill_context import SkillContext

        if state.agent_loop is None:
            raise HTTPException(status_code=503, detail="Gateway not initialized")

        registry = state.agent_loop._registry

        # Find the target plugin(s) with _notify_fn
        if body.channel is not None:
            # Route to specific channel
            meta = registry.get(body.channel)
            if meta is None:
                return NotifyResponse(
                    sent=False,
                    error=f"Channel '{body.channel}' not found in registry",
                )
            if not isinstance(meta, PluginMeta) or meta._notify_fn is None:
                return NotifyResponse(
                    sent=False,
                    error=f"Channel '{body.channel}' has no notify handler",
                )
            target_meta = meta
        else:
            # Auto-route: pick first plugin with a _notify_fn
            target_meta = None
            for meta in registry.values():
                if isinstance(meta, PluginMeta) and meta._notify_fn is not None:
                    target_meta = meta
                    break
            if target_meta is None:
                return NotifyResponse(
                    sent=False,
                    error="No notification channel available",
                )

        # Build a minimal context with the message + metadata
        input_data: dict[str, Any] = {"message": body.message}
        if body.metadata:
            input_data["metadata"] = body.metadata

        ctx = SkillContext(
            garden=state.garden_writer,
            llm=state.llm_client,
            config={},
            logger=structlog.get_logger("notify"),
            input_data=input_data,
        )

        try:
            await state.runner.run_notify(target_meta, ctx)
            return NotifyResponse(sent=True, channel=target_meta.name)
        except Exception as exc:
            logger.exception("notify_send_failed", channel=target_meta.name)
            return NotifyResponse(
                sent=False,
                channel=target_meta.name,
                error=str(exc),
            )

    # -- Config --------------------------------------------------------------

    @protected.get("/config")
    async def get_config(_perm: None = Depends(config_read)) -> dict[str, Any]:
        """Return current runtime config (api_key excluded)."""
        snap = state.runtime_config.snapshot()
        snap["has_llm_api_key"] = bool(state.runtime_config.llm_api_key)
        snap["index_available"] = state.retriever.index_available
        return snap

    @protected.patch("/config")
    async def update_config(
        update: ConfigUpdate, _perm: None = Depends(config_write)
    ) -> dict[str, Any]:
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

    @protected.post("/config/test-llm")
    async def test_llm(_perm: None = Depends(config_write)) -> dict[str, Any]:
        """Send a minimal ping to the configured LLM and report result.

        Does not modify any state. Uses current runtime_config (model +
        api_key + api_base). Returns latency, reply preview, or an error
        with a user-facing hint.
        """
        import time

        cfg = state.runtime_config
        if not cfg.llm_api_key:
            return {
                "ok": False,
                "error": "missing_api_key",
                "hint": "Save an API key first.",
            }
        if not cfg.llm_model:
            return {
                "ok": False,
                "error": "missing_model",
                "hint": "Set an LLM model first.",
            }

        start = time.perf_counter()
        try:
            reply = await state.llm_client.chat(
                system="Reply with exactly the word: pong",
                messages=[{"role": "user", "content": "ping"}],
            )
        except Exception as exc:
            logger.warning("llm_test_failed", error=str(exc))
            return {
                "ok": False,
                "error": type(exc).__name__,
                "detail": str(exc)[:300],
                "model": cfg.llm_model,
            }
        latency_ms = round((time.perf_counter() - start) * 1000)
        return {
            "ok": True,
            "model": cfg.llm_model,
            "latency_ms": latency_ms,
            "reply": reply[:200],
        }

    @protected.post("/chat")
    async def chat(body: ChatMessage, _perm: None = Depends(chat_write)) -> dict[str, str]:
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
    async def list_sync_backends(_perm: None = Depends(config_read)) -> list[str]:
        """Return names of registered sync backends."""
        return state.sync_manager.list_backends()

    # -- Generic file upload (Phase 2a) --------------------------------------

    _max_upload_bytes = 50 * 1024 * 1024  # 50 MB
    _upload_ttl_seconds = 3600  # 1 h — caller responsible for prompt consumption

    @protected.post("/uploads")
    async def upload_file(
        file: UploadFile = File(...),
        principal: Any = Depends(_principal),
    ) -> dict[str, str]:
        """Accept a single file and stash it in a tenant-scoped temp dir.

        Returns ``upload_id`` + absolute ``path``. Plugins read the file by
        passing ``upload_id`` (or ``path``) in their ``input_data`` payload
        when triggered via ``POST /api/run/{name}``.
        """
        tenant = _principal_tenant(principal) or "anonymous"
        upload_id = uuid.uuid4().hex

        raw_name = file.filename or "upload"
        safe_name = Path(raw_name).name  # strips any '..' / path components
        if not safe_name or safe_name in (".", ".."):
            safe_name = "upload"

        upload_root = state.vault.root.parent / "uploads" / tenant / upload_id
        upload_root.mkdir(parents=True, exist_ok=True)
        dest = upload_root / safe_name

        written = 0
        try:
            with dest.open("wb") as out:
                while True:
                    chunk = await file.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _max_upload_bytes:
                        out.close()
                        with contextlib.suppress(OSError):
                            dest.unlink()
                            upload_root.rmdir()
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds {_max_upload_bytes // (1024 * 1024)}MB limit",
                        )
                    out.write(chunk)
        finally:
            await file.close()

        expires_at = (datetime.now(tz=UTC) + timedelta(seconds=_upload_ttl_seconds)).isoformat()
        return {
            "upload_id": upload_id,
            "path": str(dest),
            "filename": safe_name,
            "expires_at": expires_at,
        }

    # Canonicalization routes (Handoff §15.1) live in their own module to
    # keep this file small. They register their own permission deps and
    # use ``state.canon_service`` directly.
    from bsage.gateway.canonicalization_routes import create_canonicalization_router

    canon_router = create_canonicalization_router(state)

    parent = APIRouter()
    parent.include_router(public)
    parent.include_router(protected)
    parent.include_router(canon_router)
    return parent
