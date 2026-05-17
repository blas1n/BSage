'use client';

import { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "@bsvibe/i18n";
import { api } from "../../api/client";
import { useEvents } from "../../contexts/EventsContext";

type EvidenceItem = Record<string, unknown> & {
  kind?: string;
  source?: string;
  payload?: Record<string, unknown>;
};

type ActionItem = {
  path: string;
  kind: string;
  status: string;
  params: Record<string, unknown>;
  stability_score: number | null;
  risk_reasons: EvidenceItem[];
  deterministic_evidence: EvidenceItem[];
  model_evidence: EvidenceItem[];
  human_evidence: EvidenceItem[];
  affected_paths: string[];
  source_proposal: string | null;
};

const SOURCE_STYLES: Record<string, string> = {
  // Source-aware styling per Handoff §13: deterministic / model / human
  // visually distinguished so model-derived text isn't confused with
  // deterministic system judgement.
  deterministic: "border-l-emerald-600 bg-emerald-950/40 text-emerald-200",
  model: "border-l-purple-600 bg-purple-950/40 text-purple-200",
  human: "border-l-amber-600 bg-amber-950/40 text-amber-200",
  system: "border-l-sky-600 bg-sky-950/40 text-sky-200",
};

/** Maps evidence source to its `canon.source.*` i18n key. Module-level (no
 * hooks); translated at the render site inside the component. */
const SOURCE_LABEL_KEYS: Record<string, string> = {
  deterministic: "canon.source.deterministic",
  model: "canon.source.model",
  human: "canon.source.human",
  system: "canon.source.system",
};

function EvidenceCard({ item }: { item: EvidenceItem }) {
  const t = useT("sage");
  const source = (item.source as string | undefined) ?? "deterministic";
  const cls =
    SOURCE_STYLES[source] ??
    "border-l-gray-600 bg-gray-900/40 text-gray-200";
  const payload =
    (item.payload as Record<string, unknown> | undefined) ?? {};
  return (
    <div
      className={`border-l-4 px-3 py-2 rounded-r text-xs ${cls}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[10px] uppercase tracking-wider opacity-80">
          {SOURCE_LABEL_KEYS[source] ? t(SOURCE_LABEL_KEYS[source]) : source}
        </span>
        <span className="font-semibold">{item.kind ?? t("canon.evidenceFallback")}</span>
      </div>
      <pre className="whitespace-pre-wrap font-mono text-[11px] leading-snug">
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
}

function ActionCard({
  action,
  onApprove,
  onReject,
  busy,
}: {
  action: ActionItem;
  onApprove: () => void;
  onReject: () => void;
  busy: boolean;
}) {
  const t = useT("sage");
  const score = action.stability_score;
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-4 mb-3 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="text-xs font-mono text-gray-500">{action.path}</div>
          <div className="text-sm text-gray-100 font-medium mt-0.5">
            {action.kind}
          </div>
        </div>
        <div className="text-right">
          <span className="inline-block px-2 py-0.5 rounded text-[10px] font-mono bg-amber-950 text-amber-300 border border-amber-800">
            {t("canon.pendingApproval")}
          </span>
          {score !== null && (
            <div className="mt-1 text-[11px] text-gray-400">
              {t("canon.stability", { score: score.toFixed(2) })}
            </div>
          )}
        </div>
      </div>

      {/* Params summary */}
      <pre className="text-[11px] text-gray-300 font-mono whitespace-pre-wrap bg-gray-900/40 rounded px-2 py-1 mb-2">
        {JSON.stringify(action.params, null, 2)}
      </pre>

      {/* Risk reasons */}
      {action.risk_reasons.length > 0 && (
        <div className="mb-2">
          <div className="text-[11px] font-semibold text-gray-400 mb-1 uppercase tracking-wide">
            {t("canon.riskReasons")}
          </div>
          <div className="space-y-1">
            {action.risk_reasons.map((ev, i) => (
              <EvidenceCard key={i} item={ev} />
            ))}
          </div>
        </div>
      )}

      {/* Evidence by source — keeps deterministic vs model vs human visually
          distinct per Handoff §13. */}
      {(action.deterministic_evidence.length > 0 ||
        action.model_evidence.length > 0 ||
        action.human_evidence.length > 0) && (
        <div className="mb-2">
          <div className="text-[11px] font-semibold text-gray-400 mb-1 uppercase tracking-wide">
            {t("canon.evidence")}
          </div>
          <div className="space-y-1">
            {[
              ...action.deterministic_evidence,
              ...action.model_evidence,
              ...action.human_evidence,
            ].map((ev, i) => (
              <EvidenceCard key={i} item={ev} />
            ))}
          </div>
        </div>
      )}

      {/* Affected paths */}
      {action.affected_paths.length > 0 && (
        <div className="mb-3">
          <div className="text-[11px] font-semibold text-gray-400 mb-1 uppercase tracking-wide">
            {t("canon.willAffect")}
          </div>
          <ul className="text-[11px] font-mono text-gray-300 list-disc list-inside">
            {action.affected_paths.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-2 mt-2">
        <button
          type="button"
          disabled={busy}
          onClick={onApprove}
          className="flex-1 rounded bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 px-3 py-2 text-sm font-medium text-white transition-colors"
        >
          {t("canon.approveApply")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onReject}
          className="flex-1 rounded bg-red-900 hover:bg-red-800 disabled:opacity-40 px-3 py-2 text-sm font-medium text-white transition-colors"
        >
          {t("canon.reject")}
        </button>
      </div>
    </div>
  );
}

export function CanonicalizationQueueView() {
  const t = useT("sage");
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const events = useEvents();

  const refresh = useCallback(async () => {
    try {
      const res = await api.canonListActions("pending_approval");
      setError(null);
      setActions(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  // Refresh on any canonicalization_* event. Per Handoff §15.1 — the
  // EventBus is not durable, so we always re-fetch from the index rather
  // than mutating local state from event payloads.
  useEffect(() => {
    if (events.length === 0) return;
    const last = events[events.length - 1];
    if (
      last &&
      typeof last.event_type === "string" &&
      last.event_type.startsWith("canonicalization_")
    ) {
      let cancelled = false;
      queueMicrotask(() => {
        if (!cancelled) void refresh();
      });
      return () => {
        cancelled = true;
      };
    }
  }, [events, refresh]);

  const onApprove = useCallback(
    async (path: string) => {
      setBusyPath(path);
      try {
        await api.canonApproveAction(path);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyPath(null);
      }
    },
    [refresh],
  );

  const onReject = useCallback(
    async (path: string) => {
      const reason = window.prompt(t("canon.rejectPrompt")) ?? undefined;
      setBusyPath(path);
      try {
        await api.canonRejectAction(path, reason);
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusyPath(null);
      }
    },
    [refresh, t],
  );

  const empty = useMemo(
    () => !loading && !error && actions.length === 0,
    [loading, error, actions.length],
  );

  return (
    <div className="flex flex-col h-full">
      <header className="border-b border-gray-800 bg-gray-950/80 px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-100">
            {t("canon.title")}
          </h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {t("canon.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            className="text-xs px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-gray-200"
          >
            {t("canon.refresh")}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {loading && <div className="text-sm text-gray-500">{t("canon.loading")}</div>}
        {error && (
          <div className="text-sm text-red-400 bg-red-950/40 border border-red-900 rounded p-2 mb-3">
            {error}
          </div>
        )}
        {empty && (
          <div className="text-sm text-gray-500 italic mt-12 text-center">
            {t("canon.empty")}
          </div>
        )}
        {actions.map((a) => (
          <ActionCard
            key={a.path}
            action={a}
            onApprove={() => onApprove(a.path)}
            onReject={() => onReject(a.path)}
            busy={busyPath === a.path}
          />
        ))}
      </div>
    </div>
  );
}
