"""Integration test: dynamic-ontology end-to-end against real ~/.claude memory.

Bypasses the plugin's HTTP wrapping and drives ``IngestCompiler.compile_batch``
directly so we can verify on a real LLM that the new compile prompt + entity
stub creation + maturity-folder writes hang together. Runs against ollama
qwen3:14b (validated reasoning suppression in PR A).

Manual run only — not collected by pytest. From the worktree:

    uv run python scripts/import_memory_test.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from bsage.core.events import Event, EventBus, EventType
from bsage.garden.community import detect_communities
from bsage.garden.graph_extractor import GraphExtractor
from bsage.garden.ingest_compiler import (
    BatchItem,
    IngestCompiler,
    derive_batch_char_budget,
)
from bsage.garden.vault import Vault
from bsage.garden.writer import GardenWriter

MEMORY_DIR = Path("/Users/blasin/.claude/projects/-Users-blasin/memory")
VAULT_ROOT = Path("/tmp/bsage-memory-import-test")
MODEL = "ollama/qwen3:14b"
API_BASE = "http://localhost:11434"


def _build_batch_items(memory_dir: Path, *, limit: int | None = None) -> list[BatchItem]:
    items: list[BatchItem] = []
    paths = sorted(memory_dir.glob("*.md"))
    if limit is not None:
        paths = paths[:limit]
    for md_path in paths:
        content = md_path.read_text(encoding="utf-8")
        items.append(
            BatchItem(
                label=md_path.name,
                content=(
                    f"# Memory file: {md_path.name}\n\n"
                    f"Title hint: {md_path.stem}\n\n"
                    f"---\n\n"
                    f"{content}"
                ),
            )
        )
    return items


async def main() -> None:
    if VAULT_ROOT.exists():
        shutil.rmtree(VAULT_ROOT)
    VAULT_ROOT.mkdir()
    vault = Vault(VAULT_ROOT)
    vault.ensure_dirs()

    # Direct LlmClient adapter — bypasses BSage's LiteLLMClient so we
    # can hand qwen3 a generous per-attempt timeout (default is too
    # tight for a 14B model on a consumer Mac). 5 retries × 300s gives
    # the model enough time to walk through 30+ chunks without the
    # FallbackChain bailing on a transient slow-down.
    from bsvibe_llm import LlmClient, LlmSettings, RunAuditMetadata

    class _DirectLlm:
        def __init__(self) -> None:
            settings = LlmSettings(
                bsgateway_url="",
                model=MODEL,
                retry_max_attempts=5,
                retry_base_delay_s=2.0,
            )
            self._client = LlmClient(settings=settings)

        async def chat(
            self,
            system: str,
            messages: list,
            tools=None,
            tool_handler=None,
            max_rounds: int = 10,
            suppress_reasoning: bool = False,
        ) -> str:
            full = [{"role": "system", "content": system}, *messages]
            result = await self._client.complete(
                messages=full,
                metadata=RunAuditMetadata(tenant_id="test", run_id="memory-import"),
                direct=True,
                timeout_s=300.0,
                extra={"api_base": API_BASE},
                suppress_reasoning=suppress_reasoning,
            )
            return result.text

    llm = _DirectLlm()

    # Live progress: subscribe to compile_batch chunk events so the
    # terminal shows what stage we're in (qwen3:14b on consumer Mac
    # can take ~45-90s per chunk; without progress logs the run looks
    # frozen).
    event_bus = EventBus()
    bus_state = {"start_at": None, "chunk_started_at": None}

    class _ProgressLogger:
        async def on_event(self, event: Event) -> None:
            etype = event.event_type
            payload = event.payload
            now = time.monotonic()
            if etype is EventType.INGEST_COMPILE_BATCH_START:
                bus_state["start_at"] = now
                print(
                    f"[bus] BATCH_START items={payload.get('item_count')} "
                    f"chunks={payload.get('chunk_count')}",
                    flush=True,
                )
            elif etype is EventType.INGEST_COMPILE_BATCH_CHUNK_START:
                bus_state["chunk_started_at"] = now
                print(
                    f"[bus] CHUNK_START "
                    f"{payload.get('chunk_index') + 1}/{payload.get('chunk_count')} "
                    f"size={payload.get('chunk_size')}",
                    flush=True,
                )
            elif etype is EventType.INGEST_COMPILE_BATCH_CHUNK_DONE:
                started = bus_state.get("chunk_started_at") or now
                print(
                    f"[bus] CHUNK_DONE  "
                    f"{payload.get('chunk_index') + 1}/{payload.get('chunk_count')} "
                    f"created={payload.get('notes_created')} "
                    f"updated={payload.get('notes_updated')} "
                    f"({now - started:.1f}s)",
                    flush=True,
                )
            elif etype is EventType.INGEST_COMPILE_BATCH_CHUNK_FAILED:
                started = bus_state.get("chunk_started_at") or now
                print(
                    f"[bus] CHUNK_FAILED "
                    f"{payload.get('chunk_index') + 1}/{payload.get('chunk_count')} "
                    f"({now - started:.1f}s)",
                    flush=True,
                )
            elif etype is EventType.INGEST_COMPILE_BATCH_COMPLETE:
                started = bus_state.get("start_at") or now
                print(
                    f"[bus] BATCH_COMPLETE "
                    f"created={payload.get('notes_created')} "
                    f"updated={payload.get('notes_updated')} "
                    f"llm_calls={payload.get('llm_calls')} "
                    f"({now - started:.1f}s)",
                    flush=True,
                )

    event_bus.subscribe(_ProgressLogger())

    writer = GardenWriter(vault)

    import os

    limit_env = os.environ.get("MEMORY_TEST_LIMIT")
    limit = int(limit_env) if limit_env else None
    batch_items = _build_batch_items(MEMORY_DIR, limit=limit)
    print(f"Loaded {len(batch_items)} markdown files from {MEMORY_DIR}")

    budget = await derive_batch_char_budget(MODEL, API_BASE)
    print(f"Derived char budget: {budget}")

    compiler = IngestCompiler(
        garden_writer=writer,
        llm_client=llm,
        retriever=None,
        event_bus=event_bus,
        max_updates=20,
        batch_char_budget=budget,
    )

    started = time.monotonic()
    result = await compiler.compile_batch(items=batch_items, seed_source="memory-test")
    elapsed = time.monotonic() - started

    print("\n=== Compile result ===")
    print(f"elapsed: {elapsed:.1f}s")
    print(f"llm_calls: {result.llm_calls}")
    print(f"notes_created: {result.notes_created}")
    print(f"notes_updated: {result.notes_updated}")
    print(f"actions_taken: {len(result.actions_taken)}")

    print("\n=== Tags emitted ===")
    tag_freq: dict[str, int] = {}
    for action in result.actions_taken:
        for tag in action.tags:
            tag_freq[tag] = tag_freq.get(tag, 0) + 1
    for tag, count in sorted(tag_freq.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {count:>2}  {tag}")
    print(f"  (total unique tags: {len(tag_freq)})")
    kind_tags = {"idea", "fact", "insight", "project", "task"}
    leaked = sorted(set(tag_freq) & kind_tags)
    if leaked:
        print(f"  WARNING: kind-tag blocklist leaked through: {leaked}")
    else:
        print("  OK: no kind tags leaked.")

    print("\n=== Entities extracted ===")
    entity_freq: dict[str, int] = {}
    for action in result.actions_taken:
        for entity in action.entities:
            entity_freq[entity] = entity_freq.get(entity, 0) + 1
    for entity, count in sorted(entity_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:25]:
        print(f"  {count:>2}  {entity}")
    print(f"  (total unique entities: {len(entity_freq)})")

    print("\n=== Vault layout ===")
    for stage in ("seedling", "budding", "evergreen", "entities"):
        d = VAULT_ROOT / "garden" / stage
        if d.is_dir():
            count = sum(1 for _ in d.rglob("*.md"))
            print(f"  garden/{stage}: {count} files")
    legacy_count = 0
    for legacy in ("ideas", "insights", "projects", "people", "events", "tasks"):
        d = VAULT_ROOT / legacy
        if d.is_dir():
            legacy_count += sum(1 for _ in d.rglob("*.md"))
    print(f"  (legacy entity-type folders: {legacy_count} files — expect 0)")

    print("\n=== Sample entity stubs ===")
    entities_dir = VAULT_ROOT / "garden" / "entities"
    auto_stubs = list(entities_dir.glob("*.md")) if entities_dir.is_dir() else []
    print(f"  {len(auto_stubs)} entity stubs created")
    for stub in auto_stubs[:5]:
        body = stub.read_text(encoding="utf-8")
        title_line = next(
            (line for line in body.splitlines() if line.startswith("# ")),
            "(no title)",
        )
        print(f"  - {stub.name}: {title_line.lstrip('# ')}")

    print("\n=== Graph + communities ===")
    extractor = GraphExtractor()
    nodes_total = 0
    rels_total = 0
    import networkx as nx

    graph = nx.MultiDiGraph()
    seen_node_ids: set[str] = set()
    for md_path in (VAULT_ROOT / "garden").rglob("*.md"):
        rel = str(md_path.relative_to(VAULT_ROOT))
        content = md_path.read_text(encoding="utf-8")
        entities, relationships = extractor.extract_from_note(rel, content)
        nodes_total += len(entities)
        rels_total += len(relationships)
        for e in entities:
            if e.id not in seen_node_ids:
                graph.add_node(e.id, name=e.name, source_path=e.source_path)
                seen_node_ids.add(e.id)
        for r in relationships:
            graph.add_edge(r.source_id, r.target_id, rel_type=r.rel_type)
    print(f"  extracted entities: {nodes_total}")
    print(f"  extracted relationships: {rels_total}")

    communities = detect_communities(graph, min_size=2)
    print(f"  communities (size >= 2): {len(communities)}")
    for c in communities[:10]:
        print(f"    [{c.id}] {c.label}  size={c.size}  cohesion={c.cohesion:.2f}")

    print("\n=== Verdict ===")
    success = []
    if not legacy_count:
        success.append("PASS: no legacy folders written")
    else:
        success.append(f"FAIL: {legacy_count} files in legacy folders")
    if len(auto_stubs) > 0:
        success.append(f"PASS: {len(auto_stubs)} entity stubs auto-created")
    else:
        success.append("FAIL: no entity stubs")
    if len(communities) >= 2:
        success.append(f"PASS: {len(communities)} emergent communities (target ≥ 2)")
    else:
        success.append(f"FAIL: only {len(communities)} community (target ≥ 2)")
    if not leaked:
        success.append("PASS: kind-tag blocklist held")
    for line in success:
        print(f"  {line}")

    summary = {
        "memory_files": len(batch_items),
        "elapsed_s": round(elapsed, 1),
        "llm_calls": result.llm_calls,
        "notes_created": result.notes_created,
        "actions_taken": len(result.actions_taken),
        "unique_tags": len(tag_freq),
        "kind_tag_leaks": leaked,
        "unique_entities": len(entity_freq),
        "auto_stubs": len(auto_stubs),
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "communities": len(communities),
        "vault_path": str(VAULT_ROOT),
    }
    summary_path = VAULT_ROOT / "_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
