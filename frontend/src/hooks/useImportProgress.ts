import { useEffect, useMemo, useState } from "react";
import type { WSEvent } from "../api/types";
import { useEvents } from "../contexts/EventsContext";

/** Live state of an in-progress (or just-finished) ingest_compile_batch run.
 *
 * Derived from the four ``INGEST_COMPILE_BATCH_*`` events the backend
 * emits per chunk (see ``bsage/garden/ingest_compiler.py`` ~line 240).
 * Identification is by ``correlation_id`` so concurrent imports — should
 * the user trigger one while another is running — stay separated.
 */
export interface ImportProgress {
  correlationId: string;
  source: string;
  itemCount: number;
  chunkCount: number;
  chunksDone: number;
  chunksFailed: number;
  notesCreated: number;
  notesUpdated: number;
  /** ``"running"`` while between BATCH_START and BATCH_COMPLETE; ``"done"``
   * once BATCH_COMPLETE has landed. The latter sticks around for a few
   * seconds so the UI can show a final state before dismissing. */
  status: "running" | "done";
  /** Timestamp (Date.now) of the BATCH_START — used to drive elapsed
   * counters in the UI without storing per-tick state here. */
  startedAt: number;
  /** Timestamp of BATCH_COMPLETE if present, else null. */
  completedAt: number | null;
}

const INGEST_PREFIX = "ingest_compile_batch_";
const INGEST_TYPES = new Set([
  "ingest_compile_batch_start",
  "ingest_compile_batch_chunk_start",
  "ingest_compile_batch_chunk_done",
  "ingest_compile_batch_chunk_failed",
  "ingest_compile_batch_complete",
]);

/** Returns every active or recently-finished ingest run, keyed by
 * correlation_id. ``ImportProgressBar`` calls this once and renders a row
 * per entry; the modal version calls ``useLatestImportProgress`` for the
 * "the import I just kicked off" case.
 */
export function useImportProgresses(): Map<string, ImportProgress> {
  const events = useEvents();
  return useMemo(() => derive(events), [events]);
}

/** Returns the most recently-started import — i.e. the one the modal that
 * just clicked Run is interested in. ``null`` until a BATCH_START arrives. */
export function useLatestImportProgress(): ImportProgress | null {
  const all = useImportProgresses();
  // Map preserves insertion order; the last value is the most recent
  // BATCH_START we saw.
  let latest: ImportProgress | null = null;
  for (const v of all.values()) latest = v;
  return latest;
}

/** Drop the entry for an import that has finished and is older than
 * ``ttlMs``. The return value is the cleaned map; consumers that want
 * auto-dismiss behaviour can wrap this around ``useImportProgresses``. */
export function useActiveImportProgresses(ttlMs = 5_000): Map<string, ImportProgress> {
  const all = useImportProgresses();
  // Track ``now`` as state so the useMemo predicate stays pure. The
  // setInterval callback is a side-effect handler, not render code, so
  // calling Date.now() inside it is fine.
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  return useMemo(() => {
    const out = new Map<string, ImportProgress>();
    for (const [k, v] of all) {
      if (v.status === "done" && v.completedAt && now - v.completedAt > ttlMs) {
        // Drop unless there were failures — in that case keep it sticky
        // so the user notices the partial completion.
        if (v.chunksFailed === 0) continue;
      }
      out.set(k, v);
    }
    return out;
  }, [all, ttlMs, now]);
}

function derive(events: WSEvent[]): Map<string, ImportProgress> {
  const byId = new Map<string, ImportProgress>();
  for (const ev of events) {
    if (!INGEST_TYPES.has(ev.event_type)) continue;
    if (!ev.event_type.startsWith(INGEST_PREFIX)) continue;

    const id = ev.correlation_id;
    let entry = byId.get(id);
    const payload = ev.payload || {};

    if (ev.event_type === "ingest_compile_batch_start") {
      // Fallback ``0`` keeps the derive() function pure — calling
      // Date.now() here would trip react-hooks/purity since derive runs
      // inside a render-time useMemo. The server always sets timestamp,
      // so the ``|| 0`` branch is effectively dead code.
      entry = {
        correlationId: id,
        source: stringField(payload, "source"),
        itemCount: numberField(payload, "item_count"),
        chunkCount: numberField(payload, "chunk_count"),
        chunksDone: 0,
        chunksFailed: 0,
        notesCreated: 0,
        notesUpdated: 0,
        status: "running",
        startedAt: Date.parse(ev.timestamp) || 0,
        completedAt: null,
      };
      byId.set(id, entry);
      continue;
    }
    if (!entry) continue;

    if (ev.event_type === "ingest_compile_batch_chunk_done") {
      entry.chunksDone += 1;
      entry.notesCreated += numberField(payload, "notes_created");
      entry.notesUpdated += numberField(payload, "notes_updated");
    } else if (ev.event_type === "ingest_compile_batch_chunk_failed") {
      entry.chunksFailed += 1;
    } else if (ev.event_type === "ingest_compile_batch_complete") {
      entry.status = "done";
      entry.completedAt = Date.parse(ev.timestamp) || 0;
      // Trust the COMPLETE payload's totals over our running sum so a
      // missed CHUNK_DONE event (network blip, late subscriber) doesn't
      // leave a stale count on screen.
      const finalCreated = numberField(payload, "notes_created");
      const finalUpdated = numberField(payload, "notes_updated");
      if (finalCreated > 0 || finalUpdated > 0) {
        entry.notesCreated = finalCreated;
        entry.notesUpdated = finalUpdated;
      }
    }
  }
  return byId;
}

function numberField(payload: Record<string, unknown>, key: string): number {
  const v = payload[key];
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function stringField(payload: Record<string, unknown>, key: string): string {
  const v = payload[key];
  return typeof v === "string" ? v : "";
}
