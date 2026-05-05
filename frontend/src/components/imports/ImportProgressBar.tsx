import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "../common/Icon";
import type { ImportProgress } from "../../hooks/useImportProgress";

export interface ImportProgressBarProps {
  progress: ImportProgress;
}

/** Compact progress strip rendered inside ``PluginUploadModal`` while an
 * ingest_compile_batch run is in flight. Shows ``chunk N / M`` + an
 * elapsed timer; sticks around briefly after BATCH_COMPLETE so the user
 * sees the final tally. Failed chunks surface as a separate pill — the
 * backend's per-chunk fix preserves earlier work, so partial completion
 * is normal not exceptional.
 */
export function ImportProgressBar({ progress }: ImportProgressBarProps) {
  const { t } = useTranslation();
  const elapsed = useElapsedSeconds(progress.startedAt, progress.completedAt);

  const total = Math.max(progress.chunkCount, 1);
  const fillPct = Math.min(100, Math.round((progress.chunksDone / total) * 100));
  const isDone = progress.status === "done";

  return (
    <div className="mt-4 rounded-lg border border-white/10 bg-gray-900 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-[11px] font-medium text-gray-300">
          <Icon
            name={isDone ? "check_circle" : "auto_awesome"}
            size={14}
            className={isDone ? "text-accent-light" : "text-gray-400 animate-pulse"}
          />
          <span>
            {isDone
              ? t("imports.progress.done")
              : t("imports.progress.compiling")}
          </span>
        </div>
        <span className="font-mono text-[10px] text-gray-500">
          {formatElapsed(elapsed)}
        </span>
      </div>

      {/* Progress fill */}
      <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            isDone ? "bg-accent-light" : "bg-accent-light/70"
          }`}
          style={{ width: `${fillPct}%` }}
        />
      </div>

      {/* Counts row */}
      <div className="flex items-center gap-3 mt-2 text-[10px] font-mono text-gray-400">
        <span>
          {t("imports.progress.chunks", {
            done: progress.chunksDone,
            total: progress.chunkCount,
          })}
        </span>
        <span className="text-accent-light">
          {t("imports.progress.notes", { count: progress.notesCreated })}
        </span>
        {progress.chunksFailed > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 text-red-300">
            <Icon name="error_outline" size={11} />
            {t("imports.progress.failed", { count: progress.chunksFailed })}
          </span>
        )}
      </div>
    </div>
  );
}

function useElapsedSeconds(startedAt: number, completedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (completedAt) return;
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [completedAt]);
  const end = completedAt ?? now;
  return Math.max(0, Math.floor((end - startedAt) / 1_000));
}

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${String(s).padStart(2, "0")}s`;
}
